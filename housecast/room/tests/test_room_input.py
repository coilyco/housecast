"""A subject call names its case and the hash of the exact message it was sent.

Spec: teable:coilyco/housecast#8493. The proxy keeps the session header and drops `user`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import httpx

from housecast.room import models
from housecast.room.engine import Engine
from housecast.room.store import Room
from housecast.room.tests.test_room import CFG, SUBJECTS, proxy

FRAME = "Answer in under 150 words."


def recording(cfg: models.Settings = CFG) -> tuple[httpx.MockTransport, list[dict[str, str]]]:
    inner = proxy({s["system"]: s["label"] for s in SUBJECTS})
    seen: list[dict[str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "messages" in body:
            seen.append(
                {
                    "session": request.headers["x-agent-session-id"],
                    "user_message": body["messages"][1]["content"],
                    "user_field": body["user"],
                }
            )
        return inner.handle_request(request)

    return httpx.MockTransport(handle), seen


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def play(texts: list[str], cfg: models.Settings = CFG) -> tuple[Room, list[dict[str, str]]]:
    room = Room(subjects=SUBJECTS)
    transport, seen = recording(cfg)

    async def go() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            engine = Engine(room, cfg, client)
            for text in texts:
                engine.prepare(text)
            await engine.drain()

    asyncio.run(go())
    return room, seen


def test_every_subject_call_carries_the_case_and_the_hash_of_the_message_sent() -> None:
    room, seen = play(["Is 90% accuracy good?"])
    [prompt] = room.prompts
    sent = f"Is 90% accuracy good?\n\n{FRAME}"
    assert len(seen) == len(SUBJECTS)
    for call in seen:
        assert call["user_message"] == sent
        assert call["session"] == f"case:{prompt['id']}:{sha(sent)}"
        assert call["user_field"] == "housecast-room"
    assert prompt["input_sha256"] == sha(sent)
    assert len(seen[0]["session"]) == len("case:") + 8 + 1 + 64


def test_each_case_gets_its_own_value_and_the_hash_follows_the_frame() -> None:
    room, seen = play(["one", "two"])
    values = {call["user_message"]: call["session"] for call in seen}
    assert len(values) == 2 and len(set(values.values())) == 2
    bare = models.Settings(proxy="http://proxy", model="route", jev_model="jev", frame="")
    room, seen = play(["one"], bare)
    assert seen[0]["user_message"] == "one"
    assert seen[0]["session"].endswith(sha("one"))
    assert room.prompts[0]["input_sha256"] == sha("one")


def test_a_run_again_sends_the_same_value_as_the_first_run() -> None:
    room = Room(subjects=SUBJECTS)
    transport, seen = recording()

    async def go() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            engine = Engine(room, CFG, client)
            case = engine.prepare("a case")
            await engine.drain()
            engine.rerun(case["id"])
            await engine.drain()

    asyncio.run(go())
    assert len(seen) == 2 * len(SUBJECTS) and len({c["session"] for c in seen}) == 1


def test_the_hash_reaches_a_reader_with_the_text_and_not_before() -> None:
    room, _ = play(["hidden until picked"])
    [prompt] = room.prompts

    def shown(view: str) -> dict[str, Any]:
        row: dict[str, Any] = room.snapshot(view)["prompts"][0]
        return row

    assert shown("presenter")["input_sha256"] == prompt["input_sha256"]
    for view in ("attendee", "screen"):
        assert "text" not in shown(view) and "input_sha256" not in shown(view)
    Engine(room, CFG, httpx.AsyncClient()).pick(prompt["id"])
    for view in ("attendee", "screen"):
        on_screen = shown(view)
        assert sha(f"{on_screen['text']}\n\n{FRAME}") == on_screen["input_sha256"]
