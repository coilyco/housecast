"""The pieces of the room e2e runner that need no browser. The full run is a local room."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "room_e2e.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("room_e2e", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(**changes: Any) -> dict[str, Any]:
    good: dict[str, Any] = {
        "subjects": [{"id": "s1", "label": "Violet", "model_label": "Flash"}],
        "answers": [
            {
                "prompt_id": "p1",
                "subject_id": "s1",
                "state": "done",
                "jev": {"replied": True, "confidence": 0.9, "p": 0.9, "source": "jev"},
            }
        ],
        "divergence": [{"prompt_id": "p1", "state": "done", "method": "stance", "confidence": 0.7}],
    }
    return {**good, **changes}


def test_the_long_case_is_several_lines_under_the_target_and_ends_on_the_question() -> None:
    text = _load().case_text(1500)
    assert 1350 <= len(text) <= 1500
    assert text.count("\n") > 5 and text.splitlines()[-1].startswith("Question:")


@pytest.mark.parametrize(
    ("room", "refused"),
    [
        ({"prompts": [], "rounds": []}, False),
        ({"prompts": [{"id": "a"}], "rounds": []}, True),
        ({"prompts": [], "rounds": [{"n": 1}]}, True),
    ],
)
def test_only_a_room_holding_nothing_is_a_throwaway_one(
    room: dict[str, Any], refused: bool
) -> None:
    assert (_load().refusal(room) is not None) is refused


def test_a_token_file_others_can_read_is_refused(tmp_path: Path) -> None:
    tool = _load()
    token = tmp_path / "token"
    token.write_text("abc\n")
    token.chmod(0o600)
    assert tool.read_token(token) == "abc"
    token.chmod(0o644)
    with pytest.raises(ValueError, match="readable by others"):
        tool.read_token(token)
    token.chmod(0o600)
    token.write_text("\n")
    with pytest.raises(ValueError, match="empty"):
        tool.read_token(token)


def test_the_verdict_plan_mixes_pass_and_fail_and_the_expected_split_adds_up() -> None:
    tool = _load()
    plan = tool.verdicts(3, ["a", "b", "c", "d"])
    assert plan == [
        {"a": "pass", "b": "pass", "c": "fail", "d": "fail"},
        {"a": "pass", "b": "fail", "c": "pass", "d": "fail"},
        {"a": "fail", "b": "pass", "c": "pass", "d": "fail"},
    ]
    assert tool.expected_split(plan) == {
        "a": {"pass": 2, "fail": 1},
        "b": {"pass": 2, "fail": 1},
        "c": {"pass": 2, "fail": 1},
        "d": {"pass": 0, "fail": 3},
    }
    assert len(tool.verdicts(5, ["a", "b"])) == 5


def test_reasons_are_counted_across_notes_and_failures() -> None:
    tool = _load()
    assert tool.reason_count({"notes": [1, 2], "failures": [3]}) == 3
    assert tool.reason_count({"notes": None}) == 0


def test_a_snapshot_with_every_field_has_no_problems() -> None:
    assert _load().field_problems(snapshot(), "p1") == []


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"subjects": [{"id": "s1", "label": "Violet"}]}, "no model_label"),
        (
            {"answers": [{"prompt_id": "p1", "subject_id": "s1", "state": "done"}]},
            "no jev on a settled answer",
        ),
        (
            {
                "answers": [
                    {
                        "prompt_id": "p1",
                        "subject_id": "s1",
                        "state": "done",
                        "jev": {"replied": "yes", "confidence": 0.9},
                    }
                ]
            },
            "jev.replied is not a boolean",
        ),
        (
            {
                "divergence": [
                    {"prompt_id": "p1", "state": "done", "method": "lexical", "confidence": None}
                ]
            },
            "fell back to lexical",
        ),
        ({"divergence": []}, "divergence is not done"),
    ],
)
def test_each_missing_field_is_named(changes: dict[str, Any], named: str) -> None:
    problems = _load().field_problems(snapshot(**changes), "p1")
    assert any(named in problem for problem in problems)


def test_a_note_is_not_a_failure_and_a_failed_row_is() -> None:
    tool = _load()
    lines: list[str] = []
    report = tool.Report(lines.append)
    report.add("3 reasons", "NOTE", "the page shows none")
    report.check("1 cases", [], "fine")
    assert report.ok
    report.check("2 grading", ["attendee 1 never saw a card"], "fine")
    assert not report.ok
    assert lines == [
        "NOTE 3 reasons: the page shows none",
        "PASS 1 cases: fine",
        "FAIL 2 grading: attendee 1 never saw a card",
    ]


def test_it_will_not_run_without_writes_or_with_a_path_in_an_origin(tmp_path: Path) -> None:
    tool = _load()
    token = tmp_path / "token"
    token.write_text("abc")
    token.chmod(0o600)
    base = ["--public", "https://room.example", "--direct", "https://api.room.example"]
    with pytest.raises(SystemExit) as refused:
        tool.main([*base, "--token-file", str(token)])
    assert refused.value.code == 2
    with pytest.raises(SystemExit) as refused:
        tool.main(
            [
                "--public",
                "https://room.example/present",
                "--direct",
                "https://a.example",
                "--token-file",
                str(token),
                "--writes",
            ]
        )
    assert refused.value.code == 2
