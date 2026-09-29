"""The room pages take a subject's look from subjects.json, never from their own source."""

from __future__ import annotations

import re
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "page"
# The session deck's first names, retired for each seat's own creature name.
RETIRED_NAMES = re.compile(r"\b(Evie|Delphi|Sprite|Gem)\b")
# A demo row: ["Label", "#colour", "slug", ...]. The slug builds `creatures/<slug>.png`.
DEMO_ROW = re.compile(r'\["[\w-]+", "#[0-9a-f]{6}", "([\w-]+)"')


def test_no_page_bakes_in_a_subject_name() -> None:
    for path in PAGE.iterdir():
        if path.suffix in {".html", ".js", ".css"}:
            assert not RETIRED_NAMES.search(path.read_text(encoding="utf-8")), path.name


def test_every_logo_the_demo_names_exists() -> None:
    slugs = DEMO_ROW.findall((PAGE / "room.js").read_text(encoding="utf-8"))
    assert len(slugs) == 4
    for slug in slugs:
        assert (PAGE / "creatures" / f"{slug}.png").is_file(), slug
