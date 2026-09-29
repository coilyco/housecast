"""The room's state as an append-only event log, replayed on restart.

Every change is one event with a monotonic `rev`, logged before it applies.
What a view may see differs: grades are a count until the split, answer text
shows once picked, and the recorded screen never sees unpicked prompt text.
See docs/room.md.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TERMINAL = frozenset({"done", "empty", "failed"})
PHASES = ("holding", "submissions", "grading", "split", "closing")
# Attendees never learn which model is behind a label, so `model` stays out with `system`.
HIDDEN_SUBJECT_KEYS = frozenset({"system", "model"})
VIEWS = ("attendee", "screen", "presenter")


def with_prompt_defaults(data: dict[str, Any]) -> dict[str, Any]:
    """A log from before commitments has neither key, so it replays as an attendee prompt."""
    return {"commitment": "", "source": "attendee", **data}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Room:
    subjects: list[dict[str, str]]
    log_path: Path | None = None
    phase: str = "holding"
    rev: int = 0
    prompts: list[dict[str, Any]] = field(default_factory=list)
    answers: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    divergence: dict[str, dict[str, Any]] = field(default_factory=dict)
    # prompt_id -> the fallback event's data. Its `model` is what a restart resumes with.
    fallbacks: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Deleted ids. A late answer for one is dropped, so a replay never revives it.
    removed: set[str] = field(default_factory=set)
    rounds: list[dict[str, Any]] = field(default_factory=list)
    # (round n, device) -> {subject_id: {"verdict", "reason"?}}
    grades: dict[tuple[int, str], dict[str, dict[str, str]]] = field(default_factory=dict)
    _listeners: dict[asyncio.Queue[dict[str, Any]], str] = field(default_factory=dict)

    def load(self) -> None:
        """Replay the log. A torn last line is a write the crash interrupted, so it is dropped."""
        if self.log_path is None or not self.log_path.exists():
            return
        for line in self.log_path.read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._apply(event)

    def emit(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        if kind == "prompt":
            data = with_prompt_defaults(data)
        event = {"rev": self.rev + 1, "at": now(), "kind": kind, "data": data}
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as log:
                log.write(json.dumps(event, separators=(",", ":")) + "\n")
                log.flush()
        self._apply(event)
        for queue, view in list(self._listeners.items()):
            queue.put_nowait(self.project(event, view))
        return event

    def note(self, kind: str, data: dict[str, Any]) -> None:
        """A log line for the operator. It takes no rev and reaches no view or stream."""
        if self.log_path is None:
            return
        event = {"rev": self.rev, "at": now(), "kind": kind, "data": data}
        with self.log_path.open("a") as log:
            log.write(json.dumps(event, separators=(",", ":")) + "\n")
            log.flush()

    def _apply(self, event: dict[str, Any]) -> None:
        kind, data = event["kind"], event["data"]
        self.rev = max(self.rev, int(event["rev"]))
        if kind == "prompt":
            self.prompts.append(with_prompt_defaults(data))
        elif kind == "answer":
            if data["prompt_id"] not in self.removed:
                self.answers[(data["prompt_id"], data["subject_id"])] = data
        elif kind == "divergence":
            if data["prompt_id"] not in self.removed:
                self.divergence[data["prompt_id"]] = data
        elif kind == "removed":
            gone = data["prompt_id"]
            self.removed.add(gone)
            self.prompts = [p for p in self.prompts if p["id"] != gone]
            self.answers = {k: v for k, v in self.answers.items() if k[0] != gone}
            self.divergence.pop(gone, None)
            self.fallbacks.pop(gone, None)
        elif kind == "rerun":
            # The fallback may fire again for the new round, so the old mark goes.
            self.fallbacks.pop(data["prompt_id"], None)
            self.divergence[data["prompt_id"]] = {
                "prompt_id": data["prompt_id"],
                "state": "pending",
            }
        elif kind == "fallback":
            # One event re-queues the whole round, so a crash cannot leave it mixed.
            self.fallbacks[data["prompt_id"]] = data
            for subject in self.subjects:
                key = {"prompt_id": data["prompt_id"], "subject_id": subject["id"]}
                self.answers[(data["prompt_id"], subject["id"])] = {**key, "state": "queued"}
        elif kind == "phase":
            self.phase = data["phase"]
        elif kind == "round":
            self.rounds.append({"n": data["n"], "prompt_id": data["prompt_id"]})
        elif kind == "grades":
            self.grades[(data["n"], data["device"])] = data["grades"]

    # -- what each view may see ------------------------------------------------

    @property
    def current(self) -> dict[str, Any] | None:
        return self.rounds[-1] if self.rounds else None

    def picked(self) -> set[str]:
        return {r["prompt_id"] for r in self.rounds}

    def graded(self, n: int) -> int:
        return sum(1 for (rn, _) in self.grades if rn == n)

    def split(self, n: int) -> dict[str, dict[str, Any]]:
        tally: dict[str, dict[str, Any]] = {s["id"]: {"pass": 0, "fail": 0} for s in self.subjects}
        for (rn, _), marks in self.grades.items():
            if rn != n:
                continue
            for subject_id, mark in marks.items():
                if subject_id in tally:
                    tally[subject_id][mark["verdict"]] += 1
        for row in tally.values():
            total = row["pass"] + row["fail"]
            row["share"] = round(row["pass"] / total, 4) if total else None
        return tally

    def revealed(self, n: int, view: str) -> bool:
        """A round's split shows once the presenter reaches the split, never while grading."""
        current = self.current
        if view == "presenter" or current is None or n < current["n"]:
            return True
        return self.phase in ("split", "closing")

    def _answer_view(self, answer: dict[str, Any], view: str) -> dict[str, Any]:
        if view == "presenter" or answer["prompt_id"] in self.picked() or "text" not in answer:
            return answer
        return {k: v for k, v in answer.items() if k != "text"}

    def _prompt_view(self, prompt: dict[str, Any], view: str) -> dict[str, Any]:
        """Screen hides unpicked text. A prepared case hides text and commitment from both."""
        if view == "presenter":
            return prompt
        shown = dict(prompt)
        if prompt["id"] in self.picked():
            return shown
        if view == "screen" or prompt["source"] == "prepared":
            shown = {k: v for k, v in shown.items() if k != "text"}
            shown["commitment"] = ""
        return shown

    def snapshot(self, view: str = "attendee") -> dict[str, Any]:
        current = self.current
        snap: dict[str, Any] = {
            "rev": self.rev,
            "phase": self.phase,
            "round": None if current is None else {**current, "graded": self.graded(current["n"])},
            "subjects": [
                {k: v for k, v in s.items() if k not in HIDDEN_SUBJECT_KEYS} for s in self.subjects
            ],
            "prompts": [self._prompt_view(p, view) for p in self.prompts],
            "answers": [self._answer_view(a, view) for a in self.answers.values()],
            "divergence": list(self.divergence.values()),
            "rounds": [
                {**r, "split": self.split(r["n"])} if self.revealed(r["n"], view) else dict(r)
                for r in self.rounds
            ],
        }
        if view == "presenter" or self.phase == "closing":
            failures = self.failures()
            # The recorded screen gets who failed, not the words, until Kai rules.
            if view == "screen":
                failures = [{k: v for k, v in f.items() if k != "reason"} for f in failures]
            snap["failures"] = failures
        return snap

    def failures(self) -> list[dict[str, Any]]:
        return [
            {"n": n, "subject_id": subject_id, "reason": mark["reason"]}
            for (n, _), marks in self.grades.items()
            for subject_id, mark in marks.items()
            if mark["verdict"] == "fail" and mark.get("reason")
        ]

    def project(self, event: dict[str, Any], view: str) -> dict[str, Any]:
        """One event as a view may see it. Grades travel as a count, never a direction."""
        kind, data = event["kind"], event["data"]
        if kind == "answer":
            data = self._answer_view(data, view)
        elif kind == "prompt":
            data = self._prompt_view(data, view)
        elif kind == "fallback":
            data = {"prompt_id": data["prompt_id"]}  # that a switch happened, never to what
        elif kind == "grades" and view != "presenter":
            data = {"n": data["n"], "graded": self.graded(data["n"])}
        return {**event, "data": data}

    # -- subscriptions ---------------------------------------------------------

    def subscribe(self, view: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listeners[queue] = view
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._listeners.pop(queue, None)

    # -- engine helpers --------------------------------------------------------

    def unfinished(self) -> list[dict[str, Any]]:
        """Answers a restart cut off mid-call, in room order."""
        order = {p["id"]: p["seq"] for p in self.prompts}
        pending = [a for a in self.answers.values() if a["state"] not in TERMINAL]
        return sorted(pending, key=lambda a: order.get(a["prompt_id"], 0))

    def answers_for(self, prompt_id: str) -> list[dict[str, Any]]:
        return [
            self.answers[(prompt_id, s["id"])]
            for s in self.subjects
            if (prompt_id, s["id"]) in self.answers
        ]
