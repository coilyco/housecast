"""Run one full grading round on a room's real stack, and say PASS or FAIL per step.

Writes to the room's log, so use a throwaway log. It refuses a room that holds a case.
Presenter moves use the direct origin and a control token read from a 0600 file, never
printed. Attendees and the shared screen use the public origin. Two cases make real model
calls. Screenshots land in --out. `--help` names the steps. docs/ is at its cap.
"""

from __future__ import annotations

import argparse
import stat
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import APIRequestContext, Page

LEGEND = """\
Steps, in order:
  0 same room    the direct and public origins report the same rev, and the room holds no case
  1 cases        two prepared cases (one of about 1500 characters over several lines) get an
                 answer from every persona and a divergence, then the first is picked into grading
  2 grading      three attendee browsers see the case and every answer, grade each with a mix of
                 PASS and FAIL plus a reason on each FAIL (the page offers none on PASS), and
                 each card says Saved
  3 split        the split opens, its tallies match what the attendees clicked, and the snapshot
                 carries jev.replied and confidence, divergence.confidence and model_label. Whether
                 the attendee page shows the reasons is a NOTE, since older pages may not
  4 kill switch  reasons off empties notes and failures in the attendee snapshot, on restores them
  5 next case    the cases a download would hold are the two added, in order, and picking next
                 puts the second case in front of an attendee
"""

TIMEOUT = 180
# One row per attendee, one letter per persona in snapshot order: p is PASS, f is FAIL.
PLAN = ("ppff", "pfpf", "fppf")
TERMINAL = {"done", "failed", "empty"}


def case_text(target: int = 1500) -> str:
    """A multi-line case of at most `target` characters: context lines, then the question."""
    question = "Question: may the nurse skip the confirmation when the assistant is over 95% sure?"
    lines = ["Context: a regional clinic runs a triage assistant overnight."]
    while True:
        note = (
            f"Note {len(lines)}: the assistant reads the intake form, proposes a priority from 1"
            " to 4, and a nurse confirms or overrides the proposal within ten minutes."
        )
        if len("\n".join([*lines, note, question])) > target:
            return "\n".join([*lines, question])
        lines.append(note)


def refusal(room: dict[str, Any]) -> str | None:
    """Why this room is not a throwaway one, or None when it holds nothing yet."""
    if room.get("prompts") or room.get("rounds"):
        return (
            f"the room already holds {len(room.get('prompts', []))} case(s) and"
            f" {len(room.get('rounds', []))} round(s). Restart it onto a throwaway log first"
        )
    return None


def read_token(path: Path) -> str:
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError(f"{path} is readable by others: chmod 600 it before use")
    token = path.read_text().strip()
    if not token:
        raise ValueError(f"{path} is empty")
    return token


def verdicts(attendees: int, subject_ids: list[str]) -> list[dict[str, str]]:
    """What each attendee clicks, by persona: PASS or FAIL, in a fixed mix."""
    rows = []
    for index in range(attendees):
        letters = PLAN[index % len(PLAN)]
        rows.append(
            {
                sid: "pass" if letters[at % len(letters)] == "p" else "fail"
                for at, sid in enumerate(subject_ids)
            }
        )
    return rows


def expected_split(plan: list[dict[str, str]]) -> dict[str, dict[str, int]]:
    tally: dict[str, dict[str, int]] = {}
    for row in plan:
        for sid, verdict in row.items():
            tally.setdefault(sid, {"pass": 0, "fail": 0})[verdict] += 1
    return tally


def reason_count(snapshot: dict[str, Any]) -> int:
    return len(snapshot.get("notes") or []) + len(snapshot.get("failures") or [])


def field_problems(snapshot: dict[str, Any], prompt_id: str) -> list[str]:
    """What the public snapshot lacks of the fields the pages read, for one prompt."""
    problems = []
    for subject in snapshot.get("subjects", []):
        if not subject.get("model_label"):
            problems.append(f"subject {subject.get('id')} has no model_label")
    for answer in snapshot.get("answers", []):
        if answer["prompt_id"] != prompt_id:
            continue
        who = answer["subject_id"]
        jev = answer.get("jev")
        if answer["state"] == "done" and not isinstance(jev, dict):
            problems.append(f"{who}: no jev on a settled answer")
        elif isinstance(jev, dict):
            if not isinstance(jev.get("replied"), bool):
                problems.append(f"{who}: jev.replied is not a boolean")
            if not isinstance(jev.get("confidence"), int | float):
                problems.append(f"{who}: jev.confidence is not a number")
    scored = [d for d in snapshot.get("divergence", []) if d["prompt_id"] == prompt_id]
    if not scored or scored[0].get("state") != "done":
        problems.append("the divergence is not done")
    elif scored[0].get("method") != "stance" or scored[0].get("confidence") is None:
        problems.append(
            f"divergence fell back to {scored[0].get('method')} with confidence"
            f" {scored[0].get('confidence')}, so Jev did not score it"
        )
    return problems


class Report:
    """Rows as they land, so a long run shows progress. NOTE is information, never a failure."""

    def __init__(self, emit: Callable[[str], None] = print) -> None:
        self.rows: list[tuple[str, str, str]] = []
        self.emit = emit

    def add(self, step: str, status: str, detail: str) -> None:
        self.rows.append((step, status, detail))
        self.emit(f"{status} {step}: {detail}")

    def check(self, step: str, problems: list[str], good: str) -> None:
        self.add(step, "FAIL" if problems else "PASS", "; ".join(problems) or good)

    @property
    def ok(self) -> bool:
        return all(status != "FAIL" for _, status, _ in self.rows)


def poll(test: Callable[[], bool], seconds: float = 20.0, every: float = 0.5) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if test():
            return True
        time.sleep(every)
    return test()


class Room:
    """The presenter's view through the direct origin, the attendee view through the public one."""

    def __init__(self, direct: APIRequestContext, public: APIRequestContext, token: str) -> None:
        self.direct, self.public, self.token = direct, public, token

    def control(self, path: str, body: dict[str, Any]) -> Any:
        reply = self.direct.post(path, data=body, headers={"x-control-token": self.token})
        if not reply.ok:
            raise RuntimeError(f"{path} refused: {reply.status} {reply.text()[:200]}")
        return reply.json()

    def presenter(self) -> dict[str, Any]:
        reply = self.direct.get("api/control/room", headers={"x-control-token": self.token})
        if not reply.ok:
            raise RuntimeError(f"api/control/room refused: {reply.status}")
        return dict(reply.json())

    def attendee(self) -> dict[str, Any]:
        return dict(self.public.get("api/room").json())


def settled(room: Room, ids: list[str], subjects: int) -> bool:
    snapshot = room.presenter()
    for prompt_id in ids:
        mine = [a for a in snapshot["answers"] if a["prompt_id"] == prompt_id]
        if len(mine) < subjects or any(a["state"] not in TERMINAL for a in mine):
            return False
        if any(a["state"] == "done" and "jev" not in a for a in mine):
            return False
        if not any(
            d["prompt_id"] == prompt_id and d["state"] in {"done", "failed"}
            for d in snapshot["divergence"]
        ):
            return False
    return True


def run(
    pw: Any, public: str, direct: str, token: str, out: Path, attendees: int, report: Report
) -> None:
    direct_api = pw.request.new_context(base_url=direct)
    public_api = pw.request.new_context(base_url=public)
    room = Room(direct_api, public_api, token)

    # 0. The two origins are one room, and it is a throwaway one.
    seen, heard = room.presenter(), room.attendee()
    problems = []
    if seen["rev"] != heard["rev"]:
        problems.append(f"direct rev {seen['rev']} but public rev {heard['rev']}")
    if why := refusal(seen):
        problems.append(why)
    report.check("0 same room", problems, f"rev {seen['rev']} on both, no case yet")
    if problems:
        return
    subjects = [s["id"] for s in seen["subjects"]]
    labels = {s["id"]: s["label"] for s in seen["subjects"]}
    initial_reasons = bool(seen.get("reasons_visible", True))

    # 1. Two prepared cases answer for real, and the first is picked.
    long_case = case_text()
    cases = [
        {"text": long_case, "commitment": "An agent says what it does not know"},
        {"text": "Should a small town ban cars from its main street?", "commitment": ""},
    ]
    ids = [room.control("api/control/cases", case)["id"] for case in cases]
    answered = poll(lambda: settled(room, ids, len(subjects)), TIMEOUT, 2)
    snapshot = room.presenter()
    states = {
        (a["prompt_id"], a["subject_id"]): a["state"]
        for a in snapshot["answers"]
        if a["prompt_id"] in ids
    }
    bad = [
        f"{labels[s]} on case {ids.index(p) + 1} is {v}"
        for (p, s), v in states.items()
        if v != "done"
    ]
    problems = ([] if answered else [f"not settled after {TIMEOUT}s"]) + bad
    report.check(
        "1 cases",
        problems,
        f"{len(long_case)} and {len(cases[1]['text'])} characters, all answered",
    )
    room.control("api/control/pick", {"prompt_id": ids[0]})
    snapshot = room.presenter()
    report.check(
        "1 pick",
        []
        if snapshot["phase"] == "grading" and snapshot["round"]["prompt_id"] == ids[0]
        else [f"phase {snapshot['phase']}, round {snapshot.get('round')}"],
        "the long case is in grading",
    )

    # 2. Attendees grade in their own browsers.
    plan = verdicts(attendees, subjects)
    browser = pw.chromium.launch()
    pages: list[Page] = []
    problems = []
    for index, choices in enumerate(plan):
        context = browser.new_context(base_url=public, viewport={"width": 390, "height": 844})
        page = context.new_page()
        pages.append(page)
        page.goto("/")
        try:
            page.locator("button[data-verdict]").first.wait_for(timeout=30000)
        except Exception:
            problems.append(f"attendee {index + 1} never saw a card")
            continue
        seen_text = page.locator("body").inner_text()
        if long_case.splitlines()[-1] not in seen_text:
            problems.append(f"attendee {index + 1} does not see the case question")
        cards = page.locator('button[data-verdict="pass"]').count()
        if cards != len(subjects):
            problems.append(f"attendee {index + 1} sees {cards} answers, not {len(subjects)}")
        for sid, verdict in choices.items():
            page.locator(f'button[data-subject="{sid}"][data-verdict="{verdict}"]').click()
            if verdict == "fail":  # the page offers a reason box on FAIL only
                page.locator(f'textarea[data-reason="{sid}"]').fill(
                    f"e2e attendee {index + 1} fail on {labels[sid]}"
                )
        page.wait_for_timeout(2500)
        if not poll(lambda p=page: p.get_by_text("Saved.", exact=False).count() >= len(subjects)):
            problems.append(f"attendee {index + 1} did not reach Saved on every card")
    graded = room.presenter()["round"]["graded"]
    if graded != attendees:
        problems.append(f"the room counts {graded} graders, not {attendees}")
    out.mkdir(parents=True, exist_ok=True)
    if pages:
        pages[0].screenshot(path=str(out / "attendee-grading.png"), full_page=True)
    screen = browser.new_context(
        viewport={"width": 1280, "height": 720}, base_url=public
    ).new_page()
    screen.goto("screen")
    screen.wait_for_timeout(2500)
    screen.screenshot(path=str(out / "screen-grading.png"), full_page=True)
    report.check(
        "2 grading", problems, f"{attendees} attendees graded {len(subjects)} answers each"
    )

    # 3. The split, the tallies and the fields.
    room.control("api/control/phase", {"phase": "split"})
    stuck = []
    for index, page in enumerate(pages):
        try:
            page.locator(".tally__counts, .split__share").first.wait_for(timeout=30000)
        except Exception:
            stuck.append(f"attendee {index + 1} never saw results after the split")
    heard = room.attendee()
    round_n = heard["round"]["n"]
    got = next(r["split"] for r in heard["rounds"] if r["n"] == round_n)
    want = expected_split(plan)
    problems = [
        f"{labels[s]} is {got[s]['pass']} PASS {got[s]['fail']} FAIL, clicked {want[s]['pass']}"
        f" PASS {want[s]['fail']} FAIL"
        for s in subjects
        if got[s]["pass"] != want[s]["pass"] or got[s]["fail"] != want[s]["fail"]
    ]
    report.check(
        "3 split",
        problems + stuck,
        "tallies match the clicks: "
        + ", ".join(f"{labels[s]} {want[s]['pass']}/{want[s]['fail']}" for s in subjects),
    )
    report.check(
        "3 fields",
        field_problems(heard, ids[0]),
        "jev.replied and confidence, divergence.confidence and model_label are present",
    )
    typed = sum(v == "fail" for row in plan for v in row.values())
    carried = reason_count(heard)
    shown = pages[0].locator("ul.reasons li").count() if pages else 0
    report.add(
        "3 reasons",
        "NOTE",
        f"the snapshot carries {carried} reasons ({typed} typed), the page"
        + (f" shows {shown}" if shown else " does not render any on results"),
    )
    if pages:
        measure = pages[0].locator(".measure")
        jev_line = " ".join(measure.first.inner_text().split()) if measure.count() else ""
        report.add(
            "3 jev line", "NOTE", f"the attendee page reads: {jev_line or 'no Jev line on results'}"
        )
        pages[0].screenshot(path=str(out / "attendee-results.png"), full_page=True)
    screen.wait_for_timeout(2500)
    screen.screenshot(path=str(out / "screen-results.png"), full_page=True)

    # 4. The reasons kill switch.
    problems = []
    room.control("api/control/reasons", {"visible": False})
    if not poll(lambda: reason_count(room.attendee()) == 0):
        problems.append("reasons off still leaves reasons in the attendee snapshot")
    room.control("api/control/reasons", {"visible": True})
    if not poll(lambda: reason_count(room.attendee()) == typed):
        problems.append(f"reasons on does not bring back all {typed}")
    room.control("api/control/reasons", {"visible": initial_reasons})
    report.check("4 kill switch", problems, f"off hides all {typed}, on shows all {typed}")

    # 5. Download, then pick the next case.
    snapshot = room.presenter()
    held = [
        {"text": p["text"], "commitment": p.get("commitment") or ""}
        for p in sorted(snapshot["prompts"], key=lambda p: p["seq"])
        if p.get("text")
    ]
    wanted = [{"text": c["text"], "commitment": c["commitment"]} for c in cases]
    report.check(
        "5 download",
        [] if held == wanted else [f"holds {len(held)} cases, not the two added, in order"],
        "the cases a download would hold are the two added, in order",
    )
    room.control("api/control/pick", {"prompt_id": ids[1]})
    problems = []
    if pages:
        try:
            pages[0].get_by_text(cases[1]["text"]).first.wait_for(timeout=30000)
            pages[0].locator("button[data-verdict]").first.wait_for(timeout=30000)
        except Exception:
            problems.append("the attendee never saw the second case")
        cards = pages[0].locator('button[data-verdict="pass"]').count()
        if cards != len(subjects):
            problems.append(f"the second case shows {cards} answers, not {len(subjects)}")
        pages[0].screenshot(path=str(out / "attendee-second-case.png"), full_page=True)
    report.check("5 pick next", problems, "the second case is in front of an attendee, all answers")
    room.control("api/control/phase", {"phase": "holding"})
    browser.close()


def origin(parser: argparse.ArgumentParser, flag: str, value: str) -> str:
    from urllib.parse import urlsplit

    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path not in {"", "/"}:
        parser.error(f"{flag} is an http or https origin with no path")
    return f"{parts.scheme}://{parts.netloc}/"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0],
        epilog=LEGEND,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--public", required=True, help="attendee origin, e.g. https://room.example"
    )
    parser.add_argument("--direct", required=True, help="presenter API origin, token-gated")
    parser.add_argument("--token-file", type=Path, required=True, help="a 0600 file with the token")
    parser.add_argument("--out", type=Path, default=Path("dist/room-e2e"), help="screenshots")
    parser.add_argument("--attendees", type=int, default=3, help="attendee browsers")
    parser.add_argument(
        "--writes", action="store_true", help="confirm this room is on a throwaway log"
    )
    args = parser.parse_args(argv)
    if not args.writes:
        parser.error(
            "this adds cases and grades them, so pass --writes, and only on a throwaway log"
        )
    if args.attendees < 1:
        parser.error("--attendees is at least 1")
    try:
        token = read_token(args.token_file)
    except (OSError, ValueError) as err:
        parser.error(str(err))
    public, direct = (
        origin(parser, "--public", args.public),
        origin(parser, "--direct", args.direct),
    )

    from playwright.sync_api import sync_playwright

    report = Report(lambda line: print(line, flush=True))
    with sync_playwright() as pw:
        try:
            run(pw, public, direct, token, args.out, args.attendees, report)
        except Exception as failed:  # a crashed step is a failed row, not a stopped run
            report.add("run", "FAIL", (str(failed).splitlines() or [type(failed).__name__])[0])
    print(f"screenshots in {args.out.resolve()}", flush=True)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
