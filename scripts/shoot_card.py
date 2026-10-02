"""Screenshot one card of a sealed board, cropped to the page header plus the card.

Opens the `grade seal` output from a file path with every hostname failing, so
the capture proves the board renders a committed run with no network and no
model call, and exits non-zero if the page asked for anything outside itself.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

# The capture starts at scroll 0 on purpose: scrolling the card into view parks
# the sticky site bar over the card's own pair header and hides the verdict.
CROP = """() => {
  scrollTo(0, 0);
  const unit = document.querySelector('article.unit');
  return {
    width: document.documentElement.clientWidth,
    bottom: unit.getBoundingClientRect().bottom + scrollY,
    header: unit.querySelector('.unit-h')?.innerText.replace(/\\s+/g, ' '),
    cases: [...unit.querySelectorAll('.case-id')].map(e => e.innerText),
  };
}"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=pathlib.Path, help="a sealed board .html")
    parser.add_argument("--out", type=pathlib.Path, required=True, help="the .png to write")
    parser.add_argument("--width", type=int, default=1400, help="viewport width in CSS px")
    parser.add_argument("--card", default="1", help="the ?card= position to open")
    parser.add_argument("--scale", type=float, default=2, help="device scale factor")
    args = parser.parse_args()

    outside: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--host-resolver-rules=MAP * ~NOTFOUND"])
        page = browser.new_page(
            viewport={"width": args.width, "height": 900}, device_scale_factor=args.scale
        )
        page.on(
            "request",
            lambda request: outside.append(request.url)
            if not request.url.startswith(("file:", "data:"))
            else None,
        )
        page.goto(f"{args.board.resolve().as_uri()}?card={args.card}")
        page.wait_for_timeout(800)
        box = page.evaluate(CROP)
        page.screenshot(
            path=str(args.out),
            full_page=True,
            clip={"x": 0, "y": 0, "width": box["width"], "height": box["bottom"] + 16},
        )
        browser.close()

    print(json.dumps({"out": str(args.out), "width": args.width, "card": args.card,
                      "header": box["header"], "cases": box["cases"],
                      "external_requests": outside}))
    return 1 if outside else 0


if __name__ == "__main__":
    sys.exit(main())
