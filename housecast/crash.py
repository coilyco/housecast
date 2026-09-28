"""Crash reporting to Sentry for the housecast servers and CLIs.

Crashes only, each one fully annotated: integrations stay on, logs become
breadcrumbs, and the keys that hold graded content are scrubbed rather than
switching locals off (teable:coilyco/deploy#8347). Importing the library never
calls this, only the CLI entrypoint does, so a consumer's process is untouched.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

EVENTS_PER_MINUTE = 20
DSN_FILE = Path("~/.config/housecast/sentry-dsn")

# Names that hold what a person wrote, what a model said, or how it was graded.
USER_DATA_KEYS = [
    "prompt",
    "prompts",
    "response",
    "responses",
    "reply",
    "messages",
    "message",
    "content",
    "text",
    "transcript",
    "answer",
    "answers",
    "grade",
    "grades",
    "critique",
    "critiques",
    "rationale",
    "notes",
    "note",
    "comment",
    "comments",
    "vote",
    "votes",
    "body",
    "payload",
    # Starlette/FastAPI keep the raw request bytes in their own frame.
    "body_bytes",
]

_initialized = False
_window: list[float] = []


def _within_budget(now: float) -> bool:
    cutoff = now - 60.0
    while _window and _window[0] < cutoff:
        _window.pop(0)
    if len(_window) >= EVENTS_PER_MINUTE:
        return False
    _window.append(now)
    return True


def _before_send(event: Any, _hint: Any) -> Any:
    return event if _within_budget(time.monotonic()) else None


def _dsn() -> str:
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if dsn:
        return dsn
    path = Path(os.environ.get("HOUSECAST_SENTRY_DSN_FILE", str(DSN_FILE))).expanduser()
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def init_crash_reporting() -> bool:
    """Turn crash reporting on once, when a DSN is configured and the SDK is installed."""
    global _initialized
    if _initialized:
        return False
    _initialized = True
    dsn = _dsn()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber
    except ImportError:
        # The SDK rides the eval, room and mcp extras; the bare library has none.
        return False
    try:
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=0.0,
            send_default_pii=False,
            before_send=_before_send,
            event_scrubber=EventScrubber(
                denylist=DEFAULT_DENYLIST + USER_DATA_KEYS, recursive=True
            ),
            integrations=[
                LoggingIntegration(event_level=None),
                StarletteIntegration(failed_request_status_codes=set()),
                FastApiIntegration(failed_request_status_codes=set()),
            ],
        )
    except Exception as exc:
        # The class only: a BadDsn message can carry the DSN itself.
        _log.warning("Sentry initialization failed (%s); continuing", type(exc).__name__)
        return False
    return True
