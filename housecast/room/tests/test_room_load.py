"""The load harness against a real room server on a loopback port, with a stub model."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from housecast.room.tests.serving import TOKEN, Served, free_port, stub

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "room_load_test.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("room_load_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "token"
    path.write_text(TOKEN + "\n")
    path.chmod(0o600)
    return path


def argv(served: Served, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--base", served.base,
        "--token-file", str(token_file(tmp_path)),
        "--out", str(tmp_path / "out"),
        "--round-gap", "0.4",
        "--writes",
        *extra,
    ]  # fmt: skip


def report(tmp_path: Path) -> dict[str, Any]:
    return dict(json.loads((tmp_path / "out" / "report.json").read_text()))


def test_thirty_clients_hold_three_rounds(tmp_path: Path) -> None:
    served = Served(tmp_path / "room.jsonl", free_port(), stub()).start()
    try:
        code = _load().main(argv(served, tmp_path))
    finally:
        served.stop()
    result = report(tmp_path)
    assert code == 0 and result["passed"], result["failures"]
    assert len(result["rounds"]) == 3
    for row in result["rounds"]:
        assert row["submissions"]["created"] == 30
        assert row["grades"]["sent"] == 30 and not row["grades"]["refused"]
        for swap in ("submissions", "grading", "split"):
            assert row["fanout_ms"][swap]["n"] == 30
        assert row["split"]["totals_match"]
        for subject in row["answers"]["per_subject"].values():
            assert subject["done"] == subject["answers"] == 30
    assert result["base"] == "127.0.0.1" and "token" not in json.dumps(result).lower()


def test_a_rate_limited_subject_is_measured_and_fails_the_run(tmp_path: Path) -> None:
    served = Served(tmp_path / "room.jsonl", free_port(), stub(fail="you are three")).start()
    try:
        code = _load().main(argv(served, tmp_path, "--rounds", "1", "--clients", "4"))
    finally:
        served.stop()
    result = report(tmp_path)
    amber = result["rounds"][0]["answers"]["per_subject"]["Amber"]
    assert code == 1 and not result["passed"]
    assert amber["done"] == 0 and amber["not_done"] == {"the model route answered 429": 4}
    assert any("Amber" in failure for failure in result["failures"])


def test_a_tolerated_failure_does_not_fail_the_run(tmp_path: Path) -> None:
    served = Served(tmp_path / "room.jsonl", free_port(), stub(fail="you are three")).start()
    try:
        code = _load().main(
            argv(served, tmp_path, "--rounds", "1", "--clients", "4", "--allow-failed-answers", "4")
        )
    finally:
        served.stop()
    assert code == 0


def test_a_restart_mid_answers_replays_and_the_round_finishes(tmp_path: Path) -> None:
    log = tmp_path / "room.jsonl"
    port = free_port()
    first = Served(log, port, stub(delay=1.5)).start()
    swapped: dict[str, Served] = {}

    def restart() -> None:
        checkpoint = tmp_path / "out" / "checkpoint.json"
        while not checkpoint.exists():
            time.sleep(0.05)
        first.stop()
        swapped["second"] = Served(log, port, stub()).start()
        (tmp_path / "out" / "RESUME").write_text("")

    mover = threading.Thread(target=restart, daemon=True)
    mover.start()
    try:
        pause = ("--pause-at", "answering", "--pause-round", "1")
        code = _load().main(argv(first, tmp_path, "--rounds", "1", "--clients", "4", *pause))
    finally:
        mover.join(30)
        first.stop()
        if "second" in swapped:
            swapped["second"].stop()
    result = report(tmp_path)
    assert code == 0, result["failures"]
    assert result["replay"]["cut_answers"] > 0
    assert all(result["replay"]["checks"].values())
    assert all(n >= 1 for n in result["replay"]["client_resyncs"])


def test_a_used_log_is_refused_before_any_grade_is_sent(tmp_path: Path) -> None:
    served = Served(tmp_path / "room.jsonl", free_port(), stub()).start()
    try:
        first = _load().main(argv(served, tmp_path, "--rounds", "1", "--clients", "2"))
        second = _load().main(argv(served, tmp_path, "--rounds", "1", "--clients", "2"))
    finally:
        served.stop()
    result = report(tmp_path)
    assert first == 0 and second == 1 and not result["rounds"]
    assert result["failures"] == ["the room already has 1 rounds. Start it on an empty log"]


def test_an_answer_of_only_markup_is_counted_as_empty(tmp_path: Path) -> None:
    served = Served(tmp_path / "room.jsonl", free_port(), stub(blank="you are three")).start()
    try:
        code = _load().main(
            argv(served, tmp_path, "--rounds", "1", "--clients", "4", "--allow-failed-answers", "4")
        )
    finally:
        served.stop()
    result = report(tmp_path)
    per = result["rounds"][0]["answers"]["per_subject"]
    assert code == 0 and per["Amber"]["empty"] == 4 and per["Amber"]["done"] == 0
    assert all(row["empty"] == 0 for name, row in per.items() if name != "Amber")
    assert "round 1: Amber gave 4 empty answers" in result["findings"]


def test_the_token_file_must_be_private(tmp_path: Path) -> None:
    module = _load()
    path = tmp_path / "token"
    path.write_text("x")
    path.chmod(0o644)
    with pytest.raises(SystemExit, match="readable by others"):
        module.load_token(path)
    path.chmod(0o600)
    assert module.load_token(path) == "x"


def test_it_refuses_to_write_without_the_flag(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as refused:
        _load().main(["--base", "http://127.0.0.1:1", "--out", str(tmp_path)])
    assert refused.value.code == 2


def test_spread_and_peak_concurrency() -> None:
    module = _load()
    assert module.spread([]) == {"n": 0, "p50": None, "p95": None, "max": None}
    assert module.spread([1.0, 2.0, 3.0])["p50"] == 2.0
    stamps = [
        {"started_at": "2026-09-29T00:00:00.000Z", "finished_at": "2026-09-29T00:00:02.000Z"},
        {"started_at": "2026-09-29T00:00:01.000Z", "finished_at": "2026-09-29T00:00:03.000Z"},
        {"started_at": "2026-09-29T00:00:04.000Z", "finished_at": "2026-09-29T00:00:05.000Z"},
    ]
    assert module.peak_concurrency(stamps) == 2


def test_the_event_stream_parser_reads_frames_and_skips_comments() -> None:
    module = _load()
    raw = b'event: hello\ndata: {"rev": 3}\n\n: keepalive\n\nevent: phase\ndata: {"a": 1}\n\n'

    async def read() -> list[tuple[str, str]]:
        reply = httpx.Response(200, content=raw)
        return [frame async for frame in module.sse_frames(reply)]

    assert asyncio.run(read()) == [("hello", '{"rev": 3}'), ("phase", '{"a": 1}')]


def test_thirty_clients_queue_behind_the_engine_cap(tmp_path: Path) -> None:
    """120 answers against 40 slots: the report must show the wait, not hide it."""
    served = Served(tmp_path / "room.jsonl", free_port(), stub(delay=0.3)).start()
    try:
        code = _load().main(argv(served, tmp_path, "--rounds", "1"))
    finally:
        served.stop()
    result = report(tmp_path)
    answers = result["rounds"][0]["answers"]
    assert code == 0, result["failures"]
    assert answers["peak_running"] <= 40
    waits = [s["queue_s"]["p95"] for s in answers["per_subject"].values()]
    assert max(waits) > 0.25, "120 answers through 40 slots should queue"


def test_a_fallback_is_counted_and_cannot_hide_a_failed_primary(tmp_path: Path) -> None:
    """The fallback turns failed answers into done ones, so the run must say it fired."""
    log, port = tmp_path / "room.jsonl", free_port()
    served = Served(log, port, stub(fail_model="route"), fallback="fallback-route").start()
    try:
        code = _load().main(argv(served, tmp_path, "--rounds", "1", "--clients", "4"))
    finally:
        served.stop()
    result = report(tmp_path)
    assert code == 0, result["failures"]
    assert result["rounds"][0]["fallbacks"] == 4
    assert any("fallback model" in finding for finding in result["findings"])
    for subject in result["rounds"][0]["answers"]["per_subject"].values():
        assert subject["done"] == subject["answers"] == 4
