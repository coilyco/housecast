"""A real room server on a loopback port with a stub model route, for concurrent tests.

TestClient serializes requests, so it cannot show what concurrent attendees do to
the room. This runs uvicorn in a thread. A restart is a new `Served` on the same
port and log.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from housecast.room.models import Settings
from housecast.room.server import create_app
from housecast.room.store import Room
from housecast.room.tests.test_room import SUBJECTS

CFG = Settings(proxy="http://proxy", model="route", jev_model="jev")
TOKEN = "room-test-token"


def stub(delay: float = 0.0, fail: str | None = None) -> httpx.MockTransport:
    """A model route that answers every subject, optionally slowly, or 429s one system prompt."""

    async def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/v1/systemone":
            return httpx.Response(200, json={"answers": {"divergence": {"score": 2.0}}})
        system = body["messages"][0]["content"]
        await asyncio.sleep(delay)
        if system == fail:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": f"re: {system}"}}]})

    return httpx.MockTransport(handle)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Served:
    def __init__(self, log: Path, port: int, transport: httpx.MockTransport) -> None:
        room = Room(subjects=SUBJECTS, log_path=log)
        room.load()
        app = create_app(
            room,
            CFG,
            TOKEN,
            rate_seconds=0.2,
            client=httpx.AsyncClient(transport=transport),
            page=None,
        )
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1
        )
        self.server = uvicorn.Server(config)
        self.port = port
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> Served:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            assert time.monotonic() < deadline, "the room server did not start"
            time.sleep(0.02)
        return self

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"
