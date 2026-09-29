# The room's pages

The three pages [`room.md`](room.md) serves from `housecast/room/page/`, with no build step.

## One room, three readers

* `/` is the attendee page on a phone, in whichever phase the presenter set. Attendees wait, grade four answers PASS or FAIL, read each agent's PASS share, and end on the eval table. Proposing is off (`SHOW_PROPOSALS` in `room.js`) since Kai takes prompts from Zoom chat, and instruction sentences are hidden (`SHOW_HINTS`). A guard test keeps competition wording off this page and `/screen`.
* `/screen` is shared into the call and lands on the public recording. It reads `?view=screen`, so no prompt text reaches it until the presenter picks one. After each result it shows Jev's divergence, boxed as a machine measurement and never a grade, and in closing the eval table without reasons, which are attendee-typed.
* `/present` is the presenter's. The bar's one button follows the phase and acts on the prompt selected in the list. In closing it raises the closer, since going back to holding resets the room, which stays in the jump list. Pasting a prompt into "Add prepared cases" works in any phase, and its pick opens from holding, submissions or results. A file of `{text, commitment}` also loads ([`room-cases.md`](room-cases.md)). Its divergence score doubles as a sorting aid. A token in `#token=` is taken once, dropped from the address, and kept in localStorage, so a reload or a new tab keeps control.

`/screen` is the only thing on the recording, so its holding state is the opening shot, in the presenter's own words from her deck. Its closer shows exactly the approved invitation and two links with no heading. The presenter raises the closer from `/present` over a BroadcastChannel on the same laptop, so the shared tab never navigates, and `#closer` does it by hand.

## Why it looks like this

The presenter's session flow deck is the visual reference, so the pages take its dark slate, IBM Plex Sans, and each subject's colour and logo from `subjects.json`. A subject is always its logo, name, and colour together, never hue alone. Divergence bars are neutral because rose means FAIL.

The shared screen scales type off the short side of the window. A pasted prompt's context shows in a scrolling box under its question, 14 lines on grading and 10 on results.

## Staying up

A stream a sleeping laptop dropped can stay open and silent, so every page re-reads the snapshot on wake, on network return, and every 30 seconds. Grades and phase changes retry once on a network failure, and prompts and picks never do. A pick waits for every answer to be final, and after 75 seconds it opens anyway, naming who is missing.

## Working on them

`?demo=holding|submissions|grading|split|closing|flow` renders any page from a scripted room in the contract's shapes, marked "demo data", with no server. A page redraws each second and rewrites only changed markup, so a half-typed reason survives.
