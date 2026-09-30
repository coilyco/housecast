"""Watch a live room from outside: poll GET /api/room, print what a presenter misses.

Reads only. Every request is a bare GET of /api/room with no token, cookie or body,
so it can point at the public origin. Each poll prints one summary line, then a line
for anything that needs eyes. `--help` says what each part counts. There is no docs
page, since docs/ is at its cap.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

NO_ANSWER = frozenset({"failed", "empty"})

LEGEND = """\
A header line names each subject's model_label, on the first poll and again whenever one
changes, so a hot-swap shows. Then one line per poll, for example:
  02:51:33Z rev 32 submissions no round | no-answer: Violet 0, Amber 2 (+1) | no-reply: ...

no-answer      each subject's failed and empty answers in the room log, and (+n) when
               that grew since the last poll
no-reply       each subject's settled answers whose jev.replied is false or null. Null is
               Jev not answering, or a check still in flight, so a count that falls back
               is normal. Failed and empty answers are in no-answer, not here
slow           answers running past --slow seconds, one extra line each
jev-fallback*  rounds scored by word overlap because Jev did not answer, the star the
               pages show. Those rounds have divergence.confidence null

Also reported: a room that stops answering, a sign-in page in front of it, and a rev or
prompt count that goes down, which is what a restart onto a fresh log looks like.
"""


def parse_stamp(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def clock(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%H:%M:%SZ")


def summarize(snapshot: dict[str, Any], now: float, slow: float) -> dict[str, Any]:
    """Counts a person watching the room would want, from one attendee-view snapshot."""
    round_of = {r["prompt_id"]: r["n"] for r in snapshot.get("rounds", [])}
    subjects = {s["id"]: s.get("label", s["id"]) for s in snapshot.get("subjects", [])}
    models = {s["id"]: s.get("model_label") for s in snapshot.get("subjects", [])}
    no_answer = dict.fromkeys(subjects, 0)
    no_reply = dict.fromkeys(subjects, 0)
    slow_answers: list[dict[str, Any]] = []
    for answer in snapshot.get("answers", []):
        subject = answer["subject_id"]
        if answer["state"] in NO_ANSWER:
            no_answer[subject] = no_answer.get(subject, 0) + 1
        elif answer["state"] == "done" and (answer.get("jev") or {}).get("replied") is not True:
            no_reply[subject] = no_reply.get(subject, 0) + 1
        elif answer["state"] == "running" and answer.get("started_at"):
            running_for = now - parse_stamp(answer["started_at"])
            if running_for > slow:
                slow_answers.append(
                    {
                        "subject": subjects.get(subject, subject),
                        "prompt": _prompt_name(answer["prompt_id"], round_of),
                        "seconds": int(running_for),
                    }
                )
    fallbacks = [
        _prompt_name(d["prompt_id"], round_of)
        for d in snapshot.get("divergence", [])
        if d.get("state") == "done" and d.get("method") == "lexical"
    ]
    current = snapshot.get("round")
    return {
        "rev": snapshot.get("rev"),
        "phase": snapshot.get("phase"),
        "round": None if current is None else current.get("n"),
        "prompts": len(snapshot.get("prompts", [])),
        "labels": subjects,
        "models": models,
        "no_answer": no_answer,
        "no_reply": no_reply,
        "slow": slow_answers,
        "fallbacks": fallbacks,
    }


def _prompt_name(prompt_id: str, round_of: dict[str, int]) -> str:
    return f"round {round_of[prompt_id]}" if prompt_id in round_of else f"prompt {prompt_id[:8]}"


def report(
    now: float, seen: dict[str, Any], before: dict[str, Any] | None, slow: float
) -> list[str]:
    """The lines for one poll: a summary, then a line for anything that changed or needs eyes."""
    where = f"round {seen['round']}" if seen["round"] is not None else "no round"
    lines = []
    if seen["models"] and (before is None or before["models"] != seen["models"]):
        lines.append(f"{clock(now)} models: {_models(seen)}")
    lines.append(
        f"{clock(now)} rev {seen['rev']} {seen['phase']} {where}"
        f" | no-answer: {_tally(seen, 'no_answer', before)}"
        f" | no-reply: {_tally(seen, 'no_reply', before)}"
        f" | slow>{slow:g}s: {len(seen['slow'])}"
        f" | jev-fallback*: {len(seen['fallbacks'])}"
    )
    lines += [
        f"{clock(now)}   slow: {s['subject']} on {s['prompt']} running {s['seconds']}s"
        for s in seen["slow"]
    ]
    fresh = [f for f in seen["fallbacks"] if before is None or f not in before["fallbacks"]]
    if before is not None and fresh:
        lines.append(f"{clock(now)}   jev fallback*: {', '.join(fresh)} scored by word overlap")
    went_back = (
        before is not None
        and seen["rev"] is not None
        and before["rev"] is not None
        and (seen["rev"] < before["rev"] or seen["prompts"] < before["prompts"])
    )
    if before is not None and went_back:
        lines.append(
            f"{clock(now)}   rev went {before['rev']} to {seen['rev']},"
            f" prompts {before['prompts']} to {seen['prompts']}: the room may be on a fresh log"
        )
    return lines


def _models(seen: dict[str, Any]) -> str:
    return ", ".join(
        f"{seen['labels'][subject]} on {model or 'no model_label'}"
        for subject, model in seen["models"].items()
    )


def _tally(seen: dict[str, Any], key: str, before: dict[str, Any] | None) -> str:
    """One count per subject, with (+n) when it grew since the last poll."""
    parts = []
    for subject, total in seen[key].items():
        gained = total - before[key].get(subject, 0) if before else 0
        parts.append(f"{seen['labels'][subject]} {total}" + (f" (+{gained})" if gained > 0 else ""))
    return ", ".join(parts)


def fetch(base: str, timeout: float) -> dict[str, Any]:
    """One GET of /api/room. Raises on a transport error, a non-200 answer or a non-JSON body."""
    request = urllib.request.Request(
        f"{base}/api/room", method="GET", headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        if reply.status != 200:
            raise ValueError(f"status {reply.status}")
        try:
            body = json.loads(reply.read())
        except ValueError as err:
            raise ValueError("body is not JSON, is a sign-in page in front of the room?") from err
    if not isinstance(body, dict):
        raise ValueError("body is not a snapshot")
    return body


def watch(
    base: str,
    interval: float,
    slow: float,
    timeout: float,
    iterations: int,
    emit: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    clock_now: Callable[[], float] = time.time,
) -> None:
    before: dict[str, Any] | None = None
    failures = 0
    polled = 0
    while iterations == 0 or polled < iterations:
        if polled:
            sleep(interval)
        polled += 1
        now = clock_now()
        try:
            snapshot = fetch(base, timeout)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as err:
            failures += 1
            emit(f"{clock(now)} poll failed ({failures} in a row): {_why(err)}")
            continue
        if failures:
            emit(f"{clock(now)} the room answers again after {failures} failed polls")
            failures = 0
        seen = summarize(snapshot, now, slow)
        for line in report(now, seen, before, slow):
            emit(line)
        before = seen


def _why(err: Exception) -> str:
    if isinstance(err, urllib.error.HTTPError):
        return f"HTTP {err.code}"
    if isinstance(err, urllib.error.URLError):
        return str(err.reason)
    return str(err) or type(err).__name__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0],
        epilog=LEGEND,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base", required=True, help="room origin, e.g. https://room.example")
    parser.add_argument("--interval", type=float, default=15.0, help="seconds between polls")
    parser.add_argument("--slow", type=float, default=60.0, help="flag answers running longer")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds to wait on one GET")
    parser.add_argument(
        "--iterations", type=int, default=0, help="stop after N polls, 0 is forever"
    )
    args = parser.parse_args(argv)
    parts = urlsplit(args.base)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path not in {"", "/"}:
        parser.error("--base is an http or https origin with no path")
    if args.interval <= 0 or args.slow <= 0 or args.timeout <= 0 or args.iterations < 0:
        parser.error("--interval, --slow and --timeout are positive, --iterations is not negative")
    try:
        watch(
            f"{parts.scheme}://{parts.netloc}",
            args.interval,
            args.slow,
            args.timeout,
            args.iterations,
            emit=lambda line: print(line, flush=True),
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
