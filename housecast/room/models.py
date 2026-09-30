"""The two outbound calls: a subject's answer, and Jev's divergence score.

Both go to one OpenAI-compatible proxy. Answers use `/v1/chat/completions` and
Jev uses `/v1/systemone`. A failed call becomes a state the room shows, never a
silent retry.
"""

from __future__ import annotations

import itertools
import random
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

# Levels as the divergence measurement defined them, so a room score and the
# measured score mean the same thing. Score is the expected level over 4.
LEVELS = ["same", "slight", "moderate", "large", "opposite"]

# Subjects are told to run commands, and a harness-less call returns the markup.
_BAR, _SEP = chr(0xFF5C), chr(0x2581)  # DeepSeek's fullwidth tool-call fences
_MARKUP = [
    re.compile(r"<tool_call>.*?</tool_call>", re.S),
    re.compile(r"<(tool|function)_calls>.*?</\1_calls>", re.S),
    re.compile(
        f"<{_BAR}tool{_SEP}calls{_SEP}begin{_BAR}>.*?<{_BAR}tool{_SEP}calls{_SEP}end{_BAR}>", re.S
    ),
    re.compile(r"<(?:antml:)?invoke\b.*?</(?:antml:)?invoke>", re.S),
    # DeepSeek's DSML fence: doubled bars, a spaced `calls`, possibly never closed.
    re.compile(f"<{_BAR}+DSML{_BAR}+ *(\\w*calls)>.*?(?:</{_BAR}+DSML{_BAR}+ *\\1>|\\Z)", re.S),
    # What the block patterns leave behind: a wrapper with its call already removed.
    re.compile(r"</?(?:tool|function)_calls>"),
]


class ModelRefusedError(ValueError):
    """A configured room model whose name says it is an Anthropic model."""


# A name heuristic only. What the proxy routes a name to is the real control. docs/room.md
_BARRED = ("claude", "anthropic")


def check_model_name(name: str, where: str) -> str:
    if any(word in name.lower() for word in _BARRED):
        raise ModelRefusedError(
            f"{where}: {name!r} names an Anthropic model, and the room never sends "
            "inference to one. Pick a non-Anthropic route."
        )
    return name


def strip_markup(text: str) -> str:
    for pattern in _MARKUP:
        text = pattern.sub("", text)
    return text.strip()


@dataclass
class Settings:
    proxy: str
    model: str
    jev_model: str
    key: str | None = None
    # Sent as `user` and as x-agent-session-id, which the proxy stamps on its spans.
    user: str = "housecast-room"
    max_tokens: int = 4000
    temperature: float = 0.7
    frame: str = "Answer in under 150 words."
    # One deadline across both attempts, so a stuck subject turns `failed` and the
    # round can be picked. The measured p95 was 43s.
    answer_deadline: float = 120.0
    jev_timeout: float = 60.0
    # None means no fallback: a failed answer stays failed, as it always has.
    fallback_model: str | None = None
    # Most answers in flight on one route, by model name. A route not listed has no cap.
    route_limits: dict[str, int] = field(default_factory=dict)
    # Extra asks after a transient proxy error, spaced 2s, 4s, ... inside the deadline.
    retries: int = 1

    def __post_init__(self) -> None:
        if self.fallback_model:
            check_model_name(self.fallback_model, "the fallback model")
        if self.retries < 0 or any(n < 1 for n in self.route_limits.values()):
            raise ValueError("retries must be 0 or more and every route limit 1 or more")

    def headers(self) -> dict[str, str]:
        headers = {"x-agent-session-id": self.user}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        return headers


async def complete(
    client: httpx.AsyncClient,
    cfg: Settings,
    system: str,
    prompt: str,
    model: str | None = None,
) -> str:
    """The model's reply as it came back, before any markup is stripped."""
    user = f"{prompt}\n\n{cfg.frame}" if cfg.frame else prompt
    reply = await client.post(
        f"{cfg.proxy}/v1/chat/completions",
        json={
            "model": model or cfg.model,
            "user": cfg.user,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        headers=cfg.headers(),
        timeout=cfg.answer_deadline,
    )
    reply.raise_for_status()
    return str(reply.json()["choices"][0]["message"].get("content") or "")


def jev_body(prompt: str, texts: list[str], key: str, model: str) -> dict[str, Any]:
    """Answers go in a seeded shuffle, so position carries no subject."""
    order = list(range(len(texts)))
    random.Random(key).shuffle(order)
    state: dict[str, str] = {"prompt": prompt}
    for label, index in zip("ABCDEFGH", order, strict=False):
        state[f"answer_{label}"] = texts[index]
    return {
        "model": model,
        "state": state,
        "questions": {
            "divergence": {
                "type": "score",
                "instructions": (
                    f"How far apart are the stances these {len(texts)} answers take on the prompt?"
                ),
                "criteria": LEVELS,
            }
        },
    }


def expected_level(reply: dict[str, Any]) -> float:
    scored = reply["answers"]["divergence"]
    if "score" in scored:
        return float(scored["score"])
    probs = {int(k): float(v) for k, v in scored["probabilities"].items()}
    return sum(k * v for k, v in probs.items()) / sum(probs.values())


def _unit(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and 0 <= value <= 1 else None


def reading(reply: dict[str, Any]) -> tuple[float, float | None, dict[str, float] | None]:
    """The score on 0..1, Jev's confidence in it, and its level probabilities when it sent them."""
    scored = reply["answers"]["divergence"]
    probs = scored.get("probabilities")
    kept = {str(k): float(v) for k, v in probs.items()} if probs else None
    score = max(0.0, min(1.0, expected_level(reply) / (len(LEVELS) - 1)))
    return score, _unit(scored.get("confidence")), kept


async def stance_read(
    client: httpx.AsyncClient, cfg: Settings, prompt: str, texts: list[str], key: str
) -> tuple[float, float | None, dict[str, float] | None]:
    reply = await client.post(
        f"{cfg.proxy}/v1/systemone",
        json=jev_body(prompt, texts, key, cfg.jev_model),
        headers=cfg.headers(),
        timeout=cfg.jev_timeout,
    )
    reply.raise_for_status()
    return reading(reply.json())


async def stance(
    client: httpx.AsyncClient, cfg: Settings, prompt: str, texts: list[str], key: str
) -> float:
    return (await stance_read(client, cfg, prompt, texts, key))[0]


def replied_body(prompt: str, answer: str, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "state": {"prompt": prompt, "answer": answer},
        "questions": {
            "replied": {
                "type": "noul",
                "instructions": (
                    "Is the answer a reply to the prompt at all? An empty answer, an error "
                    "message, or no content is not a reply."
                ),
                "criteria": {
                    "true": "The answer is a reply to the prompt.",
                    "false": "The answer is empty, an error, or not a reply.",
                },
            }
        },
    }


async def replied(client: httpx.AsyncClient, cfg: Settings, prompt: str, answer: str) -> float:
    """Jev's probability that the answer is a reply at all. It is not a grade."""
    reply = await client.post(
        f"{cfg.proxy}/v1/systemone",
        json=replied_body(prompt, answer, cfg.jev_model),
        headers=cfg.headers(),
        timeout=cfg.jev_timeout,
    )
    reply.raise_for_status()
    return max(0.0, min(1.0, float(reply.json()["answers"]["replied"]["noul"])))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def lexical(texts: list[str]) -> float:
    """Mean pairwise Jaccard distance. The fallback, and it scores looser than Jev."""
    distances = []
    for a, b in itertools.combinations(texts, 2):
        wa, wb = _words(a), _words(b)
        union = wa | wb
        distances.append(1 - (len(wa & wb) / len(union)) if union else 0.0)
    return sum(distances) / len(distances) if distances else 0.0
