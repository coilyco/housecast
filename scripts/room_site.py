"""Export the room pages as a static site for S3 and CloudFront.

The pages call the API relative (`api/room`), so the site is same-origin: the
distribution serves these files and forwards `/api/*` to the room server.
docs/room-site.md.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "housecast/room/page"
# Each route becomes a directory index, which is what the project-sites
# viewer function rewrites an extensionless path to.
ROUTES = {
    "index.html": "index.html",
    "screen.html": "screen/index.html",
    "present.html": "present/index.html",
}
ASSETS = ("room.css", "room.js", "views.js")
# Subjects name their logo as `creatures/<slug>.png`, so it ships beside the pages.
LOGOS = "creatures"
BASE = '<base href="/">'

NOT_FOUND = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not part of the room</title>
<link rel="icon" href="data:,">
<base href="/">
<link rel="stylesheet" href="room.css">
</head>
<body>
<main class="wrap" id="main">
<h1>This page isn't part of the room</h1>
<p><a href="/">Go to the room</a></p>
</main>
</body>
</html>
"""


def pin_base(html: str) -> str:
    """Resolve every relative URL from the root, so /screen/ works like /screen."""
    if BASE in html:
        return html
    head = html.index("<head>") + len("<head>")
    return html[:head] + "\n" + BASE + html[head:]


def export(out: Path) -> list[Path]:
    if out.exists():
        shutil.rmtree(out)
    written = []
    for source, target in ROUTES.items():
        dest = out / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(pin_base((PAGE / source).read_text(encoding="utf-8")), encoding="utf-8")
        written.append(dest)
    for name in ASSETS:
        shutil.copyfile(PAGE / name, out / name)
        written.append(out / name)
    for logo in sorted((PAGE / LOGOS).glob("*.png")):
        dest = out / LOGOS / logo.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(logo, dest)
        written.append(dest)
    (out / "404.html").write_text(NOT_FOUND, encoding="utf-8")
    written.append(out / "404.html")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the room pages as a static site.")
    parser.add_argument("out", nargs="?", default="dist/room-site", type=Path)
    args = parser.parse_args(argv)
    for path in export(args.out):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
