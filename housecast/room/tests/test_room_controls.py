"""Presenter controls on a case: delete it, run its round again. See docs/room-cases.md."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from housecast.room.server import create_app
from housecast.room.store import Room
from housecast.room.tests.test_room import CFG, SUBJECTS, proxy
from housecast.room.tests.test_server import TOKEN as HEADERS

CASES = "/api/control/cases"


def controlled(log: Path | None = None) -> tuple[TestClient, Room, list[str]]:
    """A room whose upstream counts its calls, so a re-run shows as fresh calls."""
    room = Room(subjects=SUBJECTS, log_path=log)
    inner = proxy({s["system"]: s["label"] for s in SUBJECTS})
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return inner.handle_request(request)

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    app = create_app(room, CFG, "tok", rate_seconds=20.0, client=upstream, page=None)
    return TestClient(app), room, calls


def add(tc: TestClient, text: str) -> str:
    made = tc.post(CASES, json={"text": text}, headers=HEADERS)
    assert made.status_code == 201
    return str(made.json()["id"])


def test_delete_and_run_need_the_control_token_and_a_known_case() -> None:
    tc, room, _ = controlled()
    with tc:
        case = add(tc, "a case")
        assert tc.delete(f"{CASES}/{case}").status_code == 403
        assert tc.post(f"{CASES}/{case}/run").status_code == 403
        missing = tc.delete(f"{CASES}/nope", headers=HEADERS)
        assert (missing.status_code, missing.json()) == (404, {"reason": "no such prompt"})
        assert tc.post(f"{CASES}/nope/run", headers=HEADERS).status_code == 404
    assert [p["id"] for p in room.prompts] == [case]


def test_a_deleted_case_leaves_the_room_and_a_replay_does_not_revive_it(tmp_path: Path) -> None:
    log = tmp_path / "room.jsonl"
    tc, room, _ = controlled(log)
    with tc:
        first, second = add(tc, "one"), add(tc, "two")
        gone = tc.delete(f"{CASES}/{first}", headers=HEADERS)
        assert (gone.status_code, gone.json()) == (200, {"id": first})
        third = add(tc, "three")
        snap = tc.get("/api/control/room", headers=HEADERS).json()
    assert [p["id"] for p in snap["prompts"]] == [second, third]
    assert {a["prompt_id"] for a in snap["answers"]} == {second, third}
    assert {d["prompt_id"] for d in snap["divergence"]} == {second, third}
    assert [p["seq"] for p in room.prompts] == [2, 3], "a new case never reuses a live seq"
    replay = Room(subjects=SUBJECTS, log_path=log)
    replay.load()
    assert [p["id"] for p in replay.prompts] == [second, third]
    assert first not in {k[0] for k in replay.answers} and first not in replay.divergence


def test_a_case_in_a_round_cannot_be_deleted_or_run_again() -> None:
    tc, room, _ = controlled()
    with tc:
        case = add(tc, "graded")
        assert (
            tc.post("/api/control/pick", json={"prompt_id": case}, headers=HEADERS).status_code
            == 200
        )
        gone = tc.delete(f"{CASES}/{case}", headers=HEADERS)
        again = tc.post(f"{CASES}/{case}/run", headers=HEADERS)
    assert gone.status_code == 409 and again.status_code == 409
    assert [p["id"] for p in room.prompts] == [case]


def test_running_a_case_again_asks_every_subject_and_scores_it_in_the_log(tmp_path: Path) -> None:
    log = tmp_path / "room.jsonl"
    tc, _, calls = controlled(log)
    with tc:
        case = add(tc, "a case")
        tc.get("/api/control/room", headers=HEADERS)
        before = len([c for c in calls if c == "/v1/chat/completions"])
        ran = tc.post(f"{CASES}/{case}/run", headers=HEADERS)
        snap = tc.get("/api/control/room", headers=HEADERS).json()
    assert (ran.status_code, ran.json()) == (202, {"id": case})
    assert before == len(SUBJECTS)
    assert len([c for c in calls if c == "/v1/chat/completions"]) == 2 * len(SUBJECTS)
    assert len([c for c in calls if c == "/v1/systemone"]) == 2
    assert [d["state"] for d in snap["divergence"]] == ["done"]
    assert {a["state"] for a in snap["answers"]} == {"done"}
    kinds = [json.loads(line)["kind"] for line in log.read_text().splitlines()]
    assert kinds.count("rerun") == 1 and kinds.count("prompt") == 1


def test_a_case_still_running_refuses_a_second_run() -> None:
    tc, room, _ = controlled()
    with tc:
        case = add(tc, "a case")
        room.divergence[case] = {"prompt_id": case, "state": "scoring"}
        busy = tc.post(f"{CASES}/{case}/run", headers=HEADERS)
    assert (busy.status_code, busy.json()) == (409, {"reason": "that case is still running"})
