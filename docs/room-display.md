# The room's pages

The three pages [`room.md`](room.md) serves from `housecast/room/page/`, with no build step.

## One room, three readers

* `/` is the attendee page on a phone: the info page, then submit plus the live leaderboard, then grade, the split, and closing, whichever phase the presenter set.
* `/screen` is shared into the call and lands on the public recording. It reads `?view=screen`, so no prompt text reaches it until the presenter picks one. In closing it counts failing grades rather than printing their reasons, because the reasons are attendee-typed.
* `/present` is the presenter's. The bar's one button follows the phase and acts on the prompt selected in the list, so a pick never waits below the fold. In closing it raises the closer, since going back to holding resets the room, which stays in the jump list. The round panel sits above the prompt list while a round is live. A token in `#token=` is taken once, dropped from the address, and kept in localStorage, so a reload or a new tab keeps control.

`/screen` is the only thing on the recording, so its holding state is the opening shot, in the presenter's own words from her deck. Its closer shows exactly the approved invitation and two links with no heading. The presenter raises the closer from `/present` over a BroadcastChannel on the same laptop, so the shared tab never navigates, and `#closer` does it by hand.

## Why it looks like this

The presenter's session flow deck is the visual reference, so the pages take its dark slate, IBM Plex Sans, and each subject's colour and logo from `subjects.json` rather than the kit's purple. A subject is always its logo (a glyph when it has none), name, and colour together, never hue alone. Divergence bars are neutral because rose means FAIL.

The shared screen scales type off the short side of the window, since the projector's aspect is unknown. It also fits the split and the four answers to the window, at 16:9 and at 4:3, so the names under the bars are never pushed off the recording.

## Staying up

A stream a sleeping laptop dropped can stay open and silent, so every page re-reads the snapshot on wake, on network return, and every 30 seconds. Grades and phase changes retry once on a network failure, and prompts and picks never do, since a lost response could double them. A pick waits for every answer to be final, done, empty, or failed, and after 75 seconds it opens anyway, naming who is missing.

## Working on them

`?demo=holding|submissions|grading|split|closing|flow` renders any page from a scripted room in the contract's shapes, marked "demo data", with no server. A page redraws each second for its timers and only rewrites markup that changed, so a half-typed reason survives and a screen reader is not re-announced.
