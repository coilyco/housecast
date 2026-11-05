"""Board role names stay on the roster's current slugs, whatever challenges.yaml says."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
from typing import Any

import pytest

from evalkit.filter import load_challenges
from evalkit.roleslug import canonical, canonical_case

ROOT = pathlib.Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.usefixtures("agent_compose_src")


def test_canonical_maps_a_retired_slug_and_passes_anything_else() -> None:
    assert canonical(" science ") == "scientist"
    assert canonical("sysadmin") == "sysadmin-senior"
    assert canonical("scientist") == "scientist"
    assert canonical("analyst") == "analyst"
    assert canonical("grounded") == "grounded"


def test_canonical_case_maps_entity_and_attribute_only() -> None:
    raw = {"id": "science-fit-gamedev", "entity": "science", "attribute": "gamedev"}
    assert canonical_case(raw) == {
        "id": "science-fit-gamedev",
        "entity": "scientist",
        "attribute": "game-dev",
    }
    assert raw["entity"] == "science", "the authored entry is not mutated"


@pytest.fixture(scope="module")
def roles(agent_compose_src: pathlib.Path) -> list[dict[str, Any]]:
    raw = subprocess.run(
        ["go", "run", "./cmd/agent-compose", "catalog", "roles", "--json"],
        cwd=agent_compose_src,
        env={**os.environ, "AGENT_COMPOSE_ROSTER": str(agent_compose_src / "seed" / "roster")},
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    items: list[dict[str, Any]] = json.loads(raw)["items"]
    return items


def test_every_board_case_names_a_live_role(roles: list[dict[str, Any]]) -> None:
    live = {r["slug"] for r in roles if not r.get("archived")}
    every = {r["slug"] for r in roles}
    board = load_challenges(ROOT / "challenges.yaml")
    stale = sorted({c.entity for c in board} - live)
    assert not stale, f"cases whose entity is no live role: {stale}"
    # `within` is the in-half of a role-fit pair, the seat on its own work.
    targets = {c.attribute or "" for c in board if c.test_type == "role-fit"} - {"within"}
    fit = sorted(targets - every)
    assert not fit, f"role-fit targets that are no role at all: {fit}"
