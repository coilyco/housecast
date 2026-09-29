from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from housecast.room import models
from housecast.room.engine import Engine, PromptRefusedError
from housecast.room.store import Room
from housecast.room.subjects import SubjectsError, load_subjects

SUBJECTS = [
    {"id": "s1", "label": "Violet", "system": "you are one"},
    {"id": "s2", "label": "Teal", "system": "you are two"},
    {"id": "s3", "label": "Amber", "system": "you are three"},
    {"id": "s4", "label": "Rose", "system": "you are four"},
]
CFG = models.Settings(proxy="http://proxy", model="route", jev_model="jev")


def proxy(replies: dict[str, Any], jev: Any = 2.0) -> httpx.MockTransport:
    """Answers keyed by system prompt: a string, "" for empty, or an int status to fail with."""

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["x-agent-session-id"] == "housecast-room"
        if request.url.path == "/v1/systemone":
            if isinstance(jev, int) and not isinstance(jev, bool) and jev >= 400:
                return httpx.Response(jev)
            return httpx.Response(200, json={"answers": {"divergence": {"score": jev}}})
        assert body["user"] == "housecast-room"
        reply = replies[body["messages"][0]["content"]]
        if isinstance(reply, int):
            return httpx.Response(reply)
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    return httpx.MockTransport(handle)


async def run(
    room: Room, transport: httpx.MockTransport, text: str = "do you like purple?"
) -> Engine:
    async with httpx.AsyncClient(transport=transport) as client:
        engine = Engine(room, CFG, client)
        if room.phase != "submissions":
            engine.set_phase("submissions")
        engine.submit(text)
        await engine.drain()
    return engine


def test_fan_out_records_every_subject_and_scores_with_jev(tmp_path: Path) -> None:
    room = Room(subjects=SUBJECTS, log_path=tmp_path / "room.jsonl")
    replies = {
        "you are one": "teal",
        "you are two": "",
        "you are three": 500,
        "you are four": "rose",
    }
    asyncio.run(run(room, proxy(replies, jev=2.0)))
    states = {a["subject_id"]: a["state"] for a in room.snapshot()["answers"]}
    assert states == {"s1": "done", "s2": "empty", "s3": "failed", "s4": "done"}
    failed = next(a for a in room.snapshot()["answers"] if a["state"] == "failed")
    assert failed["reason"] == "the model route answered 500"
    assert all("started_at" in a for a in room.snapshot()["answers"])
    [divergence] = room.snapshot()["divergence"]
    assert divergence == {
        "prompt_id": divergence["prompt_id"],
        "state": "done",
        "score": 0.5,
        "method": "stance",
    }


def test_jev_failure_falls_back_to_lexical(tmp_path: Path) -> None:
    room = Room(subjects=SUBJECTS)
    replies = {k["system"]: f"answer {i}" for i, k in enumerate(SUBJECTS)}
    asyncio.run(run(room, proxy(replies, jev=503)))
    [divergence] = room.snapshot()["divergence"]
    assert divergence["method"] == "lexical" and divergence["state"] == "done"


def test_fewer_than_two_answers_fails_divergence() -> None:
    room = Room(subjects=SUBJECTS)
    replies = {
        "you are one": "only me",
        "you are two": "",
        "you are three": 500,
        "you are four": "",
    }
    asyncio.run(run(room, proxy(replies)))
    [divergence] = room.snapshot()["divergence"]
    assert divergence["state"] == "failed"


def test_restart_log_replays_the_same_snapshot_and_skips_a_torn_line(tmp_path: Path) -> None:
    log = tmp_path / "room.jsonl"
    room = Room(subjects=SUBJECTS, log_path=log)
    asyncio.run(run(room, proxy({s["system"]: s["label"] for s in SUBJECTS})))
    with log.open("a") as f:
        f.write('{"rev": 999, "kind": "pro')
    again = Room(subjects=SUBJECTS, log_path=log)
    again.load()
    assert again.snapshot() == room.snapshot()


def test_resume_reruns_answers_a_restart_cut_off(tmp_path: Path) -> None:
    log = tmp_path / "room.jsonl"
    room = Room(subjects=SUBJECTS, log_path=log)
    room.emit("prompt", {"id": "p1", "seq": 1, "text": "hi", "at": "t"})
    room.emit("divergence", {"prompt_id": "p1", "state": "pending"})
    for s in SUBJECTS:
        room.emit("answer", {"prompt_id": "p1", "subject_id": s["id"], "state": "running"})
    restarted = Room(subjects=SUBJECTS, log_path=log)
    restarted.load()

    async def resume() -> int:
        async with httpx.AsyncClient(
            transport=proxy({s["system"]: s["id"] for s in SUBJECTS})
        ) as c:
            engine = Engine(restarted, CFG, c)
            count = engine.resume()
            await engine.drain()
            return count

    assert asyncio.run(resume()) == 4
    assert {a["state"] for a in restarted.snapshot()["answers"]} == {"done"}
    assert restarted.snapshot()["divergence"][0]["state"] == "done"


def test_intake_refuses_with_a_reason() -> None:
    room = Room(subjects=SUBJECTS)
    engine = Engine(room, CFG, httpx.AsyncClient())
    with pytest.raises(PromptRefusedError, match="not open"):
        engine.validate("hello")
    engine.set_phase("submissions")
    with pytest.raises(PromptRefusedError, match="empty"):
        engine.validate("   ")
    with pytest.raises(PromptRefusedError, match="over 280"):
        engine.validate("x" * 281)


def test_markup_is_stripped_and_lexical_is_bounded() -> None:
    assert models.strip_markup('hi <tool_call>{"x":1}</tool_call> there') == "hi  there"
    wrapped = '<tool_calls><invoke name="exec"><parameter name="c">ls</parameter></invoke>'
    wrapped += "</tool_calls>"
    assert models.strip_markup(wrapped) == ""
    assert models.strip_markup("<tool_calls>\n\n</tool_calls>") == ""
    assert models.strip_markup("Plan first. <tool_calls>") == "Plan first."
    tag = f"{chr(0xFF5C) * 2}DSML{chr(0xFF5C) * 2}"
    fence = f'<{tag} calls>\n<{tag} invoke name="bash">\n</{tag} invoke>\n</{tag} calls>'
    assert models.strip_markup(f"Checking. {fence}") == "Checking."
    assert models.strip_markup(fence) == ""
    assert models.strip_markup(f"Cut off {fence[:30]}") == "Cut off"
    assert models.strip_markup("DSML is a markup format.") == "DSML is a markup format."
    assert models.lexical(["a b", "a b"]) == 0.0
    assert models.lexical(["a", "b"]) == 1.0
    assert models.jev_body("p", ["w", "x"], "k", "m") == models.jev_body("p", ["w", "x"], "k", "m")
    assert (
        models.expected_level({"answers": {"divergence": {"probabilities": {"0": 0.5, "4": 0.5}}}})
        == 2.0
    )


def test_subjects_need_a_label_and_resolve_system_files(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("system one")
    good = tmp_path / "subjects.json"
    good.write_text(
        json.dumps({"subjects": [{"id": "a", "label": "Violet", "system_file": "one.md"}]})
    )
    assert load_subjects(good)[0]["system"] == "system one"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"id": "a", "system": "x"}]))
    with pytest.raises(SubjectsError, match="label"):
        load_subjects(bad)


def test_subjects_pass_their_display_fields_through(tmp_path: Path) -> None:
    path = tmp_path / "subjects.json"
    entry = {
        "id": "a",
        "label": "Violet",
        "system": "s",
        "color": "#123456",
        "logo": "creatures/violet.png",
        "role": "Tester",
        "line": "Checks it twice.",
        "unknown": "dropped",
    }
    path.write_text(json.dumps([entry]))
    subject = load_subjects(path)[0]
    assert subject["logo"] == "creatures/violet.png" and subject["role"] == "Tester"
    assert subject["line"] == "Checks it twice." and subject["color"] == "#123456"
    assert "unknown" not in subject


def test_a_round_withholds_direction_until_the_split() -> None:
    room = Room(subjects=SUBJECTS)
    asyncio.run(run(room, proxy({s["system"]: s["label"] for s in SUBJECTS})))
    engine = Engine(room, CFG, httpx.AsyncClient())
    prompt_id = room.prompts[0]["id"]
    assert all("text" not in a for a in room.snapshot()["answers"])
    assert "text" not in room.snapshot("screen")["prompts"][0]
    engine.pick(prompt_id)
    assert room.phase == "grading" and all("text" in a for a in room.snapshot()["answers"])
    engine.grade(1, "d1", {"s1": "pass", "s2": "fail"}, {"s2": "too vague"})
    engine.grade(1, "d2", {"s1": "fail"}, {})
    engine.grade(1, "d2", {"s1": "pass"}, {})  # a re-grade replaces
    attendee = room.snapshot()
    assert attendee["round"]["graded"] == 2 and "split" not in attendee["rounds"][0]
    graded = room.project(
        {"rev": 1, "at": "t", "kind": "grades", "data": {"n": 1, "device": "d3", "grades": {}}},
        "attendee",
    )
    assert graded["data"] == {"n": 1, "graded": 2}
    engine.set_phase("split")
    split = room.snapshot()["rounds"][0]["split"]
    assert split["s1"] == {"pass": 2, "fail": 0, "share": 1.0}
    assert split["s2"]["share"] == 0.0 and split["s3"]["share"] is None
    assert "failures" not in room.snapshot()
    engine.set_phase("closing")
    assert room.snapshot()["failures"] == [{"n": 1, "subject_id": "s2", "reason": "too vague"}]
    assert room.snapshot("screen")["failures"] == [{"n": 1, "subject_id": "s2"}]


def test_grades_refuse_outside_grading_and_for_a_past_round() -> None:
    room = Room(subjects=SUBJECTS)
    engine = Engine(room, CFG, httpx.AsyncClient())
    with pytest.raises(PromptRefusedError, match="not open"):
        engine.grade(1, "d", {"s1": "pass"}, {})
    room.emit("prompt", {"id": "p1", "seq": 1, "text": "hi", "at": "t"})
    room.emit("prompt", {"id": "p2", "seq": 2, "text": "yo", "at": "t"})
    engine.pick("p1")
    engine.pick("p2")
    with pytest.raises(PromptRefusedError, match="round is over"):
        engine.grade(1, "d", {"s1": "pass"}, {})
    with pytest.raises(PromptRefusedError, match="pass or fail"):
        engine.grade(2, "d", {"s1": "maybe"}, {})


def flaky(statuses: list[int], delay: float = 0.0) -> tuple[httpx.MockTransport, list[int]]:
    """Answers each chat call with the next status, 200 once the list runs out."""
    calls: list[int] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/systemone":
            return httpx.Response(200, json={"answers": {"divergence": {"score": 1.0}}})
        calls.append(1)
        if delay:
            await asyncio.sleep(delay)
        status = statuses[len(calls) - 1] if len(calls) <= len(statuses) else 200
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    return httpx.MockTransport(handle), calls


def one_subject_room() -> Room:
    return Room(subjects=SUBJECTS[:2])


async def run_with(room: Room, transport: httpx.MockTransport, cfg: models.Settings) -> None:
    async with httpx.AsyncClient(transport=transport) as client:
        engine = Engine(room, cfg, client)
        engine.set_phase("submissions")
        engine.submit("hi")
        await engine.drain()


def test_a_transient_error_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("housecast.room.engine.RETRY_PAUSE", 0.0)
    room = one_subject_room()
    transport, calls = flaky([503])
    asyncio.run(run_with(room, transport, CFG))
    states = sorted(a["state"] for a in room.snapshot()["answers"])
    assert states == ["done", "done"] and len(calls) == 3  # one subject retried once


def test_a_client_error_is_not_retried_and_two_transient_errors_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("housecast.room.engine.RETRY_PAUSE", 0.0)
    room = Room(subjects=SUBJECTS[:1])
    transport, calls = flaky([400])
    asyncio.run(run_with(room, transport, CFG))
    assert room.snapshot()["answers"][0]["state"] == "failed" and len(calls) == 1
    room = Room(subjects=SUBJECTS[:1])
    transport, calls = flaky([502, 502])
    asyncio.run(run_with(room, transport, CFG))
    assert room.snapshot()["answers"][0]["state"] == "failed" and len(calls) == 2


def test_a_stuck_subject_fails_at_the_deadline_so_the_round_can_be_picked() -> None:
    room = Room(subjects=SUBJECTS[:2])
    transport, _ = flaky([], delay=5.0)
    cfg = models.Settings(proxy="http://proxy", model="route", jev_model="jev", answer_deadline=0.2)
    asyncio.run(run_with(room, transport, cfg))
    answers = room.snapshot()["answers"]
    assert {a["state"] for a in answers} == {"failed"}
    assert {a["reason"] for a in answers} == {"the subject timed out"}
    assert room.snapshot()["divergence"][0]["state"] == "failed"
