"""Replay a trajectory ledger file into a live agent-proxy through its public intake.

Reads the source SQLite file immutable and POSTs each stored envelope to the intake in
sequence order. The intake is idempotent, so a second run reports duplicates and adds
nothing. Dry run is the default and `--apply` sends. Exits 1 on any quarantined or errored
event, or when the counts do not sum to the attempted total. `--help` has the details.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

NOTES = """\
Details:
  immutable    the source is opened with immutable=1, so a WAL or shm file beside a backup
               is never read or written
  idempotent   the intake dedups on event_id and on (source, idempotency_key)
  output       only event ids and status codes reach stdout and --out, never an envelope
  provenance   a replay lands as ordinary accepted receipts, so the target ledger tells it
               from native traffic only by each event's own session id
  docs         there is no docs page, since docs/ is at its cap
"""

INTAKE = "/v1/trajectory/events"
OUTCOMES = {202: "accepted", 200: "duplicate", 422: "quarantined"}
RETRYABLE = {429, 500, 502, 503, 504}


def source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_events(path: Path, limit: int | None) -> list[tuple[str, bytes]]:
    """(event_id, envelope) in sequence order. `immutable=1` skips the WAL and shm files."""
    connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        sql = "SELECT event_id, envelope FROM events ORDER BY sequence"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return [(str(row[0]), bytes(row[1])) for row in connection.execute(sql)]
    finally:
        connection.close()


def bare_url(url: str) -> str:
    """The base URL without userinfo, query or fragment, safe to print."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", ""))


def post(url: str, body: bytes, timeout: float) -> int:
    """One POST. Any HTTP status comes back as an int. A transport error raises OSError."""
    request = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            reply.read()
            return int(reply.status)
    except urllib.error.HTTPError as err:
        err.read()
        return int(err.code)


def get_status(url: str, timeout: float) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as reply:
            return int(reply.status)
    except urllib.error.HTTPError as err:
        return int(err.code)


def send(url: str, body: bytes, timeout: float, retries: int, backoff: float) -> tuple[int, int]:
    """(final status, retries used). Status 0 means the transport never answered."""
    used = 0
    while True:
        try:
            status = post(url, body, timeout)
        except OSError:
            status = 0
        if status not in RETRYABLE and status != 0:
            return status, used
        if used >= retries:
            return status, used
        used += 1
        time.sleep(backoff * used)


def replay(
    events: list[tuple[str, bytes]],
    base: str,
    *,
    timeout: float,
    retries: int,
    backoff: float,
    pause: float,
) -> dict[str, Any]:
    counts = {"accepted": 0, "duplicate": 0, "quarantined": 0, "error": 0}
    problems: list[dict[str, Any]] = []
    retried = 0
    for event_id, envelope in events:
        status, used = send(base + INTAKE, envelope, timeout, retries, backoff)
        retried += used
        outcome = OUTCOMES.get(status, "error")
        counts[outcome] += 1
        if outcome in ("quarantined", "error"):
            problems.append({"event_id": event_id, "status": status})
        if pause:
            time.sleep(pause)
    return {"counts": counts, "retried": retried, "problems": problems}


def summarise(
    path: Path, base: str, attempted: int, applied: bool, result: dict[str, Any] | None
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "source": str(path),
        "source_sha256": source_sha256(path),
        "target": bare_url(base),
        "mode": "apply" if applied else "dry-run",
        "attempted": attempted,
        "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if result is not None:
        counts = result["counts"]
        summary.update(result)
        summary["balanced"] = sum(counts.values()) == attempted
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, epilog=NOTES, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--source", required=True, type=Path, help="ledger SQLite file to read")
    parser.add_argument("--url", required=True, help="agent-proxy base URL, no trailing path")
    parser.add_argument("--apply", action="store_true", help="send. Without it nothing is sent")
    parser.add_argument("--limit", type=int, help="replay only the first N events by sequence")
    parser.add_argument("--out", type=Path, help="also write the summary JSON here")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--retries", type=int, default=5, help="per event, on 429, 5xx, or no reply"
    )
    parser.add_argument(
        "--backoff", type=float, default=0.5, help="seconds, times the retry number"
    )
    parser.add_argument("--pause", type=float, default=0.0, help="seconds between events")
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(f"no such ledger file: {args.source}", file=sys.stderr)
        return 2
    events = read_events(args.source, args.limit)
    base = args.url.rstrip("/")
    result: dict[str, Any] | None = None
    if args.apply:
        status = get_status(base + "/healthz", args.timeout)
        if status != 200:
            print(f"refusing to send, {bare_url(base)}/healthz answered {status}", file=sys.stderr)
            return 2
        result = replay(
            events,
            base,
            timeout=args.timeout,
            retries=args.retries,
            backoff=args.backoff,
            pause=args.pause,
        )
    summary = summarise(args.source, base, len(events), args.apply, result)
    text = json.dumps(summary, indent=2, sort_keys=True)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    if result is None:
        return 0
    clean = summary["balanced"] and not result["problems"]
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
