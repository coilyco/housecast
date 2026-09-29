"""Walk the room's phone checklist in a real browser engine against one room.

It submits a prompt and grades a round, so it writes to that room's log: run it
against a dev or rehearsal room, never the live one. The presenter's moves go
through the control API with the room's token. Step 4 (lock the phone) needs a
real device and is left to the phone checklist. docs/room-site.md.

    just room-engine-pass --base https://room.example --token-file /path/token --writes
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import APIRequestContext, Page, Playwright, sync_playwright

# Emulated phones where the engine supports it. Firefox has no mobile mode.
DEVICES = {"webkit": "iPhone 13", "chromium": "Pixel 7"}


class Pass:
    def __init__(self, browser: str, out: Path) -> None:
        self.browser, self.out, self.rows = browser, out, []

    def step(self, name: str, ok: bool, detail: str, page: Page | None = None) -> None:
        self.rows.append((self.browser, name, "PASS" if ok else "FAIL", detail))
        if page is not None:
            page.screenshot(path=str(self.out / f"{self.browser}-{name}.png"), full_page=True)


def control(api: APIRequestContext, token: str, path: str, body: dict[str, Any]) -> Any:
    reply = api.post(path, data=body, headers={"x-control-token": token})
    if not reply.ok:
        raise RuntimeError(f"{path} refused: {reply.status} {reply.text()}")
    return reply.json()


def wait_answered(api: APIRequestContext, token: str, prompt_id: str, n: int) -> bool:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        room = api.get("api/control/room", headers={"x-control-token": token}).json()
        done = [
            a for a in room["answers"] if a["prompt_id"] == prompt_id and a["state"] != "running"
        ]
        if len(done) >= n:
            return True
        time.sleep(2)
    return False


def no_sideways_scroll(page: Page) -> bool:
    return bool(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))


def run(pw: Playwright, name: str, base: str, token: str, out: Path) -> Pass:
    result = Pass(name, out)
    engine = getattr(pw, name)
    browser = engine.launch()
    options = (
        dict(pw.devices[DEVICES[name]])
        if name in DEVICES
        else {"viewport": {"width": 390, "height": 844}}
    )
    context = browser.new_context(base_url=base, **options)
    api = pw.request.new_context(base_url=base)
    page = context.new_page()
    subjects = [s["label"] for s in api.get("api/room").json()["subjects"]]

    control(api, token, "api/control/phase", {"phase": "holding"})
    page.goto("/")
    page.get_by_text("Waiting on the presenter").wait_for(timeout=15000)
    cast = page.locator("#holding-cast").inner_text()
    named = all(label in cast for label in subjects)
    upright = no_sideways_scroll(page)
    size = page.viewport_size or {"width": 390, "height": 844}
    page.set_viewport_size({"width": size["height"], "height": size["width"]})
    turned = no_sideways_scroll(page)
    page.set_viewport_size(size)
    result.step(
        "1-holding",
        named and upright and turned,
        f"names {named}, upright {upright}, turned {turned}",
        page,
    )

    page.evaluate("window.__noReload = true")
    control(api, token, "api/control/phase", {"phase": "submissions"})
    box = page.locator("#submit-text")
    box.wait_for(timeout=15000)
    first = f"Engine pass {name} {int(time.time())}: may a hospital let an AI triage patients?"
    commitment = "An agent says what it does not know"
    box.fill(first)
    page.locator("#submit-commitment").fill(commitment)
    counted = page.get_by_text(f"{len(first)} / 280").count() > 0
    page.locator("#submit-send").click()
    page.get_by_text("Proposed.", exact=False).wait_for(timeout=15000)
    second = "And should it explain itself to the patient?"
    box.fill(second)
    page.locator("#submit-commitment").fill(commitment)
    page.locator("#submit-send").click()
    page.wait_for_timeout(1500)
    refused = page.locator('[data-tone="error"]').count() > 0
    kept = box.input_value() == second
    live = bool(page.evaluate("window.__noReload === true"))
    result.step(
        "2-submit",
        counted and refused and kept and live,
        f"counter {counted}, refusal {refused}, kept {kept}, no reload {live}",
        page,
    )

    prompt_id = next(
        p["id"]
        for p in api.get("api/control/room", headers={"x-control-token": token}).json()["prompts"]
        if p["text"] == first
    )
    answered = wait_answered(api, token, prompt_id, len(subjects))
    control(api, token, "api/control/pick", {"prompt_id": prompt_id})
    verdicts = page.locator("button[data-verdict]")
    verdicts.first.wait_for(timeout=20000)
    page.locator('button[data-verdict="pass"]').nth(0).click()
    page.locator('button[data-verdict="fail"]').nth(1).click()
    page.locator("textarea[data-reason]").first.fill("Hedged when asked for a position.")
    page.wait_for_timeout(2500)
    saved = page.get_by_text("Saved.", exact=False).count() >= 2
    zoomed = bool(page.evaluate("(visualViewport?.scale ?? 1) > 1.01"))
    result.step(
        "3-grade",
        answered and saved and not zoomed,
        f"answered {answered}, saved {saved}, zoomed {zoomed}",
        page,
    )

    control(api, token, "api/control/phase", {"phase": "split"})
    page.locator(".split__share").first.wait_for(timeout=15000)
    shares = page.locator(".split__share").all_inner_texts()
    # A subject nobody graded shows a dash rather than a share.
    bars = len(shares) == len(subjects) and all(s.endswith("%") or s == "\u2013" for s in shares)
    result.step("5-split", bars, f"shares {shares}", page)

    control(api, token, "api/control/phase", {"phase": "holding"})
    browser.close()
    return result


def load_token(parser: argparse.ArgumentParser, args: argparse.Namespace) -> str:
    if args.token_file:
        if stat.S_IMODE(args.token_file.stat().st_mode) & 0o077:
            parser.error(f"{args.token_file} is readable by others: chmod 600 it before use")
        token = args.token_file.read_text().strip()
    else:
        token = args.token or os.environ.get("ROOM_CONTROL_TOKEN", "")
    if not token:
        parser.error("no control token: pass --token-file, --token, or set ROOM_CONTROL_TOKEN")
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Walk the room's phone checklist in browser engines."
    )
    parser.add_argument("--base", required=True, help="the room's origin, ending in /")
    parser.add_argument("--token", help="the control token. Prefer --token-file: argv is visible")
    parser.add_argument("--token-file", type=Path, help="a 0600 file holding the control token")
    parser.add_argument("--browser", action="append", choices=("chromium", "firefox", "webkit"))
    parser.add_argument("--out", type=Path, default=Path("dist/room-engine-pass"))
    parser.add_argument(
        "--writes", action="store_true", help="confirm this room's log may take test prompts"
    )
    args = parser.parse_args(argv)
    args.token = load_token(parser, args)
    if not args.writes:
        parser.error(
            "this submits and grades, so pass --writes, and only against a dev or rehearsal room"
        )
    args.out.mkdir(parents=True, exist_ok=True)
    base = args.base if args.base.endswith("/") else args.base + "/"
    rows = []
    with sync_playwright() as pw:
        for name in args.browser or ["firefox", "webkit"]:
            try:
                rows += run(pw, name, base, args.token, args.out).rows
            except Exception as failed:  # a crashed engine is a failed row, not a stopped run
                rows.append((name, "run", "FAIL", str(failed).splitlines()[0]))
    for row in rows:
        print(" | ".join(row))
    return 0 if all(r[2] == "PASS" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
