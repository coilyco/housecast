"""Per-subject models and the whole-round fallback. Default off is pinned first."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from housecast.room import models
from housecast.room.cli import room as room_cli
from housecast.room.engine import Engine
from housecast.room.server import create_app
from housecast.room.store import Room
from housecast.room.subjects import SubjectsError, load_subjects
from housecast.room.tests.test_room import CFG, SUBJECTS


@pytest.fixture(autouse=True)
def no_retry_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("housecast.room.engine.RETRY_PAUSE", 0.0)


Reply = str | int  # text, or a status to fail with
Calls = list[tuple[str, str]]  # (model, system) in arrival order


def routed(replies: Callable[[str, str], Reply]) -> tuple[httpx.MockTransport, Calls]:
    calls: Calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/v1/systemone":
            return httpx.Response(200, json={"answers": {"divergence": {"score": 2.0}}})
        system = body["messages"][0]["content"]
        calls.append((body["model"], system))
        reply = replies(body["model"], system)
        if isinstance(reply, int):
            return httpx.Response(reply)
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    return httpx.MockTransport(handle), calls


async def ask(room: Room, transport: httpx.MockTransport, cfg: models.Settings = CFG) -> None:
    async with httpx.AsyncClient(transport=transport) as client:
        engine = Engine(room, cfg, client)
        if room.phase != "submissions":
            engine.set_phase("submissions")
        engine.submit("do you like purple?")
        await engine.drain()


def fallback(name: str) -> models.Settings:
    return models.Settings(
        proxy="http://proxy", model="route", jev_model="jev", fallback_model=name
    )


def with_models(**by_id: str) -> list[dict[str, str]]:
    return [{**s, **({"model": by_id[s["id"]]} if s["id"] in by_id else {})} for s in SUBJECTS]


def test_default_path_calls_the_room_model_for_every_subject_and_logs_no_new_kind(
    tmp_path: Path,
) -> None:
    transport, calls = routed(lambda _m, system: system)
    room = Room(subjects=SUBJECTS, log_path=tmp_path / "room.jsonl")
    asyncio.run(ask(room, transport))
    assert sorted(calls) == sorted(("route", s["system"]) for s in SUBJECTS)
    kinds = {
        json.loads(line)["kind"]
        for line in (tmp_path / "room.jsonl").read_text().split("\n")
        if line
    }
    assert kinds == {"phase", "prompt", "divergence", "answer"}
    assert room.fallbacks == {}


def test_a_failed_answer_stays_failed_with_no_fallback_configured() -> None:
    transport, calls = routed(lambda _m, system: 500 if system == "you are two" else "ok")
    room = Room(subjects=SUBJECTS)
    asyncio.run(ask(room, transport))
    assert len(calls) == 4 + 1  # s2 retried once on the 500, then failed
    assert sorted(a["state"] for a in room.snapshot()["answers"]) == [
        "done",
        "done",
        "done",
        "failed",
    ]


def test_a_mixed_run_sends_each_subject_to_its_own_model_and_hides_it(tmp_path: Path) -> None:
    subjects = with_models(s1="mistral-medium", s3="qwen-max")
    transport, calls = routed(lambda _m, system: system)
    room = Room(subjects=subjects, log_path=tmp_path / "room.jsonl")
    asyncio.run(ask(room, transport))
    assert dict((system, model) for model, system in calls) == {
        "you are one": "mistral-medium",
        "you are two": "route",
        "you are three": "qwen-max",
        "you are four": "route",
    }
    for view in ("attendee", "screen", "presenter"):
        assert all(set(s) == {"id", "label"} for s in room.snapshot(view)["subjects"])
    assert "mistral" not in json.dumps(room.snapshot("presenter"))


def test_a_failure_moves_the_whole_round_to_the_fallback_together(tmp_path: Path) -> None:
    subjects = with_models(s1="mistral-medium", s2="kimi")

    def replies(model: str, system: str) -> Reply:
        return 500 if model == "kimi" else f"{model}:{system}"

    transport, calls = routed(replies)
    log = tmp_path / "room.jsonl"
    room = Room(subjects=subjects, log_path=log)
    cfg = fallback("qwen")
    asyncio.run(ask(room, transport, cfg))
    on_fallback = [system for model, system in calls if model == "qwen"]
    assert sorted(on_fallback) == sorted(s["system"] for s in SUBJECTS)  # all four, not one alone
    answers = {a["subject_id"]: a for a in room.snapshot("presenter")["answers"]}
    assert {a["state"] for a in answers.values()} == {"done"}
    assert answers["s1"]["text"] == "qwen:you are one"
    [switch] = [e for e in map(json.loads, log.read_text().splitlines()) if e["kind"] == "fallback"]
    assert switch["data"] == {"prompt_id": room.prompts[0]["id"], "model": "qwen", "failed": ["s2"]}
    assert room.snapshot()["divergence"][0]["state"] == "done"


def test_a_failing_fallback_does_not_switch_again() -> None:
    transport, calls = routed(lambda _m, _s: 500)
    room = Room(subjects=SUBJECTS[:2])
    cfg = fallback("qwen")
    asyncio.run(ask(room, transport, cfg))
    assert [m for m, _ in calls].count("qwen") == 4  # two subjects, one retry each
    assert {a["state"] for a in room.snapshot()["answers"]} == {"failed"}
    assert len(room.fallbacks) == 1


def test_no_switch_once_the_prompt_is_picked() -> None:
    transport, calls = routed(lambda _m, system: 500 if system == "you are two" else "ok")
    room = Room(subjects=SUBJECTS[:2])
    cfg = fallback("qwen")

    async def go() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            engine = Engine(room, cfg, client)
            engine.set_phase("submissions")
            prompt = engine.submit("hi")
            engine.pick(prompt["id"])
            await engine.drain()

    asyncio.run(go())
    assert room.fallbacks == {} and all(m == "route" for m, _ in calls)


def test_replay_of_a_log_with_a_switch_matches_and_resumes_on_the_logged_model(
    tmp_path: Path,
) -> None:
    log = tmp_path / "room.jsonl"
    room = Room(subjects=SUBJECTS[:2], log_path=log)
    room.emit("prompt", {"id": "p1", "seq": 1, "text": "hi", "at": "t"})
    room.emit("divergence", {"prompt_id": "p1", "state": "pending"})
    room.emit("answer", {"prompt_id": "p1", "subject_id": "s1", "state": "done", "text": "primary"})
    room.emit("answer", {"prompt_id": "p1", "subject_id": "s2", "state": "failed"})
    # The crash lands right after the switch is logged, before any re-queue event.
    room.emit("fallback", {"prompt_id": "p1", "model": "qwen", "failed": ["s2"]})
    restarted = Room(subjects=SUBJECTS[:2], log_path=log)
    restarted.load()
    assert restarted.fallbacks == room.fallbacks
    assert {a["state"] for a in restarted.answers.values()} == {"queued"}  # not a mixed round
    assert restarted.snapshot() == room.snapshot()

    transport, calls = routed(lambda model, system: f"{model}:{system}")
    # The restart's own config names another fallback, and must not change the logged one.
    cfg = fallback("other")

    async def resume() -> int:
        async with httpx.AsyncClient(transport=transport) as client:
            engine = Engine(restarted, cfg, client)
            count = engine.resume()
            await engine.drain()
            return count

    assert asyncio.run(resume()) == 2
    assert sorted(m for m, _ in calls) == ["qwen", "qwen"]
    assert len(restarted.fallbacks) == 1  # replayed once, never re-switched
    assert {a["state"] for a in restarted.answers.values()} == {"done"}
    assert restarted.divergence["p1"]["state"] == "done"
    again = Room(subjects=SUBJECTS[:2], log_path=log)
    again.load()
    assert again.snapshot() == restarted.snapshot()


def test_a_restart_after_every_answer_failed_but_before_the_switch_still_switches_once(
    tmp_path: Path,
) -> None:
    log = tmp_path / "room.jsonl"
    room = Room(subjects=SUBJECTS[:2], log_path=log)
    room.emit("prompt", {"id": "p1", "seq": 1, "text": "hi", "at": "t"})
    room.emit("divergence", {"prompt_id": "p1", "state": "pending"})
    for s in SUBJECTS[:2]:
        room.emit("answer", {"prompt_id": "p1", "subject_id": s["id"], "state": "failed"})
    restarted = Room(subjects=SUBJECTS[:2], log_path=log)
    restarted.load()
    transport, calls = routed(lambda model, system: system)
    cfg = fallback("qwen")

    async def resume() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            engine = Engine(restarted, cfg, client)
            engine.resume()
            await engine.drain()

    asyncio.run(resume())
    assert [m for m, _ in calls] == ["qwen", "qwen"] and len(restarted.fallbacks) == 1


def test_event_stream_views_learn_that_a_switch_happened_never_to_what() -> None:
    room = Room(subjects=SUBJECTS)
    event = {"rev": 1, "at": "t", "kind": "fallback", "data": {"prompt_id": "p1", "model": "qwen"}}
    for view in ("attendee", "screen", "presenter"):
        assert room.project(event, view)["data"] == {"prompt_id": "p1"}


@pytest.mark.parametrize("name", ["claude-opus", "Anthropic/x", "evaluation/CLAUDE-4"])
def test_an_anthropic_name_is_refused_at_load(tmp_path: Path, name: str) -> None:
    path = tmp_path / "subjects.json"
    path.write_text(json.dumps([{"id": "a", "label": "A", "system": "x", "model": name}]))
    with pytest.raises(SubjectsError, match="Anthropic"):
        load_subjects(path)
    with pytest.raises(models.ModelRefusedError, match="Anthropic"):
        models.Settings(proxy="p", model="m", jev_model="j", fallback_model=name)


def test_subjects_take_an_optional_model_and_refuse_a_blank_one(tmp_path: Path) -> None:
    path = tmp_path / "subjects.json"
    path.write_text(
        json.dumps(
            {
                "subjects": [
                    {"id": "a", "label": "A", "system": "x", "model": " evaluation/kimi "},
                    {"id": "b", "label": "B", "system": "y"},
                ]
            }
        )
    )
    a, b = load_subjects(path)
    assert a["model"] == "evaluation/kimi" and "model" not in b
    path.write_text(json.dumps([{"id": "a", "label": "A", "system": "x", "model": ""}]))
    with pytest.raises(SubjectsError, match="not a name"):
        load_subjects(path)


def test_cli_refuses_an_anthropic_fallback_before_serving(tmp_path: Path) -> None:
    subjects = tmp_path / "subjects.json"
    subjects.write_text(json.dumps([{"id": "a", "label": "A", "system": "x"}]))
    result = CliRunner().invoke(
        room_cli,
        [
            "serve",
            "--subjects",
            str(subjects),
            "--log",
            str(tmp_path / "log"),
            "--fallback-model",
            "claude-sonnet",
        ],
    )
    assert result.exit_code != 0 and "Anthropic" in result.output


def test_the_snapshot_over_http_never_carries_a_model() -> None:
    subjects = with_models(s1="mistral-medium")
    room = Room(subjects=subjects)
    transport, _ = routed(lambda _m, system: system)
    app = create_app(room, CFG, "tok", client=httpx.AsyncClient(transport=transport), page=None)
    with TestClient(app) as tc:
        body = tc.get("/api/room").text
        body += tc.get("/api/control/room", headers={"X-Control-Token": "tok"}).text
    assert "mistral" not in body and "model" not in body
