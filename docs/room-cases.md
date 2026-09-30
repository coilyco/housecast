# Commitments and prepared cases

Every prompt carries a `commitment` (empty string when absent) and a `source`
of `attendee` or `prepared`, in every view. Spec:
`teable:coilyco/housecast#8494`.

## Endpoints

`POST /api/prompts` takes an optional `commitment`. It is stripped, at most 140
characters, and a longer one answers 422 `{reason: "the commitment is over 140
characters"}`. Intake still needs the submissions phase and the rate limits. `ROOM_ATTENDEE_PROMPTS=off`
makes it answer 403 `{reason: "attendee prompts are off"}` before anything else, default `on`.

`POST /api/control/cases` takes `{text, commitment}` with `X-Control-Token`.
It answers 201 `{id, seq}` or 422 `{reason}`, takes up to 2000 characters of text (attendee
prompts stay at 280) with inner newlines kept, works in every phase, and sits outside the rate and burst limits. The
prompt fans out and scores like an attendee one, marked `prepared`.

`DELETE /api/control/cases/{id}` takes the same token and removes a case that no round has picked, with its
answers and divergence. It answers 200 `{id}`, 404 for an unknown id, and 409 once the case is in a round. The log
records a `removed` event, so a restart replays the deletion, and a new case takes the next free `seq`.

`POST /api/control/cases/{id}/run` asks the case's four subjects again and scores it again, for a model or route
change. It answers 202 `{id}`, 404 for an unknown id, and 409 for a case in a round or one still answering. The log
records a `rerun` event, and the new answers and divergence land in the same log the presentation reads. /present
shows both as "Run this case again" and "Delete this case" on the selected case.

## What each view sees

- **presenter** - everything.
- **attendee and screen** - a prepared prompt's `text` is omitted and its
  `commitment` is `""` until it is picked, in snapshots and the stream. `source`
  stays, so a page can count prepared cases apart from proposals.
- **screen** - an unpicked attendee prompt loses its text and, with it, its
  commitment. The attendee view shows both.

A log written before this change replays with `commitment: ""` and
`source: "attendee"`. Divergence rows and `rev` are unchanged.

Jev (`teable:coilyco/housecast#8520`, none of it a grade): `answer.jev` is `{replied, confidence, p, source}`, from one noul call per answer with text after it is stored, so it never holds the round. It is `null` if that call fails, `replied: false` from state for a blank answer. `divergence.confidence` and `.probabilities` are Jev's, `null` under the word-overlap fallback. A grade reason is kept on PASS as on FAIL. The presenter snapshot lists PASS reasons as `notes` of `{n, subject_id, verdict, reason}`, attendees get notes and FAIL reasons once a round's results open, never /screen, and `POST /api/control/reasons {visible}` hides them from attendees (default shown, logged, `reasons_visible` for the presenter). A grade on an `empty` or `failed` card is refused with 422.
