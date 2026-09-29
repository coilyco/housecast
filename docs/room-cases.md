# Commitments and prepared cases

Every prompt carries a `commitment` (empty string when absent) and a `source`
of `attendee` or `prepared`, in every view. Spec:
`teable:coilyco/housecast#8494`.

## Endpoints

`POST /api/prompts` takes an optional `commitment`. It is stripped, at most 140
characters, and a longer one answers 422 `{reason: "the commitment is over 140
characters"}`. Intake still needs the submissions phase and the rate limits.

`POST /api/control/cases` takes `{text, commitment}` with `X-Control-Token`.
It answers 201 `{id, seq}` or 422 `{reason}`, takes up to 2000 characters of text (attendee
prompts stay at 280) with inner newlines kept, works in every phase, and sits outside the rate and burst limits. The
prompt fans out and scores like an attendee one, marked `prepared`.

## What each view sees

- **presenter** - everything.
- **attendee and screen** - a prepared prompt's `text` is omitted and its
  `commitment` is `""` until it is picked, in snapshots and the stream. `source`
  stays, so a page can count prepared cases apart from proposals.
- **screen** - an unpicked attendee prompt loses its text and, with it, its
  commitment. The attendee view shows both.

A log written before this change replays with `commitment: ""` and
`source: "attendee"`. Divergence rows and `rev` are unchanged.
