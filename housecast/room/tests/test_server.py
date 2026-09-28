from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from starlette.requests import Request

from housecast.room.models import Settings
from housecast.room.server import client_of, create_app
from housecast.room.store import Room
from housecast.room.tests.test_room import SUBJECTS, proxy

CFG = Settings(proxy="http://proxy", model="route", jev_model="jev")
TOKEN = {"X-Control-Token": "tok"}


def client(rate: float = 20.0) -> tuple[TestClient, Room]:
    room = Room(subjects=SUBJECTS)
    upstream = httpx.AsyncClient(transport=proxy({s["system"]: s["label"] for s in SUBJECTS}))
    app = create_app(room, CFG, "tok", rate_seconds=rate, client=upstream, page=None)
    return TestClient(app), room


def test_snapshot_shows_labels_never_system_prompts() -> None:
    tc, _ = client()
    with tc:
        body = tc.get("/api/room").json()
    assert body["subjects"] == [{"id": s["id"], "label": s["label"]} for s in SUBJECTS]
    assert body["rev"] == 0 and body["phase"] == "holding"


def test_intake_pick_and_grade_through_http() -> None:
    tc, room = client()
    with tc:
        assert tc.post("/api/prompts", json={"text": "early"}).status_code == 409
        assert tc.post("/api/control/phase", json={"phase": "submissions"}).status_code == 403
        tc.post("/api/control/phase", json={"phase": "submissions"}, headers=TOKEN)
        ok = tc.post("/api/prompts", json={"text": "favourite colour?"})
        assert ok.status_code == 201 and "id" in ok.json()
        again = tc.post("/api/prompts", json={"text": "again"})
        assert again.status_code == 429 and again.json()["reason"].startswith("one prompt")
        other = tc.post("/api/prompts", json={"text": "again", "device": "phone-2"})
        assert other.status_code == 201
        empty = tc.post("/api/prompts", json={"text": "", "device": "phone-3"})
        assert empty.status_code == 422 and empty.json() == {"reason": "the prompt is empty"}
        assert tc.post("/api/prompts", json={"text": "x" * 300}).status_code == 422
        assert tc.get("/api/control/room").status_code == 403
        assert tc.get("/api/control/room", headers=TOKEN).json()["phase"] == "submissions"
        pick = {"prompt_id": ok.json()["id"]}
        assert tc.post("/api/control/pick", json=pick, headers=TOKEN).json()["n"] == 1
        sheet = {"round": 1, "device": "d1", "grades": {"s1": "pass"}}
        assert tc.post("/api/grades", json=sheet).json() == {"graded": 1}
        late = tc.post("/api/prompts", json={"text": "hi", "device": "phone-4"})
        assert late.status_code == 409 and late.json() == {"reason": "submissions are not open"}
    assert room.prompts[0]["text"] == "favourite colour?"


def test_screen_view_withholds_unpicked_prompt_text() -> None:
    tc, _ = client()
    with tc:
        tc.post("/api/control/phase", json={"phase": "submissions"}, headers=TOKEN)
        tc.post("/api/prompts", json={"text": "secret prompt"})
        assert "text" not in tc.get("/api/room?view=screen").json()["prompts"][0]
        assert tc.get("/api/room").json()["prompts"][0]["text"] == "secret prompt"
        assert tc.get("/api/room/events?view=presenter").status_code == 403


def test_kit_css_is_served_from_the_present_page() -> None:
    tc, _ = client()
    with tc:
        reply = tc.get("/kit.css")
    assert reply.status_code == 200 and reply.headers["content-type"].startswith("text/css")


def capped(burst: int, devices: int) -> tuple[TestClient, Room]:
    room = Room(subjects=SUBJECTS)
    upstream = httpx.AsyncClient(transport=proxy({s["system"]: s["label"] for s in SUBJECTS}))
    app = create_app(room, CFG, "tok", 20.0, burst, devices, client=upstream, page=None)
    return TestClient(app), room


def test_rotating_device_tokens_hit_the_address_ceiling() -> None:
    tc, _ = capped(burst=3, devices=100)
    with tc:
        tc.post("/api/control/phase", json={"phase": "submissions"}, headers=TOKEN)
        codes = [
            tc.post("/api/prompts", json={"text": f"p{i}", "device": f"minted-{i}"}).status_code
            for i in range(5)
        ]
        assert codes == [201, 201, 201, 429, 429]
        # A spoofed leftmost hop buys no fresh address, since the rightmost hop counts.
        spoofed = tc.post(
            "/api/prompts",
            json={"text": "p9", "device": "minted-9"},
            headers={"X-Forwarded-For": "1.2.3.4, testclient"},
        )
        assert spoofed.status_code == 429


def test_minted_grading_devices_run_out_per_address() -> None:
    tc, room = capped(burst=30, devices=2)
    with tc:
        tc.post("/api/control/phase", json={"phase": "submissions"}, headers=TOKEN)
        prompt_id = tc.post("/api/prompts", json={"text": "hi"}).json()["id"]
        tc.post("/api/control/pick", json={"prompt_id": prompt_id}, headers=TOKEN)
        codes = [
            tc.post(
                "/api/grades", json={"round": 1, "device": f"d{i}", "grades": {"s1": "fail"}}
            ).status_code
            for i in range(4)
        ]
        again = tc.post("/api/grades", json={"round": 1, "device": "d0", "grades": {"s1": "pass"}})
    assert codes == [200, 200, 429, 429] and again.status_code == 200
    assert room.graded(1) == 2


def request_with(headers: dict[str, str], peer: str = "10.0.0.9") -> Request:
    raw = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (peer, 5000)})


def test_client_of_keeps_the_single_ingress_hop_by_default() -> None:
    assert client_of(request_with({"X-Forwarded-For": "6.6.6.6, 203.0.113.7"})) == "203.0.113.7"
    assert client_of(request_with({})) == "10.0.0.9"


def test_client_of_reads_the_viewer_behind_cloudfront_and_a_google_balancer() -> None:
    # CloudFront appends the viewer, then the balancer appends `<client-ip>,<lb-ip>`.
    chain = "6.6.6.6, 198.51.100.10, 130.176.0.1, 34.120.0.1"
    assert client_of(request_with({"X-Forwarded-For": chain}), trusted_hops=3) == "198.51.100.10"
    # A shorter chain than configured never reaches past the leftmost entry.
    short = request_with({"X-Forwarded-For": "34.120.0.1"})
    assert client_of(short, trusted_hops=3) == "34.120.0.1"


def test_client_of_prefers_the_viewer_address_header() -> None:
    header = "CloudFront-Viewer-Address"
    v4 = request_with({header: "198.51.100.10:46532", "X-Forwarded-For": "1.1.1.1"})
    v6 = request_with({header: "2001:db8::7:46532"})
    assert client_of(v4, client_header=header) == "198.51.100.10"
    assert client_of(v6, client_header=header) == "2001:db8::7"
    fallback = request_with({"X-Forwarded-For": "198.51.100.10, 34.120.0.1"})
    assert client_of(fallback, trusted_hops=2, client_header=header) == "198.51.100.10"


def test_two_phones_behind_one_chain_are_two_addresses() -> None:
    room = Room(subjects=SUBJECTS)
    upstream = httpx.AsyncClient(transport=proxy({s["system"]: s["label"] for s in SUBJECTS}))
    app = create_app(room, CFG, "tok", 20.0, 1, 100, client=upstream, page=None, trusted_hops=3)
    with TestClient(app) as tc:
        tc.post("/api/control/phase", json={"phase": "submissions"}, headers=TOKEN)
        codes = [
            tc.post(
                "/api/prompts",
                json={"text": f"p{n}", "device": f"phone-{n}"},
                headers={"X-Forwarded-For": f"{phone}, 130.176.0.1, 34.120.0.1"},
            ).status_code
            for n, phone in enumerate(("198.51.100.10", "203.0.113.20", "198.51.100.10"))
        ]
        # Two phones each get their own window, and the first phone's second try waits.
        assert codes == [201, 201, 429]
