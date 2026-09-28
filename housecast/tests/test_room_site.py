"""The static room export, which S3 and CloudFront serve in front of the room server."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "room_site.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("room_site", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_route_is_a_directory_index(tmp_path: Path) -> None:
    """The viewer function rewrites /screen to /screen/index.html, so that is where it must be."""
    _load().export(tmp_path)
    for rel in (
        "index.html",
        "screen/index.html",
        "present/index.html",
        "404.html",
        "room.css",
        "room.js",
        "views.js",
    ):
        assert (tmp_path / rel).is_file(), rel


def test_every_page_resolves_from_the_root(tmp_path: Path) -> None:
    """Without the base, /screen/ with a trailing slash would ask for /screen/api/room."""
    _load().export(tmp_path)
    for page in ("index.html", "screen/index.html", "present/index.html", "404.html"):
        html = (tmp_path / page).read_text(encoding="utf-8")
        assert html.count('<base href="/">') == 1, page
        assert html.index('<base href="/">') < html.index("room.css"), page


def test_the_pages_stay_same_origin(tmp_path: Path) -> None:
    """An absolute API URL would break the /api/* forward the distribution relies on."""
    _load().export(tmp_path)
    for path in tmp_path.rglob("*"):
        if path.suffix in {".html", ".js"}:
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"""["'`]https?://[^"'`]*/api/""", text), path
            assert not re.search(r"""["'`]/api/""", text), path


def test_a_second_export_replaces_the_first(tmp_path: Path) -> None:
    """A stale file left in the build would be synced to the bucket."""
    stale = tmp_path / "stale.html"
    tmp_path.mkdir(exist_ok=True)
    stale.write_text("old", encoding="utf-8")
    _load().export(tmp_path)
    assert not stale.exists()
