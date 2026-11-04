"""A derived role runs its parent's cases as well as any of its own."""

from __future__ import annotations

import json
from pathlib import Path

from housecast.grade.schema import Challenge, Half

from evalkit.task import inherit_parent_cases, load_derives


def _case(case_id: str, entity: str, pair_id: str | None = None) -> Challenge:
    half = next(iter(Half)) if pair_id else None
    return Challenge(
        id=case_id, entity=entity, test_type="positive", prompt="p", pair_id=pair_id, half=half
    )


def test_a_child_gets_each_parent_case_rekeyed_to_itself() -> None:
    written = [_case("s1", "senior", "pair-1"), _case("j1", "junior"), _case("o1", "other")]

    out = inherit_parent_cases(written, {"junior": "senior"})

    inherited = [c for c in out if c.id == "s1@junior"]
    assert len(out) == 4
    assert len(inherited) == 1
    assert inherited[0].entity == "junior"
    assert inherited[0].pair_id == "pair-1@junior"


def test_no_map_means_no_inheritance(tmp_path: Path) -> None:
    assert load_derives(tmp_path) == {}
    (tmp_path / "derives.json").write_text(json.dumps({"junior": "senior"}))
    assert load_derives(tmp_path) == {"junior": "senior"}
