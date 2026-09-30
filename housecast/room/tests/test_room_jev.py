"""Jev's reply check per answer, its confidence on the divergence, and the PASS reason.

Spec: teable:coilyco/housecast#8520. Pages read `answer.jev`, `divergence.confidence`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from housecast.room.engine import NO_REPLY, Engine, PromptRefusedError
from housecast.room.store import Room
from housecast.room.tests.test_room import CFG, SUBJECTS

PROBS = {"0": 0.0, "1": 0.06, "2": 0.35, "3": 0.39, "4": 0.2}
SAYS = {
    "you are one": "teal",
    "you are two": "amber",
    "you are three": "rose",
    "you are four": "violet",
}


def jev_proxy(
    replies: dict[str, Any], replied: float = 0.9, fail: tuple[str, ...] = ()
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/v1/systemone":
            kind = "replied" if "replied" in body["questions"] else "divergence"
            if kind in fail:
                return httpx.Response(500)
            if kind == "replied":
                return httpx.Response(200, json={"answers": {"replied": {"noul": replied}}})
            scored = {"score": 2.0, "confidence": 0.43, "probabilities": PROBS}
            return httpx.Response(200, json={"answers": {"divergence": scored}})
        reply = replies[body["messages"][0]["content"]]
        if isinstance(reply, int):
            return httpx.Response(reply)
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    return httpx.MockTransport(handle)


async def play(room: Room, transport: httpx.MockTransport) -> Engine:
    async with httpx.AsyncClient(transport=transport) as client:
        engine = Engine(room, CFG, client)
        engine.set_phase("submissions")
        engine.prepare("a case")
        await engine.drain()
    return engine


def answers(room: Room) -> dict[str, dict[str, Any]]:
    return {a["subject_id"]: a for a in room.snapshot("presenter")["answers"]}


def test_each_answer_carries_a_reply_check_and_the_divergence_carries_confidence() -> None:
    room = Room(subjects=SUBJECTS)
    asyncio.run(play(room, jev_proxy({**SAYS, "you are two": "", "you are three": 500})))
    got = answers(room)
    for subject_id in ("s1", "s4"):
        assert got[subject_id]["jev"] == {
            "replied": True,
            "confidence": 0.9,
            "p": 0.9,
            "source": "jev",
        }
    assert got["s2"]["state"] == "empty" and got["s2"]["jev"] == NO_REPLY
    assert got["s3"]["state"] == "failed" and got["s3"]["jev"] == NO_REPLY
    [divergence] = room.snapshot("presenter")["divergence"]
    assert divergence["confidence"] == 0.43 and divergence["probabilities"] == PROBS
    assert divergence["method"] == "stance" and divergence["score"] == 0.5


def test_a_low_probability_is_not_a_reply_and_its_confidence_is_the_other_side() -> None:
    room = Room(subjects=SUBJECTS)
    asyncio.run(play(room, jev_proxy(SAYS, replied=0.2)))
    assert answers(room)["s1"]["jev"] == {
        "replied": False,
        "confidence": 0.8,
        "p": 0.2,
        "source": "jev",
    }


def test_a_jev_failure_on_the_reply_check_is_null_and_never_blocks_the_round() -> None:
    room = Room(subjects=SUBJECTS)
    asyncio.run(play(room, jev_proxy(SAYS, fail=("replied",))))
    got = answers(room)
    assert {a["state"] for a in got.values()} == {"done"}
    assert all(a["jev"] is None for a in got.values())
    assert room.snapshot("presenter")["divergence"][0]["state"] == "done"


def test_the_word_overlap_fallback_has_no_confidence() -> None:
    room = Room(subjects=SUBJECTS)
    asyncio.run(play(room, jev_proxy(SAYS, fail=("divergence",))))
    [divergence] = room.snapshot("presenter")["divergence"]
    assert divergence["method"] == "lexical"
    assert divergence["confidence"] is None and divergence["probabilities"] is None


def test_a_restart_checks_an_answer_that_settled_before_jev_replied() -> None:
    room = Room(subjects=SUBJECTS)
    prompt = {
        "id": "p1",
        "seq": 1,
        "text": "a case",
        "commitment": "",
        "source": "prepared",
        "at": "t",
    }
    room.emit("prompt", prompt)
    for s in SUBJECTS:
        done = {"prompt_id": "p1", "subject_id": s["id"], "state": "done", "text": "hi"}
        room.emit("answer", {**done, "finished_at": "t"})
    room.emit("divergence", {"prompt_id": "p1", "state": "done", "score": 0.5, "method": "stance"})

    async def restart() -> None:
        async with httpx.AsyncClient(transport=jev_proxy(SAYS)) as client:
            engine = Engine(room, CFG, client)
            engine.resume()
            await engine.drain()

    asyncio.run(restart())
    assert all(a["jev"]["replied"] is True for a in answers(room).values())


async def graded(room: Room, marks: dict[str, str], reasons: dict[str, str]) -> Engine:
    async with httpx.AsyncClient(transport=jev_proxy(SAYS)) as client:
        engine = Engine(room, CFG, client)
        engine.set_phase("submissions")
        prompt = engine.prepare("a case")
        await engine.drain()
        engine.pick(prompt["id"])
        engine.grade(1, "d1", marks, reasons)
    return engine


def test_reasons_reach_attendees_once_results_open_and_never_the_screen() -> None:
    room = Room(subjects=SUBJECTS)
    marks = {"s1": "pass", "s2": "fail", "s3": "pass"}
    engine = asyncio.run(
        graded(room, marks, {"s1": "Named the trade-off.", "s2": "Hedged.", "s3": ""})
    )
    note = {"n": 1, "subject_id": "s1", "verdict": "pass", "reason": "Named the trade-off."}
    presenter = room.snapshot("presenter")
    assert presenter["notes"] == [note]
    assert [f["reason"] for f in presenter["failures"]] == ["Hedged."]
    # Still grading: nobody but the presenter reads a reason.
    attendee = room.snapshot("attendee")
    assert attendee["notes"] == [] and attendee["failures"] == []
    assert "Hedged." not in json.dumps(attendee) and "trade-off" not in json.dumps(attendee)
    for phase in ("split", "closing"):
        engine.set_phase(phase)
        open_ = room.snapshot("attendee")
        assert open_["notes"] == [note]
        assert [f["reason"] for f in open_["failures"]] == ["Hedged."]
        screen = json.dumps(room.snapshot("screen"))
        assert "notes" not in room.snapshot("screen")
        assert "Hedged." not in screen and "trade-off" not in screen
    assert room.snapshot("screen")["failures"] == [{"n": 1, "subject_id": "s2"}]


def test_a_grade_on_a_card_with_no_answer_is_refused_and_nothing_is_stored() -> None:
    room = Room(subjects=SUBJECTS)
    replies = {**SAYS, "you are two": "", "you are three": 500}

    async def go() -> None:
        async with httpx.AsyncClient(transport=jev_proxy(replies)) as client:
            engine = Engine(room, CFG, client)
            engine.set_phase("submissions")
            prompt = engine.prepare("a case")
            await engine.drain()
            engine.pick(prompt["id"])
            for bad in ("s2", "s3"):
                with pytest.raises(PromptRefusedError, match="no answer cannot be graded"):
                    engine.grade(1, "d1", {"s1": "pass", bad: "pass"}, {})
            assert engine.grade(1, "d1", {"s1": "pass", "s4": "fail"}, {}) == 1

    asyncio.run(go())
    assert room.grades == {(1, "d1"): {"s1": {"verdict": "pass"}, "s4": {"verdict": "fail"}}}
