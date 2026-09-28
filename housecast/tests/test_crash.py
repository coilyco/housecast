"""Crash reporting: crashes only, fully annotated, graded content scrubbed (deploy#8347)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sentry_sdk = pytest.importorskip("sentry_sdk")
pytest.importorskip("fastapi")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sentry_sdk.transport import Transport  # noqa: E402

import housecast.crash as crash  # noqa: E402


class _Capture(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Any) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Capture]:
    transport = _Capture()
    real_init = sentry_sdk.init
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: real_init(transport=transport, **kw))
    monkeypatch.setattr(crash, "_initialized", False)
    monkeypatch.setattr(crash, "_window", [])
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    assert crash.init_crash_reporting() is True
    yield transport
    real_init()


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/grade")
    async def grade(request: dict[str, str]) -> None:
        board_id = request["board"]  # noqa: F841
        critique = request["critique"]  # noqa: F841
        logging.getLogger("housecast.test").warning("grading board")
        raise RuntimeError("grader crashed")

    @app.get("/handled")
    async def handled() -> dict[str, bool]:
        logging.getLogger("housecast.test").error("upstream model timed out, retrying")
        return {"ok": True}

    @app.get("/refused")
    async def refused() -> None:
        raise HTTPException(status_code=503, detail="deliberate")

    return app


def _leaks(events: list[dict[str, Any]], secret: str) -> list[str]:
    found = []
    for event in events:
        for value in event.get("exception", {}).get("values", []):
            for frame in value.get("stacktrace", {}).get("frames", []):
                for name, var in (frame.get("vars") or {}).items():
                    if secret in json.dumps(var):
                        found.append(f"{frame.get('module')}:{name}")
        if secret in json.dumps(event.get("request", {})):
            found.append("request")
    return found


def test_a_crash_is_annotated_and_carries_no_graded_content(captured: _Capture) -> None:
    secret = "-".join(["GRADER", "SECRET"])
    client = TestClient(_app(), raise_server_exceptions=False)
    body = {"board": "board-7", "critique": secret}
    assert client.post("/grade", json=body).status_code == 500
    sentry_sdk.flush()
    (event,) = captured.events
    assert event["exception"]["values"][-1]["value"] == "grader crashed"
    frame_vars = event["exception"]["values"][-1]["stacktrace"]["frames"][-1]["vars"]
    assert "board-7" in frame_vars["board_id"]
    assert "grading board" in [c.get("message") for c in event["breadcrumbs"]["values"]]
    assert event["request"]["method"] == "POST"
    assert _leaks(captured.events, secret) == []
    assert secret not in json.dumps(captured.events)


def test_handled_errors_and_deliberate_5xx_send_nothing(captured: _Capture) -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    assert client.get("/handled").status_code == 200
    assert client.get("/refused").status_code == 503
    sentry_sdk.flush()
    assert captured.events == []


def test_importing_the_library_never_starts_sentry() -> None:
    env = {**os.environ, "SENTRY_DSN": "https://public@example.invalid/1"}
    code = (
        "import housecast, housecast.grade, housecast.room, sentry_sdk;"
        "print(sentry_sdk.get_client().is_active())"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_no_dsn_leaves_it_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(crash, "_initialized", False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("HOUSECAST_SENTRY_DSN_FILE", str(tmp_path / "absent"))
    assert crash.init_crash_reporting() is False


def test_a_converged_dsn_file_is_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dsn_file = tmp_path / "sentry-dsn"
    dsn_file.write_text("https://public@example.invalid/2\n", encoding="utf-8")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("HOUSECAST_SENTRY_DSN_FILE", str(dsn_file))
    assert crash._dsn() == "https://public@example.invalid/2"


def test_budget_caps_events_per_process_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crash, "_window", [])
    allowed = [crash._within_budget(100.0) for _ in range(crash.EVENTS_PER_MINUTE + 1)]
    assert allowed.count(True) == crash.EVENTS_PER_MINUTE
    assert crash._within_budget(161.0) is True


def test_init_failure_logs_the_class_and_never_the_dsn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def refuse(**_kw: Any) -> None:
        raise ValueError("https://secret-key@o0.ingest.example/1")

    monkeypatch.setattr(crash, "_initialized", False)
    monkeypatch.setattr(sentry_sdk, "init", refuse)
    monkeypatch.setenv("SENTRY_DSN", "https://secret-key@o0.ingest.example/1")
    with caplog.at_level(logging.WARNING, logger="housecast.crash"):
        assert crash.init_crash_reporting() is False
    assert "ValueError" in caplog.text
    assert "secret-key" not in caplog.text
