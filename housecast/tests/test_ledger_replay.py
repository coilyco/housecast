"""The ledger replay runner sends only on request, counts every outcome, and leaks no body."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ledger_replay.py"
SECRET = "body-text-that-must-not-be-printed"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("ledger_replay", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Intake:
    """A stub of the intake: 202 first sight, 200 repeat, 422 for a marked body."""

    def __init__(self, throttle: int = 0) -> None:
        self.posts: list[str] = []
        self.seen: set[str] = set()
        self.throttle = throttle
        self.health = 200


def _serve(intake: Intake) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _reply(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def do_GET(self) -> None:
            self._reply(intake.health)

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if intake.throttle > 0:
                intake.throttle -= 1
                return self._reply(429)
            intake.posts.append(body["event_id"])
            if body.get("marked"):
                return self._reply(422)
            if body["event_id"] in intake.seen:
                return self._reply(200)
            intake.seen.add(body["event_id"])
            return self._reply(202)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def intake() -> Iterator[tuple[Intake, str]]:
    state = Intake()
    server = _serve(state)
    yield state, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _ledger(tmp_path: Path, marked: tuple[str, ...] = ()) -> Path:
    path = tmp_path / "ledger.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        "CREATE TABLE events (sequence INTEGER PRIMARY KEY, event_id TEXT, envelope BLOB)"
    )
    for number in range(1, 6):
        event_id = f"e{number}"
        body = {"event_id": event_id, "text": SECRET, "marked": event_id in marked}
        # The real ledger column is a BLOB, so the fixture must store bytes too.
        connection.execute(
            "INSERT INTO events VALUES (?, ?, ?)", (number, event_id, json.dumps(body).encode())
        )
    connection.commit()
    connection.close()
    return path


def _run(path: Path, url: str, *extra: str) -> tuple[int, dict[str, Any]]:
    out = path.parent / "summary.json"
    code = _load().main(
        ["--source", str(path), "--url", url, "--out", str(out), "--backoff", "0", *extra]
    )
    return code, json.loads(out.read_text())


def test_a_dry_run_sends_nothing(intake: tuple[Intake, str], tmp_path: Path) -> None:
    state, url = intake
    code, summary = _run(_ledger(tmp_path), url)
    assert code == 0
    assert state.posts == []
    assert summary["mode"] == "dry-run"
    assert summary["attempted"] == 5


def test_apply_then_apply_again_is_accepted_then_duplicate(
    intake: tuple[Intake, str], tmp_path: Path
) -> None:
    state, url = intake
    path = _ledger(tmp_path)
    first_code, first = _run(path, url, "--apply")
    second_code, second = _run(path, url, "--apply")
    assert (first_code, second_code) == (0, 0)
    assert first["counts"] == {"accepted": 5, "duplicate": 0, "quarantined": 0, "error": 0}
    assert second["counts"] == {"accepted": 0, "duplicate": 5, "quarantined": 0, "error": 0}
    assert len(state.seen) == 5


def test_a_quarantined_event_fails_the_run_and_is_named(
    intake: tuple[Intake, str], tmp_path: Path
) -> None:
    _, url = intake
    code, summary = _run(_ledger(tmp_path, marked=("e3",)), url, "--apply")
    assert code == 1
    assert summary["counts"]["quarantined"] == 1
    assert summary["problems"] == [{"event_id": "e3", "status": 422}]


def test_a_throttled_post_is_retried_and_counted(tmp_path: Path) -> None:
    state = Intake(throttle=2)
    server = _serve(state)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        code, summary = _run(_ledger(tmp_path), url, "--apply")
    finally:
        server.shutdown()
    assert code == 0
    assert summary["retried"] == 2
    assert summary["counts"]["accepted"] == 5


def test_an_unhealthy_target_gets_nothing(intake: tuple[Intake, str], tmp_path: Path) -> None:
    state, url = intake
    state.health = 503
    assert _load().main(["--source", str(_ledger(tmp_path)), "--url", url, "--apply"]) == 2
    assert state.posts == []


def test_limit_takes_the_first_events_by_sequence(
    intake: tuple[Intake, str], tmp_path: Path
) -> None:
    state, url = intake
    _run(_ledger(tmp_path), url, "--apply", "--limit", "2")
    assert state.posts == ["e1", "e2"]


def test_no_envelope_text_reaches_the_output(
    intake: tuple[Intake, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, url = intake
    code, _ = _run(_ledger(tmp_path, marked=("e2",)), url, "--apply")
    assert code == 1
    assert SECRET not in capsys.readouterr().out
    assert SECRET not in (tmp_path / "summary.json").read_text()


def test_the_printed_target_drops_credentials_and_query() -> None:
    shown = _load().bare_url("http://user:pw@host.example:8080/base/?token=abc#frag")
    assert shown == "http://host.example:8080/base"
