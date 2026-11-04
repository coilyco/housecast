"""Every roster personality has a grading anchor, and every anchor is used.

The roster is read from this checkout through `go run ./cmd/agent-compose
catalog roles --json` in the checkout AGENT_COMPOSE_SRC names, so the check follows
the roster being edited.

The personality tier bypasses item analysis, so these anchors are the only
thing holding its scale still. A personality without one cannot be graded.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
from typing import Any

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
ANCHORS = ROOT / "evaluations" / "personality-anchors.yaml"


@pytest.fixture(scope="module")
def anchors() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(ANCHORS.read_text())
    return loaded


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


def test_every_melded_personality_has_an_anchor(
    roles: list[dict[str, Any]], anchors: dict[str, Any]
) -> None:
    traits = anchors["traits"]
    used = set()
    missing = []
    for role in roles:
        for personality in role["personalities"]:
            used.add(personality)
            if personality not in traits:
                missing.append(f"{role['slug']} melds {personality}")
    assert not missing, f"melded without a grading anchor: {missing}"
    assert not set(traits) - used, f"anchors matching no meld: {sorted(set(traits) - used)}"


def test_the_scale_is_complete(anchors: dict[str, Any]) -> None:
    assert anchors.get("version"), "anchors need a version the graded records can reference"
    scale = anchors["scale"]
    assert all(scale.get(point) for point in ("fit", "undecided", "does_not_fit"))
    assert anchors.get("universal_deductions")


@pytest.mark.parametrize("trait", sorted(yaml.safe_load(ANCHORS.read_text())["traits"]))
def test_anchors_name_behaviours_rather_than_restating_the_trait(
    anchors: dict[str, Any], trait: str
) -> None:
    entry = anchors["traits"][trait]
    for field in ("fit", "deduct", "distinguish"):
        assert entry.get(field), f"anchor {trait!r} is missing {field}"
    fit = entry["fit"].strip().lower()
    assert not fit.startswith(f"is {trait}"), f"anchor {trait!r} restates the trait"
    assert fit != trait, f"anchor {trait!r} restates the trait"
    assert "." in entry["distinguish"], f"anchor {trait!r} must name the neighbour it is not"
