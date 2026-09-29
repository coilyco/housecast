"""Load `subjects.json`: the consumer's whole contribution to a room."""

from __future__ import annotations

import json
from pathlib import Path

from housecast.room.models import ModelRefusedError, check_model_name


class SubjectsError(ValueError):
    """A subjects file the room cannot run."""


def load_subjects(path: Path) -> list[dict[str, str]]:
    """Each subject is `{id, label, system}` or `{id, label, system_file}`, plus optional
    `color` and `emblem` for the page.

    `label` is what a room shows, so it is required and never derived from `id`.
    A `system_file` resolves against the subjects file's own directory.
    """
    raw = json.loads(path.read_text())
    entries = raw["subjects"] if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or not entries:
        raise SubjectsError(f"{path}: no subjects")
    subjects: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        sid, label = str(entry.get("id", "")).strip(), str(entry.get("label", "")).strip()
        if not sid or not label:
            raise SubjectsError(f"{path}: every subject needs an id and a label")
        if sid in seen:
            raise SubjectsError(f"{path}: duplicate subject id {sid!r}")
        seen.add(sid)
        if "system" in entry:
            system = str(entry["system"])
        elif "system_file" in entry:
            system = (path.parent / str(entry["system_file"])).read_text()
        else:
            raise SubjectsError(f"{path}: subject {sid!r} has no system prompt")
        subject = {"id": sid, "label": label, "system": system}
        # Display-only fields pass through untouched: the page owns what they mean.
        for extra in ("color", "emblem"):
            if entry.get(extra):
                subject[extra] = str(entry[extra])
        subjects.append(subject)
        if "model" in entry:  # optional route for this subject, never shown. docs/room.md
            subject["model"] = _model_of(entry["model"], f"{path}: subject {sid!r}")
    return subjects


def _model_of(model: object, where: str) -> str:
    if not isinstance(model, str) or not model.strip():
        raise SubjectsError(f"{where} has a model that is not a name")
    try:
        return check_model_name(model.strip(), where)
    except ModelRefusedError as refused:
        raise SubjectsError(str(refused)) from refused
