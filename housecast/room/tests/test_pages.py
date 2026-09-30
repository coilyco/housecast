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


def test_earlier_cases_can_only_read() -> None:
    """A folded case is drawn from the sheet body with no controls, so it holds no grade button."""
    html = (PAGE / "index.html").read_text(encoding="utf-8")
    views = (PAGE / "views.js").read_text(encoding="utf-8")
    render = html[html.index("function render()") :]
    start = render.index('$("old-cases")')
    old = render[start : render.index("\n}\n", start)]
    assert "V.sheetBody(room, r, { now, reasons: true })" in old  # reasons, no controls
    assert "gradeControls" not in old and "data-verdict" not in old
    # Only the case being graded is handed the controls, and only while grading is open.
    assert "controls: live ? gradeControls : null" in render
    assert 'const live = phase === "grading" && top?.n === room.round.n;' in render
    body = views[views.index("function sheetBody") : views.index("/** A case as a sheet.")]
    assert "data-verdict" not in body


def test_the_tally_shows_only_once_the_results_are_open() -> None:
    """The room sees a count, never a direction, so a card's tally waits for the split."""
    views = (PAGE / "views.js").read_text(encoding="utf-8")
    body = views[views.index("function sheetBody") : views.index("/** A case as a sheet.")]
    assert "const cells = r.split ? splitFor(room, r.n) : null;" in body
    assert 'cell ? tallyHtml(cell) + said : ""' in body and "cell && reasons ? reasonsHtml(" in body


def test_no_run_status_reads_like_a_grade() -> None:
    """Humans grade. An answer that did not come back is "no answer", never FAIL or "failed"."""
    for name in ("views.js", "present.html", "screen.html", "index.html"):
        text = (PAGE / name).read_text(encoding="utf-8")
        assert "✕ failed" not in text and 'failed: "failed"' not in text, name


def test_a_slow_answer_is_never_called_slow_or_usual() -> None:
    """A slow route is normal, so no card claims a usual time or calls the wait a fault."""
    for name in ("views.js", "room.js"):
        text = (PAGE / name).read_text(encoding="utf-8")
        assert "slower than usual" not in text and "Usually about" not in text, name


# Kai's cover line, character for character: her 06:15 self-check compares it.
OPENING_LINE = (
    "I've setup an array of 4 agents with separate composed personas and model backends. "
    "We're going to be curating eval cases with the specific purpose of finding divergence "
    "and digging into what source text is causing it."
)


def test_the_screen_opens_on_kais_cover_line() -> None:
    html = (PAGE / "screen.html").read_text(encoding="utf-8")
    assert f'<p class="dim">{OPENING_LINE}</p>' in html


def test_the_machine_measurement_sits_under_the_case_and_is_not_a_grade() -> None:
    """Jev split shows once a divergence row exists, labelled a measurement, backup marked."""
    views = (PAGE / "views.js").read_text(encoding="utf-8")
    assert "Machine measurement, not a grade" in views
    assert "word overlap" in views and "Jev did not answer" in views
    assert "0 means the answers take the same stance" in views and "by stance" not in views
    body = views[views.index("function sheetBody") : views.index("/** A case as a sheet.")]
    assert "${measure(room, r.prompt_id)}" in body and "r.split ? measure(" not in body
    # The presenter reads it beside the four answers, before picking.
    present = (PAGE / "present.html").read_text(encoding="utf-8")
    assert 'V.setHtml($("detail-jev"), prompt ? V.measure(room, prompt.id) : "")' in present


# Kai has never used the word, so the phone and the recording carry none of it. What
# survives is a code identifier: `prompt.commitment`, or a `commitment:` key in demo data.
COMMITMENT_IDENTIFIER = re.compile(r"(\?\.|\.)commitment\b|\bcommitment(?=\s*[:,)\]])")
SURFACE_FILES = ("index.html", "screen.html", "views.js", "room.js")


def test_no_phone_or_screen_copy_says_commitment() -> None:
    for name in SURFACE_FILES:
        text = COMMITMENT_IDENTIFIER.sub("", (PAGE / name).read_text(encoding="utf-8"))
        assert "commitment" not in text.lower(), name


def test_no_rule_line_and_no_discussion_card_on_the_room_surfaces() -> None:
    """Kai sets the rule out loud and the room talks in Zoom chat."""
    for name in SURFACE_FILES:
        text = (PAGE / name).read_text(encoding="utf-8")
        for gone in ("RUBRIC", "talkCard", "talkFor", "Talk it through", "case-tests"):
            assert gone not in text, f"{name}: {gone}"
    assert 'id="talk"' not in (PAGE / "screen.html").read_text(encoding="utf-8")


def test_the_propose_form_is_behind_its_switch_and_asks_only_for_the_prompt() -> None:
    room_js = (PAGE / "room.js").read_text(encoding="utf-8")
    index = (PAGE / "index.html").read_text(encoding="utf-8")
    assert "const SHOW_PROPOSALS = false;" in room_js and "const SHOW_HINTS = false;" in room_js
    assert "phaseNow()" in index and 'name="commitment"' not in index
    assert 'postJson("api/prompts", { text, device: device() }' in index


def test_a_pasted_case_can_be_picked_from_holding_and_from_results() -> None:
    """Kai queues the next prompt while results show, so the pick cannot need submissions."""
    present = (PAGE / "present.html").read_text(encoding="utf-8")
    assert '["holding", "submissions", "split"].includes(room.phase)' in present


def test_a_pasted_prompt_shows_its_context_apart_from_its_question() -> None:
    """Context sits in its own scrolling box, so a long paste never pushes the results off."""
    views = (PAGE / "views.js").read_text(encoding="utf-8")
    css = (PAGE / "room.css").read_text(encoding="utf-8")
    assert "function splitPrompt(" in views and 'class="case__code"' in views
    assert ".case__text, #title { white-space: pre-wrap; }" in css
    # On /screen the results keep a smaller box, so Jev's measurement stays in the window.
    assert '.screen .sheets[data-phase="split"] .case__code { max-height: 20vh; }' in css


def test_the_attendee_page_is_one_casebook_column() -> None:
    """Newest case on top, earlier ones folded below, and no tab to a separate look-back."""
    html = (PAGE / "index.html").read_text(encoding="utf-8")
    assert 'id="live-case"' in html and 'id="old-cases"' in html
    assert 'id="tabs"' not in html and "past-list" not in html
    # Holding is the title and the join address, so the casebook is not drawn there.
    assert "const [top, ...older] = waiting ? [] : casesNow();" in html
    css = (PAGE / "room.css").read_text(encoding="utf-8")
    assert ".sheet .answer__text { max-height: 12rem; overflow: auto;" in css


def test_the_screen_is_the_same_casebook_without_buttons() -> None:
    """Newest case on top as a sheet, earlier cases folded, and nothing on it to press."""
    screen = (PAGE / "screen.html").read_text(encoding="utf-8")
    assert 'id="sheets"' in screen and "function renderSheets(" in screen
    body = screen[screen.index("function renderSheets(") : screen.index("function render()")]
    assert "V.sheet(room, top, { now, live, note: graded })" in body  # no controls argument
    assert "V.sheetBody(room, r, { now })" in body
    for gone in ("gradeControls", "data-verdict", "<button", "V.split("):
        assert gone not in screen, gone


def test_the_presenter_can_step_to_the_next_unpicked_case_in_one_click() -> None:
    """Kai curates dozens of prepared cases, so the next one in list order is a single button."""
    present = (PAGE / "present.html").read_text(encoding="utf-8")
    assert 'id="pick-next"' in present and "function nextInLine()" in present
    assert "sortedPrompts().filter((p) => !isUsed(p.id))" in present


def test_the_presenter_can_run_a_case_again_or_delete_it_and_pages_hear_a_delete() -> None:
    """The site is the pressure test, so a case is run and deleted from the page, not by hand."""
    present = (PAGE / "present.html").read_text(encoding="utf-8")
    room = (PAGE / "room.js").read_text(encoding="utf-8")
    assert 'id="case-run"' in present and 'id="case-delete"' in present
    assert (
        "`cases/${selected}/run`" in present
        and 'control(`cases/${selected}`, undefined, "DELETE")' in present
    )
    assert '"removed"' in room and 'method === "DELETE"' in room


def test_the_presenter_can_download_every_case_in_the_loaders_shape() -> None:
    """The keepers have to survive a wipe of the log, so the room's cases leave as a file."""
    present = (PAGE / "present.html").read_text(encoding="utf-8")
    assert 'id="cases-download"' in present and "function casesJson()" in present
    start = present.index("function casesJson()")
    body = present[start : present.index("\n}\n", start)]
    assert "sortedPrompts()" in body and '{ text: p.text, commitment: p.commitment ?? "" }' in body
    assert "const MAX_CASES = 100;" in present


def test_every_page_sits_on_the_kits_dark_ground_and_loads_it_first() -> None:
    """The room composes over the coilyco kit: its dark ground, loaded before room.css."""
    for name in ("index.html", "screen.html", "present.html"):
        html = (PAGE / name).read_text(encoding="utf-8")
        assert 'data-ground="dark"' in html, name
        assert html.index('href="coilyco-kit.css"') < html.index('href="room.css"'), name
    css = (PAGE / "room.css").read_text(encoding="utf-8")
    assert "var(--k-ground)" in css and "#14181f" not in css


def test_the_screen_opens_on_the_cover_while_proposals_are_hidden() -> None:
    """The room waits in submissions, so the cover with the four agents shows there too."""
    screen = (PAGE / "screen.html").read_text(encoding="utf-8")
    assert 'room.phase === "submissions" && !SHOW_PROPOSALS' in screen
    assert '$("main").hidden = showCloser || sheets || opening;' in screen


def test_jev_says_how_many_replied_in_one_line_and_nothing_until_the_engine_sends_it() -> None:
    """Kai chose one line in the box over a chip on every card, hidden until every check exists."""
    views = (PAGE / "views.js").read_text(encoding="utf-8")
    assert "function jevReplied(" in views and "jev-chip" not in views
    assert 'checks.some((j) => typeof j?.replied !== "boolean")) return null' in views
    assert "Math.min(...sure)" in views and "${replied.replied}/${replied.of} replied" in views


def test_a_card_with_no_answer_offers_no_grade() -> None:
    """The engine counts any grade, so an empty or failed answer must not be gradable."""
    html = (PAGE / "index.html").read_text(encoding="utf-8")
    body = html[html.index("function gradeControls(") : html.index("function renderClosing(")]
    assert 'state === "empty" || state === "failed"' in body and "No answer to grade." in body


def test_both_verdicts_take_a_reason_and_both_are_posted() -> None:
    """Kai wants a one-line reason on PASS as well as FAIL, and the engine must keep it."""
    html = (PAGE / "index.html").read_text(encoding="utf-8")
    body = html[html.index("function gradeControls(") : html.index("function renderClosing(")]
    assert 'mineNow.verdict === "fail" || mineNow.verdict === "pass"' in body
    assert "if (each.reason) reasons[id] = each.reason;" in html
    assert 'each.verdict === "fail" && each.reason' not in html


def test_the_reason_hint_says_others_will_see_it_after_results() -> None:
    """Attendees read each other's reasons once results open, so the hint must not say otherwise."""
    html = (PAGE / "index.html").read_text(encoding="utf-8")
    assert "Others in the room will see this after results." in html
    assert "Only the presenter reads it." not in html and "eval table at the end" not in html


def test_jevs_box_is_one_line_with_a_meter_and_the_explanation_on_hover() -> None:
    """Kai asked for about 40 characters: the scale is a meter, the words are the title."""
    views = (PAGE / "views.js").read_text(encoding="utf-8")
    body = views[views.index("function measure(") : views.index("/** A card's share")]
    assert 'class="measure__meter"' in body and 'title="${escapeHtml(title)}"' in body
    assert "·" not in body


def test_the_cases_list_opens_in_the_order_they_were_added() -> None:
    """Kai loads anchors first, so oldest-first is the default and Pick next follows it."""
    present = (PAGE / "present.html").read_text(encoding="utf-8")
    assert 'data-sort="order" aria-pressed="true">In order</button>' in present
    assert 'let sort = "order";' in present
    assert 'if (sort === "order") return list.sort((a, b) => a.seq - b.seq);' in present


def test_the_closing_line_and_link_are_the_developer_advocates_returned_copy() -> None:
    """The invitation ends on an email address now, on /screen and on the attendee page."""
    for name in ("screen.html", "index.html"):
        html = (PAGE / name).read_text(encoding="utf-8")
        assert 'href="mailto:kai@coilyco.ai"' in html and "coilysiren.me/setups" not in html, name
    screen = (PAGE / "screen.html").read_text(encoding="utf-8")
    assert "one-quarter pilot" in screen and "email me at kai@coilyco.ai." in screen


def test_a_persona_shows_its_model_label_and_nothing_when_the_snapshot_has_none() -> None:
    """The engine sends `subjects[].model_label`, absent when a subject has none."""
    room = (PAGE / "room.js").read_text(encoding="utf-8")
    assert 'typeof subject.model_label === "string" ? subject.model_label : ""' in room
    views = (PAGE / "views.js").read_text(encoding="utf-8")
    assert 'look.model ? `<span class="who__model">' in views


def test_the_presenter_reads_pass_reasons_and_the_room_pages_never_draw_them() -> None:
    """PASS reasons come as `notes` on the presenter snapshot, and only /present draws them."""
    present = (PAGE / "present.html").read_text(encoding="utf-8")
    assert "V.failures(room) + V.notes(room)" in present
    for name in ("index.html", "screen.html"):
        assert "V.notes(" not in (PAGE / name).read_text(encoding="utf-8"), name


def test_typed_reasons_show_on_the_attendee_results_and_the_presenter_never_on_the_screen() -> None:
    """Kai: attendees and /present read what the room said, and /screen shows counts only."""
    index = (PAGE / "index.html").read_text(encoding="utf-8")
    assert "reasons: true" in index
    screen = (PAGE / "screen.html").read_text(encoding="utf-8")
    assert "reasons: true" not in screen and "roundReasons" not in screen
    present = (PAGE / "present.html").read_text(encoding="utf-8")
    assert "V.roundReasons(room, last.n)" in present
