"""Load `subjects.json`: the consumer's whole contribution to a room."""

from __future__ import annotations

import json
from pathlib import Path

from housecast.room.models import ModelRefusedError, check_model_name


class SubjectsError(ValueError):
    """A subjects file the room cannot run."""


def load_subjects(path: Path) -> list[dict[str, str]]:
    """Each subject is `{id, label, system}` or `{id, label, system_file}`, plus optional
    `color`, `emblem`, `logo`, `role`, and `line` for the page, and `model_label`, the
    provider's name for the model, which is the only model text a snapshot carries.

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
        for extra in ("color", "emblem", "logo", "role", "line"):
            if entry.get(extra):
                subject[extra] = str(entry[extra])
        subjects.append(subject)
        if "model" in entry:  # optional route for this subject, never shown. docs/room.md
            subject["model"] = _model_of(entry["model"], f"{path}: subject {sid!r}")
        if entry.get("model_label"):  # the one model text a page may show. docs/room-models.md
            subject["model_label"] = _label_of(entry["model_label"], f"{path}: subject {sid!r}")
    return subjects


MAX_MODEL_LABEL = 60


def _label_of(label: object, where: str) -> str:
    """A provider's name for the model, in words. A route id is `family/name`, so no slash."""
    text = label.strip() if isinstance(label, str) else ""
    if not text or len(text) > MAX_MODEL_LABEL or any(c in text for c in "/<>\n\r\t"):
        raise SubjectsError(
            f"{where} has a model_label that is not a plain name of at most "
            f"{MAX_MODEL_LABEL} characters with no slash"
        )
    return text


def _model_of(model: object, where: str) -> str:
    if not isinstance(model, str) or not model.strip():
        raise SubjectsError(f"{where} has a model that is not a name")
    try:
        return check_model_name(model.strip(), where)
    except ModelRefusedError as refused:
        raise SubjectsError(str(refused)) from refused
