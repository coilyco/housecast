"""The room preflight against bare local HTTP servers standing in for the two origins."""

from __future__ import annotations

import importlib.util
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from housecast.room.tests.serving import free_port

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "room_preflight.py"
SNAPSHOT = '{"rev": 41, "phase": "answering"}'
LOGIN = "https://accounts.example/login?state=opaque-state-value&client_id=abc"

PUBLIC = {
    "/": (200, ""),
    "/screen": (200, ""),
    "/api/room": (200, SNAPSHOT),
    "/present": (403, ""),
}
GATED = {"/present": (302, LOGIN)}


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("room_preflight", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def origin(routes: dict[str, tuple[int, str]], seen: list[Any]) -> Iterator[str]:
    """Serves (status, body) per path, or a Location when the status is 3xx. Records requests."""

    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            seen.append((self.command, self.path, {k.lower() for k in self.headers}))
            status, body = routes.get(self.path, (404, ""))
            self.send_response(status)
            if 300 <= status < 400:
                self.send_header("Location", body)
                body = ""
            self.end_headers()
            self.wfile.write(body.encode())

        do_GET = do_POST = do_PUT = do_DELETE = _answer  # noqa: N815

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def preflight(
    public: dict[str, tuple[int, str]], gated: dict[str, tuple[int, str]]
) -> tuple[bool, list[str], list[Any]]:
    seen: list[Any] = []
    lines: list[str] = []
    with origin(public, seen) as pub, origin(gated, seen) as gate:
        ok = _load().run(pub, gate, 5, emit=lines.append)
    return ok, lines, seen


def test_a_healthy_edge_passes_every_line_and_prints_rev_and_phase() -> None:
    ok, lines, _ = preflight(PUBLIC, GATED)
    assert ok
    assert [line.split(":")[0] for line in lines] == [
        "PASS public /",
        "PASS public /screen",
        "PASS public /api/room",
        "PASS public /present",
        "PASS gated /present",
    ]
    assert "rev 41 phase answering" in lines[2]


def test_the_login_redirect_is_named_without_its_query() -> None:
    _, lines, _ = preflight(PUBLIC, GATED)
    assert lines[4].endswith("status 302 to accounts.example/login")
    assert "opaque-state-value" not in "".join(lines) and "client_id" not in "".join(lines)


@pytest.mark.parametrize(
    ("path", "reply", "line"),
    [
        ("/", (502, ""), "FAIL public /: status 502, wanted 200"),
        ("/screen", (404, ""), "FAIL public /screen: status 404, wanted 200"),
        ("/api/room", (200, "<html>Sign in</html>"), "FAIL public /api/room: status 200 but"),
        ("/api/room", (200, '{"hello": 1}'), "FAIL public /api/room: status 200 but"),
        ("/api/room", (500, ""), "FAIL public /api/room: status 500, wanted 200"),
        ("/present", (200, ""), "FAIL public /present: status 200, wanted 403"),
    ],
)
def test_each_public_check_fails_on_its_own_wrong_answer(
    path: str, reply: tuple[int, str], line: str
) -> None:
    ok, lines, _ = preflight({**PUBLIC, path: reply}, GATED)
    assert not ok
    assert sum(entry.startswith("FAIL") for entry in lines) == 1
    assert any(entry.startswith(line) for entry in lines)


@pytest.mark.parametrize("reply", [(200, ""), (403, ""), (302, "")])
def test_the_gated_host_must_redirect_to_a_login_page(reply: tuple[int, str]) -> None:
    ok, lines, _ = preflight(PUBLIC, {"/present": reply})
    assert not ok
    assert lines[4].startswith("FAIL gated /present: status")
    assert lines[:4] == [line for line in lines[:4] if line.startswith("PASS")]


def test_a_redirect_on_the_public_origin_is_a_failure_and_is_not_followed() -> None:
    ok, lines, seen = preflight({**PUBLIC, "/": (302, "/elsewhere")}, GATED)
    assert not ok and lines[0].startswith("FAIL public /: status 302, wanted 200")
    assert "/elsewhere" not in [path for _, path, _ in seen]


def test_an_origin_that_is_down_fails_its_lines_and_the_rest_still_run() -> None:
    watcher = _load()
    lines: list[str] = []
    seen: list[Any] = []
    with origin(GATED, seen) as gate:
        ok = watcher.run(f"http://127.0.0.1:{free_port()}", gate, 2, emit=lines.append)
    assert not ok
    assert [line.split(" ")[0] for line in lines] == ["FAIL"] * 4 + ["PASS"]


def test_it_sends_only_bare_gets_of_the_five_paths() -> None:
    _, _, seen = preflight(PUBLIC, GATED)
    assert {method for method, _, _ in seen} == {"GET"}
    assert sorted(path for _, path, _ in seen) == [
        "/",
        "/api/room",
        "/present",
        "/present",
        "/screen",
    ]
    sent = set().union(*(headers for _, _, headers in seen))
    assert not sent & {"authorization", "cookie", "x-control-token", "content-length"}


@pytest.mark.parametrize(
    "argv",
    [
        ["--public", "room.example", "--gated", "https://room.example.dev"],
        ["--public", "https://room.example/present", "--gated", "https://room.example.dev"],
        ["--public", "https://room.example", "--gated", "ftp://room.example.dev"],
        ["--public", "https://room.example"],
        [
            "--public",
            "https://room.example",
            "--gated",
            "https://room.example.dev",
            "--timeout",
            "0",
        ],
    ],
)
def test_an_argument_that_is_not_an_origin_is_refused(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as refused:
        _load().main(argv)
    assert refused.value.code == 2


def test_the_exit_code_follows_the_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[Any] = []
    with origin(PUBLIC, seen) as pub, origin(GATED, seen) as gate:
        assert _load().main(["--public", pub, "--gated", gate]) == 0
    with origin({**PUBLIC, "/": (500, "")}, seen) as pub, origin(GATED, seen) as gate:
        assert _load().main(["--public", pub, "--gated", gate]) == 1
    assert "FAIL public /: status 500, wanted 200" in capsys.readouterr().out
