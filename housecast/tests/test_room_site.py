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


def test_every_logo_a_page_can_name_is_exported(tmp_path: Path) -> None:
    """A subject's logo is a relative path, so a file left out is a broken image on the screen."""
    site = _load()
    site.export(tmp_path)
    shipped = sorted(p.name for p in (site.PAGE / "creatures").glob("*.png"))
    assert shipped
    assert sorted(p.name for p in (tmp_path / "creatures").glob("*.png")) == shipped


def test_the_split_keeps_the_presenter_off_the_public_site(tmp_path: Path) -> None:
    """The public host serves the attendee page and the recording screen, and no /present."""
    site = _load()
    site.export(tmp_path / "public", "public")
    site.export(tmp_path / "gated", "gated")
    public = sorted(
        p.relative_to(tmp_path / "public").as_posix()
        for p in (tmp_path / "public").rglob("*")
        if p.is_file()
    )
    assert "index.html" in public and "screen/index.html" in public and "404.html" in public
    assert not any(name.startswith("present") for name in public)
    assert "present/index.html" in sorted(
        p.relative_to(tmp_path / "gated").as_posix()
        for p in (tmp_path / "gated").rglob("*")
        if p.is_file()
    )
    # The gated root is the presenter page too, so its bare address works.
    assert (tmp_path / "gated" / "index.html").read_text(encoding="utf-8") == (
        tmp_path / "gated" / "present" / "index.html"
    ).read_text(encoding="utf-8")
    # Each directory carries the shared files its pages load.
    for root in ("public", "gated"):
        for shared in ("room.css", "room.js", "views.js", "404.html"):
            assert (tmp_path / root / shared).is_file(), (root, shared)


def test_split_writes_both_directories(tmp_path: Path) -> None:
    assert _load().main([str(tmp_path / "out"), "--split"]) == 0
    assert (tmp_path / "out" / "public" / "screen" / "index.html").is_file()
    assert (tmp_path / "out" / "gated" / "present" / "index.html").is_file()
