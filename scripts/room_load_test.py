"""Hold one room under N simulated attendees through full rounds, and report what held.

Each attendee is an SSE client with its own device token. Every client must see every
page swap with no `rev` gap, and each subject's queue wait, run time and failures under
the fan-out are measured. It writes to the room's log, so run it against a dev or
rehearsal room. The token comes from a 0600 file. docs/room-load.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import stat
import sys
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

TERMINAL = frozenset({"done", "empty", "failed"})
PHASE_WAIT = 0.05


class Refused(Exception):
    """A control call the room turned away. Carries the status, never the token."""


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    at = (len(ordered) - 1) * q
    low = int(at)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (at - low)


def spread(values: list[float]) -> dict[str, Any]:
    def rounded(x: float | None) -> float | None:
        return None if x is None else round(x, 3)

    return {
        "n": len(values),
        "p50": rounded(quantile(values, 0.5)),
        "p95": rounded(quantile(values, 0.95)),
        "max": rounded(max(values) if values else None),
    }


def when(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def peak_concurrency(answers: list[dict[str, Any]]) -> int:
    """The most answers running at once, from the room's own start and finish stamps."""
    edges: list[tuple[float, int]] = []
    for answer in answers:
        if answer.get("started_at") and answer.get("finished_at"):
            edges += [(when(answer["started_at"]), 1), (when(answer["finished_at"]), -1)]
    edges.sort(key=lambda edge: (edge[0], edge[1]))
    running = peak = 0
    for _, step in edges:
        running += step
        peak = max(peak, running)
    return peak


async def sse_frames(reply: httpx.Response) -> AsyncIterator[tuple[str, str]]:
    event, data = "message", []
    async for line in reply.aiter_lines():
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif not line.startswith(":"):
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)


class Feed:
    """One simulated attendee: an event stream, a device token, and what it saw in order."""

    def __init__(self, index: int, base: str) -> None:
        self.index = index
        self.device = f"load-{index:02d}-{secrets.token_hex(3)}"
        self.http = httpx.AsyncClient(base_url=base, timeout=httpx.Timeout(30.0, read=None))
        self.rev = -1
        self.phase = ""
        self.round_n = 0
        self.graded: dict[int, int] = {}
        self.fallbacks: set[str] = set()
        self.phase_events: list[tuple[str, int, float]] = []
        self.gaps: list[tuple[int, int]] = []
        self.reconnects = 0
        self.resyncs = 0
        self.errors: list[str] = []
        self._wake = asyncio.Condition()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self.http.aclose()

    async def _run(self) -> None:
        connected = False
        while True:
            try:
                async with self.http.stream("GET", "api/room/events") as reply:
                    reply.raise_for_status()
                    if connected:
                        self.reconnects += 1
                    connected = True
                    await self._pump(reply)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # a dropped stream is what a restart does, so reconnect
                self.errors.append(type(err).__name__)
            await asyncio.sleep(0.25)

    async def _pump(self, reply: httpx.Response) -> None:
        async for kind, raw in sse_frames(reply):
            if kind == "hello":
                if json.loads(raw)["rev"] != self.rev:
                    await self._resync()
            else:
                await self._note(json.loads(raw))

    async def _resync(self) -> None:
        """Take the snapshot when the stream and this client disagree, as the pages do."""
        snap = (await self.http.get("api/room")).json()
        async with self._wake:
            if self.rev >= 0:
                self.resyncs += 1
            self.rev = snap["rev"]
            self.phase = snap["phase"]
            current = snap["round"]
            self.round_n = current["n"] if current else 0
            if current:
                self.graded[current["n"]] = current["graded"]
            self.phase_events.append((snap["phase"], snap["rev"], time.monotonic()))
            self._wake.notify_all()

    async def _note(self, event: dict[str, Any]) -> None:
        rev, kind, data = event["rev"], event["kind"], event["data"]
        async with self._wake:
            if rev <= self.rev:
                return  # a snapshot already covers it
            if self.rev >= 0 and rev != self.rev + 1:
                self.gaps.append((self.rev, rev))
            self.rev = rev
            if kind == "phase":
                self.phase = data["phase"]
                self.phase_events.append((data["phase"], rev, time.monotonic()))
            elif kind == "round":
                self.round_n = data["n"]
            elif kind == "grades":
                self.graded[data["n"]] = data["graded"]
            elif kind == "fallback":
                self.fallbacks.add(data["prompt_id"])
            self._wake.notify_all()

    async def until(self, ready: Any, timeout: float) -> bool:
        async def wait() -> None:
            async with self._wake:
                await self._wake.wait_for(ready)

        try:
            await asyncio.wait_for(wait(), timeout)
        except TimeoutError:
            return False
        return True

    async def saw_phase(self, phase: str, after_rev: int, timeout: float) -> float | None:
        """When this client learned the room reached `phase`, or None if it never did."""

        def ready() -> bool:
            return any(p == phase and r > after_rev for p, r, _ in self.phase_events)

        if not await self.until(ready, timeout):
            return None
        return next(t for p, r, t in self.phase_events if p == phase and r > after_rev)


class Presenter:
    def __init__(self, base: str, token: str) -> None:
        self.http = httpx.AsyncClient(
            base_url=base, timeout=30.0, headers={"x-control-token": token}
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def snapshot(self) -> dict[str, Any]:
        reply = await self.http.get("api/control/room")
        if not reply.is_success:
            raise Refused(f"api/control/room answered {reply.status_code}")
        return dict(reply.json())

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        reply = await self.http.post(path, json=body)
        if not reply.is_success:
            raise Refused(f"{path} answered {reply.status_code}: {reply.text[:160]}")
        return dict(reply.json())


# Plain questions, so a subject answers the way it does for an attendee. Tagged prompts
# ("Load <id> round 1 client 10") sent Frog-Ox looking for files with those names.
QUESTIONS = (
    "Is being unsure a virtue?",
    "When should you admit you do not know something?",
    "Is it better to be kind or to be honest?",
    "What makes a good explanation?",
    "Should a team ever ship something it is not proud of?",
    "Is it fair to judge an idea by who proposed it?",
    "What is the most useful habit for learning something hard?",
    "When is a rule worth breaking?",
    "Is a fast answer ever better than a careful one?",
    "How do you tell a good question from a bad one?",
    "What should you do when two experts disagree?",
    "Is it okay to change your mind in public?",
)
ENDS = (".", "!", "?", '"', "'", ")", "]", "*", "`", "\u201d", "\u2019")


class Run:
    def __init__(self, args: argparse.Namespace, presenter: Presenter, feeds: list[Feed]) -> None:
        self.args = args
        self.presenter = presenter
        self.feeds = feeds
        self.out: Path = args.out
        self.failures: list[str] = []
        self.findings: list[str] = []
        self.rounds: list[dict[str, Any]] = []
        self.replay: dict[str, Any] | None = None
        self.id = secrets.token_hex(2)
        self.last_submit = 0.0

    def fail(self, text: str) -> None:
        self.failures.append(text)
        print(f"FAIL {text}", file=sys.stderr, flush=True)

    async def swap(self, phase: str) -> dict[str, Any]:
        """The presenter moves the room, and every client must learn it."""
        before = (await self.presenter.snapshot())["rev"]
        sent = time.monotonic()
        await self.presenter.post("api/control/phase", {"phase": phase})
        return await self.watch(phase, before, sent)

    async def watch(self, phase: str, before: int, sent: float) -> dict[str, Any]:
        seen = await asyncio.gather(
            *(f.saw_phase(phase, before, self.args.swap_timeout) for f in self.feeds)
        )
        missed = [f.index for f, t in zip(self.feeds, seen, strict=True) if t is None]
        if missed:
            self.fail(f"clients {missed} never saw the swap to {phase}")
        return spread([(t - sent) * 1000 for t in seen if t is not None])

    async def submit_all(self, n: int) -> tuple[list[str], dict[str, Any]]:
        gap = self.args.round_gap - (time.monotonic() - self.last_submit)
        if self.last_submit and gap > 0:
            await asyncio.sleep(gap)

        async def one(feed: Feed) -> tuple[int, float, dict[str, Any]]:
            text = QUESTIONS[(feed.index + n) % len(QUESTIONS)]
            began = time.monotonic()
            reply = await feed.http.post("api/prompts", json={"text": text, "device": feed.device})
            body = reply.json() if reply.content else {}
            return reply.status_code, (time.monotonic() - began) * 1000, body

        self.last_submit = time.monotonic()
        results = await asyncio.gather(*(one(f) for f in self.feeds))
        ids = [body["id"] for status, _, body in results if status == 201]
        refused: dict[str, int] = {}
        for status, _, _ in results:
            if status != 201:
                refused[str(status)] = refused.get(str(status), 0) + 1
        if refused:
            self.fail(f"round {n}: submissions refused {refused}")
        latency = spread([ms for _, ms, _ in results])
        return ids, {"created": len(ids), "refused": refused, "latency_ms": latency}

    async def settle(self, prompt_ids: list[str], subjects: int) -> tuple[dict[str, Any], float]:
        """Poll until every answer and score for these prompts is terminal, or the wait ends."""
        began = time.monotonic()
        wanted = set(prompt_ids)
        while True:
            snap = await self.presenter.snapshot()
            answers = [a for a in snap["answers"] if a["prompt_id"] in wanted]
            scored = [d for d in snap["divergence"] if d["prompt_id"] in wanted]
            done = (
                len(answers) == len(wanted) * subjects
                and all(a["state"] in TERMINAL for a in answers)
                and len(scored) == len(wanted)
                and all(d["state"] in ("done", "failed") for d in scored)
            )
            if done or time.monotonic() - began > self.args.answer_timeout:
                return snap, time.monotonic() - began
            await asyncio.sleep(1.0)

    def measure(self, snap: dict[str, Any], prompt_ids: list[str]) -> dict[str, Any]:
        wanted = set(prompt_ids)
        at = {p["id"]: when(p["at"]) for p in snap["prompts"] if p["id"] in wanted}
        answers = [a for a in snap["answers"] if a["prompt_id"] in wanted]
        labels = {s["id"]: s["label"] for s in snap["subjects"]}
        per: dict[str, Any] = {}
        for subject_id, label in labels.items():
            mine = [a for a in answers if a["subject_id"] == subject_id]
            timed = [a for a in mine if a.get("started_at") and a.get("finished_at")]
            reasons: dict[str, int] = {}
            for a in mine:
                if a["state"] in ("failed", "empty"):
                    why = a.get("reason", a["state"])
                    reasons[why] = reasons.get(why, 0) + 1
            per[label] = {
                "answers": len(mine),
                "done": sum(1 for a in mine if a["state"] == "done"),
                "empty": sum(1 for a in mine if a["state"] == "empty"),
                # No finish_reason reaches the room, so a done answer that ends off a
                # sentence mark stands in for one cut off mid-sentence.
                "cut_off": sum(
                    1 for a in mine if a["state"] == "done" and not a["text"].rstrip().endswith(ENDS)
                ),
                "not_done": reasons,
                "queue_s": spread([when(a["started_at"]) - at[a["prompt_id"]] for a in timed]),
                "run_s": spread([when(a["finished_at"]) - when(a["started_at"]) for a in timed]),
                "total_s": spread([when(a["finished_at"]) - at[a["prompt_id"]] for a in timed]),
            }
        scored = [d for d in snap["divergence"] if d["prompt_id"] in wanted]
        methods: dict[str, int] = {}
        for d in scored:
            key = d.get("method", d["state"])
            methods[key] = methods.get(key, 0) + 1
        return {
            "per_subject": per,
            "divergence": methods,
            "peak_running": peak_concurrency(answers),
            "stuck": sum(1 for a in answers if a["state"] not in TERMINAL),
        }

    async def grade_all(self, n: int, subject_ids: list[str]) -> dict[str, Any]:
        def marks(feed: Feed) -> dict[str, str]:
            return {
                s: "pass" if (feed.index + i) % 3 else "fail" for i, s in enumerate(subject_ids)
            }

        async def one(feed: Feed) -> tuple[int, float]:
            grades = marks(feed)
            reasons = {s: "Hedged when asked for a position." for s, v in grades.items() if v == "fail"}
            body = {"round": n, "device": feed.device, "grades": grades, "reasons": reasons}
            began = time.monotonic()
            reply = await feed.http.post("api/grades", json=body)
            return reply.status_code, (time.monotonic() - began) * 1000

        results = await asyncio.gather(*(one(f) for f in self.feeds))
        refused: dict[str, int] = {}
        for status, _ in results:
            if status != 200:
                refused[str(status)] = refused.get(str(status), 0) + 1
        if refused:
            self.fail(f"round {n}: grades refused {refused}")
        return {
            "sent": len(results),
            "refused": refused,
            "latency_ms": spread([ms for _, ms in results]),
        }

    async def check_split(self, n: int, subject_ids: list[str]) -> dict[str, Any]:
        snap = await self.presenter.snapshot()
        row = next(r for r in snap["rounds"] if r["n"] == n)
        expected = {s: {"pass": 0, "fail": 0} for s in subject_ids}
        for feed in self.feeds:
            for i, s in enumerate(subject_ids):
                expected[s]["pass" if (feed.index + i) % 3 else "fail"] += 1
        # A real client outside the harness adds one grade per subject of its own.
        extra = {
            s: [row["split"][s][k] - expected[s][k] for k in ("pass", "fail")] for s in subject_ids
        }
        ok = all(min(e) >= 0 and sum(e) <= self.args.outside_graders for e in extra.values())
        if not ok:
            self.fail(f"round {n}: the split does not match the {len(self.feeds)} grades sent")
        return {"totals_match": ok, "outside_grades": sum(sum(e) for e in extra.values()), "split": row["split"]}

    async def checkpoint(self, where: str, n: int) -> dict[str, Any]:
        snap = await self.presenter.snapshot()
        cp = {
            "where": where,
            "round": n,
            "rev": snap["rev"],
            "phase": snap["phase"],
            "rounds": [(r["n"], r["prompt_id"]) for r in snap["rounds"]],
            "prompts": [p["id"] for p in snap["prompts"]],
            "answers": {
                f"{a['prompt_id']}/{a['subject_id']}": [a["state"], a.get("text", "")]
                for a in snap["answers"]
            },
            "graded": snap["round"]["graded"] if snap["round"] else 0,
        }
        (self.out / "checkpoint.json").write_text(json.dumps(cp, indent=2))
        return cp

    async def pause(self, where: str, n: int) -> None:
        cp = await self.checkpoint(where, n)
        resume = self.args.resume_file or self.out / "RESUME"
        print(
            f"PAUSED at {where} of round {n}, rev {cp['rev']}. Restart the room, "
            f"then create {resume}",
            file=sys.stderr,
            flush=True,
        )
        deadline = time.monotonic() + self.args.pause_timeout
        while not resume.exists():
            if time.monotonic() > deadline:
                self.fail("the pause ended with no resume file")
                return
            await asyncio.sleep(1.0)
        resume.unlink(missing_ok=True)
        await self.verify_replay(cp)

    async def verify_replay(self, cp: dict[str, Any]) -> None:
        began = time.monotonic()
        snap: dict[str, Any] = {}
        while time.monotonic() - began < self.args.restart_timeout:
            try:
                snap = await self.presenter.snapshot()
                break
            except (httpx.HTTPError, Refused):
                await asyncio.sleep(1.0)
        if not snap:
            self.fail("the room did not come back after the restart")
            return
        checks: dict[str, bool] = {
            "phase kept": snap["phase"] == cp["phase"],
            "rounds kept": [(r["n"], r["prompt_id"]) for r in snap["rounds"]] == [
                tuple(r) for r in cp["rounds"]
            ],
            "prompts kept": set(cp["prompts"]) <= {p["id"] for p in snap["prompts"]},
            "rev did not fall": snap["rev"] >= cp["rev"],
            "grades kept": (snap["round"]["graded"] if snap["round"] else 0) >= cp["graded"],
        }
        now = {f"{a['prompt_id']}/{a['subject_id']}": a for a in snap["answers"]}
        finished = {k: v for k, v in cp["answers"].items() if v[0] in TERMINAL}
        checks["finished answers kept"] = all(
            k in now and now[k]["state"] == v[0] and now[k].get("text", "") == v[1]
            for k, v in finished.items()
        )
        cut = [k for k, v in cp["answers"].items() if v[0] not in TERMINAL]
        settled, _ = await self.settle(cp["prompts"], len(snap["subjects"]))
        after = {f"{a['prompt_id']}/{a['subject_id']}": a["state"] for a in settled["answers"]}
        checks["cut answers asked again"] = all(after.get(k) in TERMINAL for k in cut)
        target = (await self.presenter.snapshot())["rev"]
        caught = await asyncio.gather(*(f.until(lambda f=f: f.rev >= target, 30.0) for f in self.feeds))
        checks["clients caught up"] = all(caught)
        for name, ok in checks.items():
            if not ok:
                self.fail(f"replay: {name} is false")
        self.replay = {
            "checkpoint": cp["where"],
            "cut_answers": len(cut),
            "checks": checks,
            "down_s": round(time.monotonic() - began, 1),
            "client_resyncs": [f.resyncs for f in self.feeds],
            "client_reconnects": [f.reconnects for f in self.feeds],
        }

    async def round(self, n: int) -> None:
        record: dict[str, Any] = {"round": n}
        marks: dict[str, float] = {"start": time.monotonic()}
        record["steps_s"] = marks
        record["fanout_ms"] = {"submissions": await self.swap("submissions")}
        marks["opened"] = time.monotonic()
        ids, submitted = await self.submit_all(n)
        record["submissions"] = submitted
        marks["submitted"] = time.monotonic()
        snap = await self.presenter.snapshot()
        subjects = [s["id"] for s in snap["subjects"]]
        if self.args.pause_at == "answering" and n == self.args.pause_round:
            await self.pause("answering", n)
        snap, waited = await self.settle(ids, len(subjects))
        if any(a["state"] == "failed" for a in snap["answers"]):
            await asyncio.sleep(1.0)  # a fallback re-asks the round, so look again
            snap, waited = await self.settle(ids, len(subjects))
        marks["settled"] = time.monotonic()
        record["answers"] = self.measure(snap, ids)
        record["answers"]["settled_s"] = round(waited, 1)
        record["answers"]["waited_out"] = record["answers"]["stuck"] > 0
        for label, per in record["answers"]["per_subject"].items():
            if per["empty"]:
                self.findings.append(f"round {n}: {label} gave {per['empty']} empty answers")
            if per["cut_off"]:
                self.findings.append(f"round {n}: {label} had {per['cut_off']} answers with no closing mark")
        watcher = self.feeds[0]
        await watcher.until(lambda: watcher.rev >= snap["rev"], self.args.swap_timeout)
        record["fallbacks"] = len(set(ids) & watcher.fallbacks)
        if record["fallbacks"]:
            self.findings.append(
                f"round {n}: {record['fallbacks']} prompts moved to the fallback model, "
                "so their primary answers failed"
            )
        if record["answers"]["stuck"]:
            self.fail(f"round {n}: {record['answers']['stuck']} answers never finished")
        if not ids:
            self.rounds.append(record)
            return
        before = snap["rev"]
        sent = time.monotonic()
        await self.presenter.post("api/control/pick", {"prompt_id": ids[(n - 1) % len(ids)]})
        record["fanout_ms"]["grading"] = await self.watch("grading", before, sent)
        if self.args.pause_at == "grading" and n == self.args.pause_round:
            await self.pause("grading", n)
        marks["picked"] = time.monotonic()
        # The room refuses a grade on a card with no answer, so the page draws none.
        picked = ids[(n - 1) % len(ids)]
        silent = {
            a["subject_id"]
            for a in (await self.presenter.snapshot())["answers"]
            if a["prompt_id"] == picked and a["state"] in ("empty", "failed")
        }
        gradable = [s for s in subjects if s not in silent]
        record["grades"] = await self.grade_all(n, gradable)
        marks["graded"] = time.monotonic()
        target = len(self.feeds)
        counted = await asyncio.gather(
            *(f.until(lambda f=f: f.graded.get(n, 0) >= target, self.args.swap_timeout) for f in self.feeds)
        )
        late = [f.index for f, ok in zip(self.feeds, counted, strict=True) if not ok]
        if late:
            self.fail(f"round {n}: clients {late} never saw all {target} grades counted")
        hidden = (await self.feeds[0].http.get("api/room")).json()
        shown = next((r for r in hidden["rounds"] if r["n"] == n), {})
        if "split" in shown:
            self.fail(f"round {n}: an attendee saw the split while grading was open")
        marks["counted"] = time.monotonic()
        record["fanout_ms"]["split"] = await self.swap("split")
        record["split"] = await self.check_split(n, gradable)
        marks["end"] = time.monotonic()
        record["steps_s"] = {
            k: round(v - marks["start"], 2) for k, v in marks.items() if k != "start"
        }
        self.rounds.append(record)


def load_token(path: Path | None) -> str:
    if path is None:
        token = os.environ.get("ROOM_CONTROL_TOKEN", "")
    else:
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise SystemExit(f"{path} is readable by others: chmod 600 it before use")
        token = path.read_text().strip()
    if not token:
        raise SystemExit("no control token: pass --token-file or set ROOM_CONTROL_TOKEN")
    return token


def summarize(run: Run, report: dict[str, Any]) -> None:
    lines = [f"clients {len(run.feeds)} | rounds {len(run.rounds)} | base {report['base']}"]
    for r in run.rounds:
        swaps = ", ".join(f"{k} p95 {v['p95']}ms" for k, v in r["fanout_ms"].items())
        ans = r.get("answers", {})
        lines.append(
            f"round {r['round']} | steps {r.get('steps_s')} | fan-out {swaps} | settled {ans.get('settled_s')}s"
            f" | peak running {ans.get('peak_running')} | divergence {ans.get('divergence')}"
        )
        for label, s in ans.get("per_subject", {}).items():
            lines.append(
                f"  {label} | done {s['done']}/{s['answers']} | queue p95 {s['queue_s']['p95']}s"
                f" | run p50 {s['run_s']['p50']}s p95 {s['run_s']['p95']}s | not done {s['not_done']}"
            )
    if run.replay:
        lines.append(f"replay at {run.replay['checkpoint']}: {run.replay['checks']}")
    lines.append("gaps per client: " + str([len(f.gaps) for f in run.feeds]))
    for finding in run.findings:
        lines.append(f"FINDING {finding}")
    for failure in run.failures:
        lines.append(f"FAIL {failure}")
    print("\n".join(lines))


async def drive(args: argparse.Namespace, token: str) -> tuple[Run, dict[str, Any]]:
    presenter = Presenter(args.base, token)
    feeds = [Feed(i, args.base) for i in range(args.clients)]
    run = Run(args, presenter, feeds)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        for feed in feeds:
            await feed.start()
        ready = await asyncio.gather(*(f.until(lambda f=f: f.rev >= 0, 30.0) for f in feeds))
        graded = (await presenter.snapshot())["rounds"]
        if not all(ready):
            run.fail("some clients never connected to the event stream")
        elif graded:
            # Rounds are numbered from 1 here, so a used log would refuse every grade.
            run.fail(f"the room already has {len(graded)} rounds. Start it on an empty log")
        else:
            for n in range(1, args.rounds + 1):
                await run.round(n)
        for feed in feeds:
            if feed.gaps:
                run.fail(f"client {feed.index} skipped revs {feed.gaps[:3]}")
            if feed.reconnects and not run.replay:
                run.fail(f"client {feed.index} dropped its stream {feed.reconnects} times")
        for r in run.rounds:
            for label, s in r.get("answers", {}).get("per_subject", {}).items():
                missing = s["answers"] - s["done"]
                if missing > args.allow_failed_answers:
                    run.fail(f"round {r['round']}: {label} did not answer {missing}: {s['not_done']}")
            lexical = r.get("answers", {}).get("divergence", {}).get("lexical", 0)
            if lexical:
                run.findings.append(f"round {r['round']}: {lexical} scores fell back to lexical")
    finally:
        for feed in feeds:
            await feed.stop()
        await presenter.close()
    report = {
        "base": httpx.URL(args.base).host,
        "started": started,
        "clients": args.clients,
        "rounds": run.rounds,
        "replay": run.replay,
        "failures": run.failures,
        "findings": run.findings,
        "passed": not run.failures,
    }
    return run, report


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Hold a room under simulated attendees.")
    p.add_argument("--base", required=True, help="the room's origin, for example https://room.example")
    p.add_argument("--token-file", type=Path, help="a 0600 file holding the presenter control token")
    p.add_argument("--clients", type=int, default=30)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--round-gap", type=float, default=21.0, help="seconds between submit waves")
    p.add_argument("--answer-timeout", type=float, default=180.0)
    p.add_argument("--swap-timeout", type=float, default=20.0)
    p.add_argument("--restart-timeout", type=float, default=300.0)
    p.add_argument("--pause-at", choices=("none", "answering", "grading"), default="none")
    p.add_argument("--pause-round", type=int, default=2)
    p.add_argument("--pause-timeout", type=float, default=1800.0)
    p.add_argument("--resume-file", type=Path)
    p.add_argument("--allow-failed-answers", type=int, default=0)
    p.add_argument("--outside-graders", type=int, default=0, help="real clients that may also grade")
    p.add_argument("--out", type=Path, default=Path("dist/room-load-test"))
    p.add_argument("--writes", action="store_true", help="confirm this room's log may take test prompts")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.writes:
        parser().error("this submits and grades, so pass --writes, and only against a dev or rehearsal room")
    args.base = args.base.rstrip("/") + "/"
    args.out.mkdir(parents=True, exist_ok=True)
    token = load_token(args.token_file)
    run, report = asyncio.run(drive(args, token))
    (args.out / "report.json").write_text(json.dumps(report, indent=2))
    summarize(run, report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
