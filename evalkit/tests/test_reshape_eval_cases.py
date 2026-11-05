"""The 121 hand-authored cases reshape into the eval-only schema and stay lossless."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml

from evalkit.roleslug import canonical_case
from housecast.grade.schema import EvalCase

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "reshape_eval_cases.py"
CHALLENGES = Path(__file__).resolve().parents[2] / "challenges.yaml"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("reshape_eval_cases", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_challenges() -> list[dict[str, Any]]:
    payload: dict[str, Any] = yaml.safe_load(CHALLENGES.read_text(encoding="utf-8"))
    challenges: list[dict[str, Any]] = payload["challenges"]
    return challenges


@pytest.mark.usefixtures("agent_compose_src")
def test_every_case_validates_against_the_schema() -> None:
    cases = _load().reshape(_raw_challenges())
    assert all(isinstance(case, EvalCase) for case in cases)


@pytest.mark.usefixtures("agent_compose_src")
def test_reshaping_is_lossless_on_count_and_id() -> None:
    raw = _raw_challenges()
    cases = _load().reshape(raw)
    assert len(cases) == len(raw)
    assert [case.id for case in cases] == [entry["id"] for entry in raw]


@pytest.mark.usefixtures("agent_compose_src")
def test_roster_vocabulary_moves_into_metadata_and_nowhere_else() -> None:
    """entity/test_type/attribute/half/pair_id are gone as fields, present as metadata keys."""
    raw = _raw_challenges()
    cases = {case.id: case for case in _load().reshape(raw)}
    for entry in map(canonical_case, raw):
        case = cases[entry["id"]]
        assert case.input == entry["prompt"]
        assert case.target == entry["target"]
        for key in ("entity", "test_type", "attribute", "half", "pair_id"):
            if entry.get(key) is not None:
                assert case.metadata[key] == str(entry[key])


@pytest.mark.usefixtures("agent_compose_src")
def test_the_cli_writes_a_file_the_schema_accepts(tmp_path: Path) -> None:
    out = tmp_path / "eval_cases.yaml"
    module = _load()
    assert module.main(["--source", str(CHALLENGES), "--out", str(out)]) == 0
    payload = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert payload["schema"] == "housecast.eval-case.v1"
    assert len(payload["cases"]) == len(_raw_challenges())
    for raw_case in payload["cases"]:
        EvalCase.model_validate(raw_case)
