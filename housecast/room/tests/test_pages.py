"""The room pages hold none of the retired subject names."""

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


# The room is graded against written commitments, so nothing an attendee or the
# recording can read ranks, scores or competes. /present keeps its own sorting aid.
COMPETITION = re.compile(
    r"\b(compete|competing|competition|competitive|competitor|win|wins|winner|winning|points|"
    r"leaderboard|scoreboard|rank|ranked|ranking|arcade)\b"
    r"|most split|splits most|split them",
    re.I,
)
ROOM_FACING = ("index.html", "screen.html", "views.js", "room.js")


def test_no_competition_copy_on_an_attendee_or_screen_surface() -> None:
    for name in ROOM_FACING:
        found = COMPETITION.search((PAGE / name).read_text(encoding="utf-8"))
        assert not found, f"{name}: {found.group(0)}"


def test_no_glyph_stands_in_for_a_logo() -> None:
    """A persona is its creature or only its name, so no page draws an emoji or shape for it."""
    for name in ("room.js", "views.js", "room.css", "index.html", "screen.html", "present.html"):
        assert "emblem" not in (PAGE / name).read_text(encoding="utf-8"), name
