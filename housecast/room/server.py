"""The room's HTTP surface: one snapshot, one event stream, intake, and control.

The event stream carries the same shapes as the snapshot, each with the `rev`
it produced, so a page that sees a gap re-reads the snapshot instead of
guessing. Refusals answer `{reason}` for the form to show verbatim.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from housecast.room.engine import Engine, PromptRefusedError
from housecast.room.models import Settings
from housecast.room.store import Room

DEFAULT_PORT = 8767
PAGE = Path(__file__).parent / "page"
KIT = Path(__file__).parent.parent / "grade" / "present_page" / "kit.css"
HEARTBEAT = 15.0
GRACEFUL_SHUTDOWN = 5


class Intake(BaseModel):
    text: str = ""
    device: str = ""


class GradeSheet(BaseModel):
    round: int
    device: str = ""
    grades: dict[str, str]
    reasons: dict[str, str] = {}


class PhaseChange(BaseModel):
    phase: str


class Pick(BaseModel):
    prompt_id: str


class RateLimit:
    """One prompt per device per window, and at most `burst` per address per window.

    The device token is the browser's own claim, so the address ceiling is what a
    script rotating tokens runs into. A room, not a fortress.
    """

    def __init__(self, seconds: float, burst: int) -> None:
        self.seconds = seconds
        self.burst = burst
        self._last: dict[str, float] = {}
        self._recent: dict[str, list[float]] = {}

    def allow(self, device: str, address: str) -> bool:
        stamp = time.monotonic()
        recent = [t for t in self._recent.get(address, []) if stamp - t < self.seconds]
        self._recent[address] = recent
        if len(recent) >= self.burst:
            return False
        key = device or address
        if stamp - self._last.get(key, -self.seconds) < self.seconds:
            return False
        self._last[key] = stamp
        recent.append(stamp)
        return True


class DeviceCap:
    """At most `cap` distinct grading devices per address per round, so minted tokens run out."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self._seen: dict[tuple[int, str], set[str]] = {}

    def allow(self, n: int, address: str, device: str) -> bool:
        seen = self._seen.setdefault((n, address), set())
        if device in seen or len(seen) < self.cap:
            seen.add(device)
            return True
        return False


VIEWER_ADDRESS = "cloudfront-viewer-address"


def client_of(request: Request, trusted_hops: int = 1, client_header: str = "") -> str:
    # Each trusted proxy appends to X-Forwarded-For, so the viewer is the entry the
    # outermost one wrote. Anything left of it is client-written. docs/room.md
    if client_header:
        named = request.headers.get(client_header, "").strip()
        if named:
            # CloudFront-Viewer-Address carries `address:port`, IPv6 unbracketed.
            return named.rsplit(":", 1)[0] if client_header.lower() == VIEWER_ADDRESS else named
    forwarded = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",")]
    forwarded = [hop for hop in forwarded if hop]
    if forwarded:
        return forwarded[max(len(forwarded) - trusted_hops, 0)]
    return request.client.host if request.client else "unknown"


def create_app(
    room: Room,
    cfg: Settings,
    control_token: str,
    rate_seconds: float = 20.0,
    address_burst: int = 30,
    devices_per_address: int = 100,
    client: httpx.AsyncClient | None = None,
    page: Path | None = PAGE,
    trusted_hops: int = 1,
    client_header: str = "",
) -> FastAPI:
    limit = RateLimit(rate_seconds, address_burst)
    ballots = DeviceCap(devices_per_address)
    state: dict[str, Engine] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        owned = client is None
        http = client or httpx.AsyncClient()
        state["engine"] = Engine(room, cfg, http)
        state["engine"].resume()
        try:
            yield
        finally:
            if owned:
                await http.aclose()

    app = FastAPI(title="housecast room", docs_url=None, redoc_url=None, lifespan=lifespan)

    def presenter(token: str | None) -> None:
        if not token or not secrets.compare_digest(token, control_token):
            raise HTTPException(status_code=403, detail="the control token does not match")

    def view_of(view: str | None, token: str | None) -> str:
        if view == "presenter":
            presenter(token)
            return "presenter"
        return "screen" if view == "screen" else "attendee"

    @app.get("/api/room")
    def snapshot(view: str | None = None) -> dict[str, Any]:
        return room.snapshot(view_of(view, None) if view != "presenter" else "attendee")

    @app.get("/api/control/room")
    def presenter_snapshot(x_control_token: str | None = Header(default=None)) -> dict[str, Any]:
        presenter(x_control_token)
        return room.snapshot("presenter")

    @app.get("/api/room/events")
    async def events(
        request: Request, view: str | None = None, token: str | None = None
    ) -> StreamingResponse:
        # EventSource sends no headers, so the presenter stream takes a query token.
        queue = room.subscribe(view_of(view, token))

        async def stream() -> AsyncIterator[str]:
            try:
                yield f"event: hello\ndata: {json.dumps({'rev': room.rev})}\n\n"
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    frame = json.dumps(event)
                    yield f"event: {event['kind']}\nid: {event['rev']}\ndata: {frame}\n\n"
            finally:
                room.unsubscribe(queue)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def refuse(refused: PromptRefusedError) -> JSONResponse:
        return JSONResponse({"reason": refused.reason}, refused.status)

    @app.post("/api/prompts", status_code=201, response_model=None)
    async def submit(intake: Intake, request: Request) -> dict[str, Any] | JSONResponse:
        try:
            state["engine"].validate(intake.text)
            if not limit.allow(intake.device, client_of(request, trusted_hops, client_header)):
                return JSONResponse({"reason": "one prompt at a time: wait a moment"}, 429)
            prompt = state["engine"].submit(intake.text)
        except PromptRefusedError as refused:
            return refuse(refused)
        return {"id": prompt["id"]}

    @app.post("/api/grades", response_model=None)
    def grade(sheet: GradeSheet, request: Request) -> dict[str, Any] | JSONResponse:
        address = client_of(request, trusted_hops, client_header)
        if sheet.device and not ballots.allow(sheet.round, address, sheet.device):
            return JSONResponse({"reason": "too many graders from this network"}, 429)
        try:
            graded = state["engine"].grade(sheet.round, sheet.device, sheet.grades, sheet.reasons)
        except PromptRefusedError as refused:
            return refuse(refused)
        return {"graded": graded}

    @app.post("/api/control/phase", response_model=None)
    def set_phase(
        change: PhaseChange, x_control_token: str | None = Header(default=None)
    ) -> dict[str, Any] | JSONResponse:
        presenter(x_control_token)
        try:
            state["engine"].set_phase(change.phase)
        except PromptRefusedError as refused:
            return refuse(refused)
        return {"phase": room.phase}

    @app.post("/api/control/pick", response_model=None)
    def pick(
        choice: Pick, x_control_token: str | None = Header(default=None)
    ) -> dict[str, Any] | JSONResponse:
        presenter(x_control_token)
        try:
            return state["engine"].pick(choice.prompt_id)
        except PromptRefusedError as refused:
            return refuse(refused)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True, "rev": room.rev}

    if KIT.exists():

        @app.get("/kit.css")
        def kit() -> FileResponse:
            return FileResponse(KIT, media_type="text/css")

    if page is not None and page.is_dir():
        for route, name in (("/screen", "screen.html"), ("/present", "present.html")):
            if (page / name).exists():
                app.add_api_route(route, _file(page / name), include_in_schema=False)
        app.mount("/", StaticFiles(directory=str(page), html=True), name="page")

    return app


def _file(path: Path) -> Any:
    def send() -> FileResponse:
        return FileResponse(path, media_type="text/html")

    return send


def serve(
    room: Room,
    cfg: Settings,
    control_token: str,
    host: str,
    port: int,
    rate_seconds: float,
    address_burst: int,
    devices_per_address: int,
    trusted_hops: int = 1,
    client_header: str = "",
) -> None:
    import uvicorn

    uvicorn.run(
        create_app(
            room,
            cfg,
            control_token,
            rate_seconds,
            address_burst,
            devices_per_address,
            trusted_hops=trusted_hops,
            client_header=client_header,
        ),
        host=host,
        port=port,
        log_level="warning",
        proxy_headers=False,
        # An SSE stream never ends on its own, so without a bound uvicorn waits on it
        # through the pod's whole grace period while refusing new requests.
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN,
    )
