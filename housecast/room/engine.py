"""Fan one prompt out to every subject, then score how far apart they landed.

Each subject answers on its own task, so the room shows four clocks rather than
one spinner. Divergence runs once every answer is terminal, over the answers
that came back non-empty.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import Callable
from typing import Any

import httpx

from housecast.room import models
from housecast.room.store import PHASES, TERMINAL, Room, now

log = logging.getLogger(__name__)

MAX_PROMPT = 280
MAX_CASE = 2000  # a presenter-prepared case may carry pasted context
MAX_COMMITMENT = 140
RETRY_PAUSE = 2.0
RAW_KEPT = 2048  # characters of an emptied reply the log keeps, for the operator only
MAX_REASON = 140
VERDICTS = frozenset({"pass", "fail"})


class PromptRefusedError(Exception):
    """A request the room will not take. The page shows `reason` verbatim."""

    def __init__(self, reason: str, status: int = 422) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


class Engine:
    def __init__(
        self, room: Room, cfg: models.Settings, client: httpx.AsyncClient, concurrency: int = 40
    ) -> None:
        self.room = room
        self.cfg = cfg
        self.client = client
        self._slots = asyncio.Semaphore(concurrency)
        self._routes = {m: asyncio.Semaphore(n) for m, n in cfg.route_limits.items()}
        self._tasks: set[asyncio.Task[None]] = set()

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def validate(self, text: str) -> str:
        if self.room.phase != "submissions":
            raise PromptRefusedError("submissions are not open", 409)
        return self._clean(text)

    @staticmethod
    def _clean(text: str, limit: int = MAX_PROMPT) -> str:
        text = text.strip()  # inner newlines stay, a case may be several lines
        if not text:
            raise PromptRefusedError("the prompt is empty")
        if len(text) > limit:
            raise PromptRefusedError(f"the prompt is over {limit} characters")
        return text

    @staticmethod
    def check_commitment(commitment: str | None) -> str:
        commitment = (commitment or "").strip()
        if len(commitment) > MAX_COMMITMENT:
            raise PromptRefusedError(f"the commitment is over {MAX_COMMITMENT} characters")
        return commitment

    def submit(self, text: str, commitment: str | None = None) -> dict[str, Any]:
        """An attendee prompt, taken only while submissions are open."""
        return self._open(self.validate(text), self.check_commitment(commitment), "attendee")

    def prepare(self, text: str, commitment: str | None = None) -> dict[str, Any]:
        """A presenter case, taken in any phase. It fans out like an attendee prompt."""
        text = self._clean(text, MAX_CASE)
        return self._open(text, self.check_commitment(commitment), "prepared")

    def _open(self, text: str, commitment: str, source: str) -> dict[str, Any]:
        prompt = {
            "id": secrets.token_hex(4),
            "seq": len(self.room.prompts) + 1,
            "text": text,
            "commitment": commitment,
            "source": source,
            "at": now(),
        }
        self.room.emit("prompt", prompt)
        self.room.emit("divergence", {"prompt_id": prompt["id"], "state": "pending"})
        for subject in self.room.subjects:
            self.room.emit(
                "answer",
                {"prompt_id": prompt["id"], "subject_id": subject["id"], "state": "queued"},
            )
            self._spawn(self._answer(prompt, subject))
        return prompt

    async def _answer(self, prompt: dict[str, Any], subject: dict[str, str]) -> None:
        base = {"prompt_id": prompt["id"], "subject_id": subject["id"]}
        route = self._model_for(prompt, subject) or self.cfg.model
        # The route's cap comes first, so answers waiting on it hold no global slot.
        async with self._routes.get(route) or contextlib.nullcontext(), self._slots:
            started = now()
            self.room.emit("answer", {**base, "state": "running", "started_at": started})
            try:
                text = await self._call(
                    subject["system"],
                    prompt["text"],
                    self._model_for(prompt, subject),
                    self._keep_raw(base),
                )
            except Exception as failed:  # the room shows it, and the other subjects carry on
                self.room.emit(
                    "answer",
                    {
                        **base,
                        "state": "failed",
                        "started_at": started,
                        "finished_at": now(),
                        "reason": _reason(failed),
                    },
                )
            else:
                done: dict[str, Any] = {**base, "started_at": started, "finished_at": now()}
                if text:
                    done.update(state="done", text=text)
                else:
                    done.update(state="empty", reason="the subject returned no text")
                self.room.emit("answer", done)
        await self._maybe_score(prompt)

    def _keep_raw(self, base: dict[str, str]) -> Callable[[int, str], None]:
        def keep(attempt: int, raw: str) -> None:
            note = {**base, "attempt": attempt, "chars": len(raw), "raw": raw[:RAW_KEPT]}
            self.room.note("raw_empty", note)

        return keep

    def _model_for(self, prompt: dict[str, Any], subject: dict[str, str]) -> str | None:
        """None is the room's model. A switched round uses the model its event logged."""
        switched = self.room.fallbacks.get(prompt["id"])
        return switched["model"] if switched else subject.get("model")

    async def _call(
        self,
        system: str,
        text: str,
        model: str | None = None,
        on_empty: Callable[[int, str], None] | None = None,
    ) -> str:
        """One answer under the deadline. A transient proxy error is retried up to
        cfg.retries times, and an answer that strips to nothing, a subject that tried to
        run a command, is asked once more."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.cfg.answer_deadline
        errors = empties = 0
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError
            try:
                raw = await asyncio.wait_for(
                    models.complete(self.client, self.cfg, system, text, model), timeout=remaining
                )
            except (httpx.TransportError, httpx.HTTPStatusError) as err:
                errors += 1
                if errors > self.cfg.retries or not _transient(err):
                    raise
                await asyncio.sleep(min(RETRY_PAUSE * errors, max(0.0, deadline - loop.time())))
                continue
            answer = models.strip_markup(raw)
            if not answer and on_empty:
                on_empty(errors + empties + 1, raw)
            if answer or empties:
                return answer
            empties += 1

    async def _maybe_score(self, prompt: dict[str, Any]) -> None:
        answers = self.room.answers_for(prompt["id"])
        if len(answers) < len(self.room.subjects) or any(
            a["state"] not in TERMINAL for a in answers
        ):
            return
        if self.room.divergence.get(prompt["id"], {}).get("state") != "pending":
            return
        if self._maybe_fall_back(prompt, answers):
            return
        texts = [a["text"] for a in answers if a["state"] == "done"]
        base = {"prompt_id": prompt["id"]}
        if len(texts) < 2:
            self.room.emit(
                "divergence",
                {**base, "state": "failed", "reason": "fewer than two answers came back"},
            )
            return
        # Marked before the await, so two subjects finishing at once score once.
        self.room.divergence[prompt["id"]] = {**base, "state": "scoring"}
        try:
            score = await models.stance(self.client, self.cfg, prompt["text"], texts, prompt["id"])
            method = "stance"
        except Exception:  # lexical is the measured fallback, looser than Jev
            score, method = models.lexical(texts), "lexical"
        self.room.emit(
            "divergence", {**base, "state": "done", "score": round(score, 4), "method": method}
        )

    def _maybe_fall_back(self, prompt: dict[str, Any], answers: list[dict[str, Any]]) -> bool:
        """Re-ask the whole round on the fallback model when any answer ended failed.

        Once per prompt, and never after a pick, since the answers would change under the
        grading room. Nothing awaits between the check and the emit, so it fires once.
        """
        fallback = self.cfg.fallback_model
        failed = [a["subject_id"] for a in answers if a["state"] == "failed"]
        if not fallback or not failed or prompt["id"] in self.room.fallbacks:
            return False
        if prompt["id"] in self.room.picked():
            log.warning("prompt %s already picked, so its failed answers stay", prompt["id"])
            return False
        self.room.emit("fallback", {"prompt_id": prompt["id"], "model": fallback, "failed": failed})
        log.warning(
            "prompt %s: %d of %d answers failed, so the round moves to %s",
            prompt["id"],
            len(failed),
            len(answers),
            fallback,
        )
        for subject in self.room.subjects:
            base = {"prompt_id": prompt["id"], "subject_id": subject["id"]}
            self.room.emit("answer", {**base, "state": "queued"})
            self._spawn(self._answer(prompt, subject))
        return True

    def set_phase(self, phase: str) -> None:
        if phase not in PHASES:
            raise PromptRefusedError(f"a phase is one of {', '.join(PHASES)}")
        self.room.emit("phase", {"phase": phase})

    def pick(self, prompt_id: str) -> dict[str, Any]:
        """Start the next round on one prompt. The pick is also the moderation filter."""
        if not any(p["id"] == prompt_id for p in self.room.prompts):
            raise PromptRefusedError("no such prompt")
        current = self.room.current
        round_ = {"n": (current["n"] + 1) if current else 1, "prompt_id": prompt_id}
        self.room.emit("round", round_)
        self.room.emit("phase", {"phase": "grading"})
        return round_

    def grade(self, n: int, device: str, marks: dict[str, str], reasons: dict[str, str]) -> int:
        current = self.room.current
        if self.room.phase != "grading" or current is None:
            raise PromptRefusedError("grading is not open", 409)
        if n != current["n"]:
            raise PromptRefusedError("that round is over", 409)
        if not device:
            raise PromptRefusedError("a grade needs a device token")
        known = {s["id"] for s in self.room.subjects}
        graded: dict[str, dict[str, str]] = {}
        for subject_id, verdict in marks.items():
            if subject_id not in known or verdict not in VERDICTS:
                raise PromptRefusedError("each grade is pass or fail for a known subject")
            mark = {"verdict": verdict}
            reason = reasons.get(subject_id, "").strip()
            if len(reason) > MAX_REASON:
                raise PromptRefusedError(f"a reason is at most {MAX_REASON} characters")
            if reason and verdict == "fail":
                mark["reason"] = reason
            graded[subject_id] = mark
        if not graded:
            raise PromptRefusedError("no grades were sent")
        self.room.emit("grades", {"n": n, "device": device, "grades": graded})
        return self.room.graded(n)

    def resume(self) -> int:
        """Re-run what a restart cut off, and re-score prompts left pending."""
        prompts = {p["id"]: p for p in self.room.prompts}
        subjects = {s["id"]: s for s in self.room.subjects}
        cut = self.room.unfinished()
        for answer in cut:
            prompt, subject = prompts.get(answer["prompt_id"]), subjects.get(answer["subject_id"])
            if prompt and subject:
                self.room.emit(
                    "answer",
                    {**{k: answer[k] for k in ("prompt_id", "subject_id")}, "state": "queued"},
                )
                self._spawn(self._answer(prompt, subject))
        for prompt in self.room.prompts:
            if self.room.divergence.get(prompt["id"], {}).get("state") in ("pending", "scoring"):
                self.room.divergence[prompt["id"]] = {"prompt_id": prompt["id"], "state": "pending"}
                self._spawn(self._maybe_score(prompt))
        return len(cut)

    async def drain(self) -> None:
        # A finished task leaves `_tasks` a loop turn late, and gathering only finished
        # tasks never yields, so a round that respawns its answers would spin here.
        while pending := [t for t in self._tasks if not t.done()]:
            await asyncio.gather(*pending, return_exceptions=True)


def _transient(err: Exception) -> bool:
    if isinstance(err, httpx.HTTPStatusError):
        return err.response.status_code == 429 or err.response.status_code >= 500
    return isinstance(err, httpx.TransportError)


def _reason(failed: Exception) -> str:
    if isinstance(failed, (httpx.TimeoutException, TimeoutError)):
        return "the subject timed out"
    if isinstance(failed, httpx.HTTPStatusError):
        return f"the model route answered {failed.response.status_code}"
    return "the subject could not be reached"
