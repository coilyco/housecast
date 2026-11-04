"""Map a retired role slug to its current one, from the table the Go launcher embeds.

challenges.yaml keeps the slugs it was authored and graded under, so its case ids
still line up with committed boards. Loading maps them to the roster's current
slugs. The table is internal/roleslug/retired.json in the agent-compose source,
one file for both languages, found through AGENT_COMPOSE_SRC.
"""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

ROLE_FIELDS = ("entity", "attribute")


def table_path() -> Path:
    """The retired-slug table inside the agent-compose source named by AGENT_COMPOSE_SRC."""
    src = os.environ.get("AGENT_COMPOSE_SRC")
    if not src:
        raise RuntimeError("set AGENT_COMPOSE_SRC to the agent-compose source checkout")
    return Path(src) / "internal" / "roleslug" / "retired.json"


@cache
def _retired() -> dict[str, str]:
    loaded: dict[str, str] = json.loads(table_path().read_text(encoding="utf-8"))
    return loaded


def canonical(slug: str) -> str:
    slug = slug.strip()
    return _retired().get(slug, slug)


def canonical_case(entry: dict[str, Any]) -> dict[str, Any]:
    """A raw challenge with its role-bearing fields on current slugs."""
    mapped = dict(entry)
    for field in ROLE_FIELDS:
        if isinstance(mapped.get(field), str):
            mapped[field] = canonical(mapped[field])
    return mapped
