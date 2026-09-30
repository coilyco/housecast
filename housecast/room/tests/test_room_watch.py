"""The room watcher against a real room with a stub model, and a bare HTTP server."""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from housecast.room.tests.serving import TOKEN, Served, free_port, stub

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "room_watch.py"
TERMINAL = {"done", "empty", "failed"}


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("room_watch", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def submit(base: str, text: str, device: str) -> None:
    headers = {"x-control-token": TOKEN}
    with httpx.Client(base_url=base, timeout=10, headers=headers) as ctl:
        ctl.post("api/control/phase", json={"phase": "submissions"})
        assert ctl.post("api/prompts", json={"text": text, "device": device}).status_code == 201


def settled(base: str) -> None:
    """Wait until every answer is terminal and every prompt has its divergence."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        snap = httpx.get(f"{base}/api/room", timeout=5).json()
        answers = snap["answers"]
        scored = {d["prompt_id"] for d in snap["divergence"] if d["state"] in {"done", "failed"}}
        if (
            answers
            and all(a["state"] in TERMINAL for a in answers)
            and len(scored) == len(snap["prompts"])
        ):
            return
        time.sleep(0.05)
    raise AssertionError("the room did not settle")


def jev_down(inner: httpx.MockTransport) -> httpx.MockTransport:
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/systemone":
            return httpx.Response(500)
        return await inner.handle_async_request(request)

    return httpx.MockTransport(handle)


@contextmanager
def room(tmp_path: Path, transport: httpx.MockTransport) -> Iterator[Served]:
    served = Served(tmp_path / "room.jsonl", free_port(), transport).start()
    try:
        yield served
    finally:
        served.stop()


def jev_says(replied: dict[str, float | None], inner: httpx.MockTransport) -> httpx.MockTransport:
    """Jev's reply check per answer text: a probability, or None for a 500."""

    async def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/v1/systemone" and "replied" in body["questions"]:
            p = replied[body["state"]["answer"]]
            if p is None:
                return httpx.Response(500)
            return httpx.Response(200, json={"answers": {"replied": {"noul": p}}})
        return await inner.handle_async_request(request)

    return httpx.MockTransport(handle)


def checked(base: str) -> None:
    """Wait until every settled answer carries its Jev verdict, null included."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        answers = httpx.get(f"{base}/api/room", timeout=5).json()["answers"]
        if answers and all("jev" in a for a in answers if a["state"] == "done"):
            return
        time.sleep(0.05)
    raise AssertionError("Jev's checks did not land")


def summary_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "no-answer:" in line]


def test_a_failed_subject_is_counted_and_a_fresh_failure_is_marked(tmp_path: Path) -> None:
    watcher = _load()
    with room(tmp_path, stub(fail="you are three")) as served:
        submit(served.base, "first", "d1")
        settled(served.base)
        lines: list[str] = []

        def second_prompt(_: float) -> None:
            submit(served.base, "second", "d2")
            settled(served.base)

        watcher.watch(served.base, 0, 60, 5, 2, emit=lines.append, sleep=second_prompt)
    first, second = summary_lines(lines)
    assert "Amber 1," in first and "Violet 0" in first and "Teal 0" in first and "Rose 0" in first
    assert "(+" not in first
    assert "Amber 2 (+1)" in second and "Violet 0," in second
    assert "jev-fallback*: 0" in first


def test_answers_running_past_the_limit_are_listed(tmp_path: Path) -> None:
    watcher = _load()
    with room(tmp_path, stub(delay=4)) as served:
        submit(served.base, "slow one", "d1")
        time.sleep(0.8)
        lines: list[str] = []
        watcher.watch(served.base, 0, 0.3, 5, 1, emit=lines.append, sleep=lambda _: None)
    (line,) = summary_lines(lines)
    assert "slow>0.3s: 4" in line
    listed = [entry for entry in lines if "  slow: " in entry]
    assert len(listed) == 4 and all(" running " in entry for entry in listed)
    assert {entry.split("slow: ")[1].split(" on ")[0] for entry in listed} == {
        "Violet",
        "Teal",
        "Amber",
        "Rose",
    }


def test_a_round_scored_without_jev_is_marked_as_a_fallback(tmp_path: Path) -> None:
    watcher = _load()
    with room(tmp_path, jev_down(stub())) as served:
        submit(served.base, "no jev today", "d1")
        settled(served.base)
        lines: list[str] = []
        watcher.watch(served.base, 0, 60, 5, 1, emit=lines.append, sleep=lambda _: None)
        snap = httpx.get(f"{served.base}/api/room", timeout=5).json()
    (line,) = summary_lines(lines)
    assert "jev-fallback*: 1" in line
    assert [d["method"] for d in snap["divergence"]] == ["lexical"], "the room did not fall back"


def report_of(
    rev: int, prompts: int, no_answer: int = 0, no_reply: int = 0, model: str | None = None
) -> dict[str, Any]:
    return {
        "rev": rev,
        "phase": "answering",
        "round": 1,
        "prompts": prompts,
        "labels": {"s1": "Violet"},
        "models": {"s1": model},
        "no_answer": {"s1": no_answer},
        "no_reply": {"s1": no_reply},
        "slow": [],
        "fallbacks": [],
    }


def test_a_reply_that_is_false_or_null_is_counted_per_subject(tmp_path: Path) -> None:
    watcher = _load()
    verdicts = {"re: you are one": 0.9, "re: you are two": 0.1, "re: you are four": None}
    with room(tmp_path, jev_says(verdicts, stub(fail="you are three"))) as served:
        submit(served.base, "who answers", "d1")
        settled(served.base)
        checked(served.base)
        lines: list[str] = []
        watcher.watch(served.base, 0, 60, 5, 1, emit=lines.append, sleep=lambda _: None)
    (line,) = summary_lines(lines)
    no_reply = line.split("no-reply: ")[1].split(" | ")[0]
    # Violet replied, Teal was judged not a reply, Rose has no verdict, Amber failed.
    assert no_reply == "Violet 0, Teal 1, Amber 0, Rose 1"
    assert "no-answer: Violet 0, Teal 0, Amber 1, Rose 0" in line


def test_the_header_names_each_model_and_says_again_when_one_is_swapped() -> None:
    watcher = _load()
    flash, glm = report_of(1, 0, model="Flash Lite"), report_of(2, 0, model="GLM")
    assert watcher.report(1000.0, flash, None, 60)[0].endswith("models: Violet on Flash Lite")
    assert not any("models:" in line for line in watcher.report(1015.0, flash, flash, 60))
    assert watcher.report(1030.0, glm, flash, 60)[0].endswith("models: Violet on GLM")
    assert watcher.report(1045.0, report_of(3, 0), None, 60)[0].endswith(
        "models: Violet on no model_label"
    )


def test_a_no_reply_count_that_grew_is_marked() -> None:
    watcher = _load()
    lines = watcher.report(1000.0, report_of(2, 1, no_reply=3), report_of(1, 1, no_reply=1), 60)
    assert "no-reply: Violet 3 (+2)" in lines[-1]


def test_a_round_scored_by_stance_without_a_confidence_is_not_a_fallback() -> None:
    watcher = _load()
    snapshot = {
        "rev": 5,
        "phase": "answering",
        "round": {"n": 1},
        "rounds": [{"n": 1, "prompt_id": "p1"}],
        "subjects": [{"id": "s1", "label": "Violet"}],
        "prompts": [{"id": "p1"}],
        "divergence": [
            {"prompt_id": "p1", "state": "done", "method": "stance", "confidence": None},
            {"prompt_id": "p2", "state": "done", "method": "lexical", "confidence": None},
        ],
    }
    assert watcher.summarize(snapshot, 1000.0, 60)["fallbacks"] == ["prompt p2"]


def test_a_rev_that_goes_backwards_warns_of_a_fresh_log() -> None:
    watcher = _load()
    lines = watcher.report(1000.0, report_of(2, 0), report_of(40, 5), 60)
    assert any("fresh log" in line for line in lines)
    assert not any(
        "fresh log" in line
        for line in watcher.report(1000.0, report_of(41, 5), report_of(40, 5), 60)
    )


@contextmanager
def bare_server(replies: list[tuple[int, str]]) -> Iterator[tuple[str, list[Any]]]:
    """Serves the given (status, body) in turn, then the last one forever, and records requests."""
    seen: list[Any] = []

    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            seen.append((self.command, self.path, {k.lower() for k in self.headers}))
            status, body = replies[min(len(seen) - 1, len(replies) - 1)]
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body.encode())

        do_GET = do_POST = do_PUT = do_DELETE = _answer  # noqa: N815

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", seen
    finally:
        server.shutdown()


SNAPSHOT = json.dumps(
    {"rev": 3, "phase": "submissions", "round": None, "subjects": [], "prompts": []}
)


def test_it_sends_bare_gets_of_api_room_and_nothing_else() -> None:
    watcher = _load()
    with bare_server([(200, SNAPSHOT)]) as (base, seen):
        watcher.watch(base, 0, 60, 5, 3, emit=lambda _: None, sleep=lambda _: None)
    assert [(method, path) for method, path, _ in seen] == [("GET", "/api/room")] * 3
    sent = set().union(*(headers for _, _, headers in seen))
    assert not sent & {"authorization", "cookie", "x-control-token", "content-length"}


def test_a_dead_room_is_reported_and_its_return_is_noticed() -> None:
    watcher = _load()
    with bare_server([(502, "bad gateway"), (502, ""), (200, SNAPSHOT)]) as (base, _):
        lines: list[str] = []
        watcher.watch(base, 0, 60, 5, 3, emit=lines.append, sleep=lambda _: None)
    assert lines[0].endswith("poll failed (1 in a row): HTTP 502")
    assert lines[1].endswith("poll failed (2 in a row): HTTP 502")
    assert "answers again after 2 failed polls" in lines[2]
    assert "rev 3" in lines[3] and not any("models:" in line for line in lines)


def test_a_sign_in_page_in_front_of_the_room_is_named() -> None:
    watcher = _load()
    with bare_server([(200, "<html>Sign in</html>")]) as (base, _):
        lines: list[str] = []
        watcher.watch(base, 0, 60, 5, 1, emit=lines.append, sleep=lambda _: None)
    assert "sign-in page" in lines[0]


@pytest.mark.parametrize(
    "base",
    ["ftp://room.example", "room.example", "https://room.example/present", "https://"],
)
def test_a_base_that_is_not_an_origin_is_refused(base: str) -> None:
    with pytest.raises(SystemExit) as refused:
        _load().main(["--base", base, "--iterations", "1"])
    assert refused.value.code == 2


def test_the_loop_stops_on_ctrl_c(monkeypatch: pytest.MonkeyPatch) -> None:
    watcher = _load()

    def interrupted(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(watcher, "watch", interrupted)
    assert watcher.main(["--base", "https://room.example"]) == 0
