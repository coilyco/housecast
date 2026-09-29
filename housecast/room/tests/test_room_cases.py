"""Commitments, presenter-prepared cases, the withholding rule, and an old log's replay."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from housecast.room.engine import MAX_COMMITMENT
from housecast.room.server import create_app
from housecast.room.store import Room
from housecast.room.tests.serving import TOKEN, Served, free_port, stub
from housecast.room.tests.test_room import CFG, SUBJECTS, proxy
from housecast.room.tests.test_server import TOKEN as HEADERS

CASES = "/api/control/cases"


def client(rate: float = 20.0, log: Path | None = None) -> tuple[TestClient, Room]:
    room = Room(subjects=SUBJECTS, log_path=log)
    upstream = httpx.AsyncClient(transport=proxy({s["system"]: s["label"] for s in SUBJECTS}))
    app = create_app(room, CFG, "tok", rate_seconds=rate, client=upstream, page=None)
    return TestClient(app), room


def prompt_event(queue: asyncio.Queue[dict[str, Any]]) -> dict[str, Any]:
    """The prompt event a listener was sent, past the answers of earlier prompts."""
    while (event := queue.get_nowait())["kind"] != "prompt":
        pass
    data: dict[str, Any] = event["data"]
    return data


def open_room(tc: TestClient, phase: str = "submissions") -> None:
    tc.post("/api/control/phase", json={"phase": phase}, headers=HEADERS)


def test_commitment_is_stripped_capped_and_defaults_to_empty() -> None:
    tc, room = client()
    with tc:
        open_room(tc)
        kept = tc.post(
            "/api/prompts", json={"text": "a", "commitment": "  refuses  ", "device": "1"}
        )
        bare = tc.post("/api/prompts", json={"text": "b", "device": "2"})
        nulled = tc.post("/api/prompts", json={"text": "c", "commitment": None, "device": "3"})
        edge = "x" * MAX_COMMITMENT
        at_cap = tc.post("/api/prompts", json={"text": "d", "commitment": edge, "device": "4"})
        over = tc.post("/api/prompts", json={"text": "e", "commitment": edge + "y", "device": "5"})
    assert [r.status_code for r in (kept, bare, nulled, at_cap)] == [201] * 4
    assert over.status_code == 422
    assert over.json() == {"reason": "the commitment is over 140 characters"}
    assert [p["commitment"] for p in room.prompts] == ["refuses", "", "", edge]
    assert {p["source"] for p in room.prompts} == {"attendee"}
    assert len(room.prompts) == 4, "a refused commitment must not create a prompt"


def test_a_refused_commitment_does_not_spend_the_rate_limit() -> None:
    tc, _ = client()
    with tc:
        open_room(tc)
        too_long = {"text": "a", "commitment": "x" * 141}
        assert tc.post("/api/prompts", json=too_long).status_code == 422
        assert tc.post("/api/prompts", json={"text": "a"}).status_code == 201


def test_case_endpoint_needs_the_control_token() -> None:
    tc, room = client()
    with tc:
        open_room(tc)
        body = {"text": "case", "commitment": "c"}
        assert tc.post(CASES, json=body).status_code == 403
        assert tc.post(CASES, json=body, headers={"X-Control-Token": "wrong"}).status_code == 403
    assert room.prompts == []


def test_case_round_trip_and_validation() -> None:
    tc, room = client()
    with tc:
        made = tc.post(CASES, json={"text": " a case ", "commitment": " hold "}, headers=HEADERS)
        assert made.status_code == 201 and made.json().keys() == {"id", "seq"}
        empty = tc.post(CASES, json={"text": " ", "commitment": "c"}, headers=HEADERS)
        assert empty.status_code == 422 and empty.json() == {"reason": "the prompt is empty"}
        long_text = tc.post(CASES, json={"text": "x" * 281}, headers=HEADERS)
        assert long_text.status_code == 422 and "280" in long_text.json()["reason"]
        long_commit = tc.post(CASES, json={"text": "ok", "commitment": "y" * 141}, headers=HEADERS)
        assert long_commit.json() == {"reason": "the commitment is over 140 characters"}
        bare = tc.post(CASES, json={"text": "no commitment"}, headers=HEADERS)
        answers = tc.get("/api/control/room", headers=HEADERS).json()
    [first, second] = room.prompts
    assert (first["text"], first["commitment"], first["source"]) == ("a case", "hold", "prepared")
    assert second["commitment"] == "" and second["source"] == "prepared" and bare.status_code == 201
    assert made.json() == {"id": first["id"], "seq": 1}
    # Fan-out and scoring ran exactly as for an attendee prompt.
    assert len([a for a in answers["answers"] if a["prompt_id"] == first["id"]]) == len(SUBJECTS)
    assert answers["divergence"][0]["state"] == "done"


def test_case_works_in_every_phase_but_attendee_intake_still_needs_submissions() -> None:
    tc, room = client()
    with tc:
        for phase in ("holding", "submissions", "grading", "split", "closing"):
            open_room(tc, phase)
            assert tc.post(CASES, json={"text": phase}, headers=HEADERS).status_code == 201
            expected = 201 if phase == "submissions" else 409
            attendee = tc.post("/api/prompts", json={"text": phase, "device": phase})
            assert attendee.status_code == expected
    assert room.phase == "closing"


def test_cases_are_outside_the_per_client_rate_and_burst_limits() -> None:
    tc, room = client(rate=60.0)
    with tc:
        open_room(tc)
        codes = [
            tc.post(CASES, json={"text": f"c{i}"}, headers=HEADERS).status_code for i in range(40)
        ]
        # Forty cases spent none of the attendee allowance for this address or device.
        first = tc.post("/api/prompts", json={"text": "mine", "device": "d"})
        second = tc.post("/api/prompts", json={"text": "mine again", "device": "d"})
    assert codes == [201] * 40 and first.status_code == 201 and second.status_code == 429
    assert [p["source"] for p in room.prompts].count("prepared") == 40


def test_prepared_text_and_commitment_are_withheld_until_picked() -> None:
    tc, room = client()
    with tc:
        open_room(tc)
        case = tc.post(CASES, json={"text": "secret case", "commitment": "secret"}, headers=HEADERS)
        tc.post("/api/prompts", json={"text": "attendee says", "commitment": "theirs"})
        queue = room.subscribe("attendee")
        screen_queue = room.subscribe("screen")
        presenter_queue = room.subscribe("presenter")
        again = tc.post(CASES, json={"text": "second", "commitment": "two"}, headers=HEADERS)
        views = {v: tc.get(f"/api/room?view={v}").json()["prompts"] for v in ("attendee", "screen")}
        views["presenter"] = tc.get("/api/control/room", headers=HEADERS).json()["prompts"]
        streamed = {
            "attendee": prompt_event(queue),
            "screen": prompt_event(screen_queue),
            "presenter": prompt_event(presenter_queue),
        }
        assert streamed["attendee"]["id"] == again.json()["id"]
        # A withheld value keeps the commitment key, and text goes as it does on screen.
        withheld = {
            "id": case.json()["id"],
            "seq": 1,
            "commitment": "",
            "at": views["attendee"][0]["at"],
        }
        assert views["attendee"][0] == withheld
        assert "text" not in streamed["attendee"] and streamed["attendee"]["commitment"] == ""
        assert "text" not in streamed["screen"] and streamed["screen"]["commitment"] == ""
        # An attendee prompt shows in full to attendees. The screen still drops its text
        # and its commitment with it, since the commitment would give the text away.
        assert views["attendee"][1]["text"] == "attendee says"
        assert views["attendee"][1]["commitment"] == "theirs"
        assert "text" not in views["screen"][1] and views["screen"][1]["commitment"] == ""
        # Only the presenter learns the source, and sees everything.
        assert all("source" not in p for v in ("attendee", "screen") for p in views[v])
        assert views["presenter"][0]["text"] == "secret case"
        assert views["presenter"][0]["commitment"] == "secret"
        assert views["presenter"][0]["source"] == "prepared"
        assert (
            streamed["presenter"]["text"] == "second"
            and streamed["presenter"]["source"] == "prepared"
        )
        tc.post("/api/control/pick", json={"prompt_id": case.json()["id"]}, headers=HEADERS)
        picked = {
            v: tc.get(f"/api/room?view={v}").json()["prompts"][0] for v in ("attendee", "screen")
        }
    for shown in picked.values():
        assert shown["text"] == "secret case" and shown["commitment"] == "secret"
        assert "source" not in shown


def test_a_log_from_before_commitments_replays_as_an_attendee_prompt(tmp_path: Path) -> None:
    log = tmp_path / "room.jsonl"
    old = {
        "rev": 1,
        "at": "t",
        "kind": "prompt",
        "data": {"id": "p1", "seq": 1, "text": "hi", "at": "t"},
    }
    log.write_text(json.dumps(old) + "\n")
    room = Room(subjects=SUBJECTS, log_path=log)
    room.load()
    assert room.rev == 1
    assert room.prompts == [
        {"id": "p1", "seq": 1, "text": "hi", "at": "t", "commitment": "", "source": "attendee"}
    ]
    assert room.snapshot("presenter")["prompts"][0]["source"] == "attendee"
    assert room.snapshot()["prompts"][0]["commitment"] == ""
    assert room.snapshot("screen")["prompts"][0] == {
        "id": "p1",
        "seq": 1,
        "at": "t",
        "commitment": "",
    }


def test_a_new_prompt_survives_a_restart_with_commitment_and_source(tmp_path: Path) -> None:
    log = tmp_path / "room.jsonl"
    tc, room = client(log=log)
    with tc:
        open_room(tc)
        tc.post(CASES, json={"text": "case", "commitment": "held"}, headers=HEADERS)
        tc.post("/api/prompts", json={"text": "theirs", "commitment": "kept"})
    again = Room(subjects=SUBJECTS, log_path=log)
    again.load()
    assert again.snapshot("presenter") == room.snapshot("presenter")
    assert [(p["source"], p["commitment"]) for p in again.prompts] == [
        ("prepared", "held"),
        ("attendee", "kept"),
    ]


async def add_cases_while_grading(base: str) -> None:
    headers = {"x-control-token": TOKEN}
    async with httpx.AsyncClient(base_url=base, timeout=30, headers=headers) as ctl:
        await ctl.post("api/control/phase", json={"phase": "submissions"})
        probe = (await ctl.post("api/prompts", json={"text": "probe", "device": "p0"})).json()
        await asyncio.sleep(0.3)
        await ctl.post("api/control/pick", json={"prompt_id": probe["id"]})

        async def grade(i: int) -> None:
            async with httpx.AsyncClient(base_url=base, timeout=30) as one:
                body = {"round": 1, "device": f"d{i}", "grades": {"s1": "pass"}}
                await one.post("api/grades", json=body)

        async def case(i: int) -> None:
            body = {"text": f"case {i}", "commitment": f"c{i}"}
            assert (await ctl.post("api/control/cases", json=body)).status_code == 201

        await asyncio.gather(*(grade(i) for i in range(20)), *(case(i) for i in range(20)))
        await asyncio.sleep(0.5)


def test_concurrent_cases_and_grades_keep_revs_contiguous(tmp_path: Path) -> None:
    """The case handler is async, so it cannot race `emit` the way a sync one did."""
    log = tmp_path / "room.jsonl"
    served = Served(log, free_port(), stub(delay=0.05)).start()
    try:
        asyncio.run(add_cases_while_grading(served.base))
    finally:
        served.stop()
    events = [json.loads(line) for line in log.read_text().splitlines()]
    revs = [e["rev"] for e in events]
    assert revs == list(range(1, len(revs) + 1)), "revs repeat or skip under concurrent cases"
    prepared = [e for e in events if e["kind"] == "prompt" and e["data"]["source"] == "prepared"]
    assert len(prepared) == 20 and {e["data"]["seq"] for e in prepared} == set(range(2, 22))
