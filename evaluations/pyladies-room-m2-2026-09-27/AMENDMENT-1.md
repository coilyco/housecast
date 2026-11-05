# Amendment 1: fit the measures to the M1 contract

Seat: science. Written 2026-09-26T04:36:04Z, before any run and before a dev
deploy exists. Source: the M1 data contract, comment 20132 on
`teable:coilyco-flight-deck/housecast#8168`. `PREREGISTER.md` still stands except
where this file overrides it.

## Access, narrowed

* **Read:** `GET /api/room` and `GET /api/room/events` only. These are the public
  snapshot and its event stream.
* **Write:** `POST /api/prompts` only, with a distinct `device` per simulated
  submitter. Distinct devices match a real room of 10 browsers, and the 20s
  per-device limit stays in force.
* **Not held:** the `X-Control-Token`. It moves the phase and picks rounds, which
  are presenter writes, and the read-only constraint on this measurement rules
  those out. The room owner sets the dev deploy to `submissions` before the run.
  A 409 at submit time means the run does not start.

## Measures, remapped

* **Time to all four / first subject:** read from each answer's `started_at` and
  `finished_at` in the snapshot, not from polling. Wall-clock time of the submit
  call is kept as a cross-check.
* **Errors:** a non-2xx on submit other than an expected 429, an answer in
  `failed`, or a prompt without four terminal states at 180s.
* **P2 empty:** answer `state: empty` over all answers, from the public snapshot.
* **P2 markup:** it needs answer text, which the public snapshot withholds for
  unpicked prompts. After the run, the room owner exports the `[m2-probe]` rows of
  the restart log, and I count markup in that export. If there's no export, the
  markup half of P2 is reported as unmeasured, not as passed.
* **P3 divergence:** the room scores 0 to 1. The threshold becomes a persona
  minus control gap of at least 0.25, with both controls at or below 0.25. That
  is 1.0 level on Jev's 0 to 4 scale if the room's score is level divided by 4. The
  room owner confirms the mapping before the run. If the mapping is different, the
  0.25 threshold is re-derived from it here, before the run.

## Confirmed by the room owner, 2026-09-26, still before any run

* **Mapping:** `score` is Jev's expected stance level divided by 4, clamped to 0 to 1,
  with the same levels and shuffled-answer body as `bundle-divergence-2026-09-24`.
  0.25 stands.
* **Lexical fallback:** a prompt scored with `method: lexical` is mean pairwise
  Jaccard distance, which is not on that scale. P3 uses stance scores only. The
  lexical count is reported beside it, and a control with no stance score leaves
  P3 unmeasured rather than passed.
* **Markup export:** the room strips markup before it logs, so the export measures
  what reaches a screen, which is the P2 question. Raw markup before the strip is
  the room owner's separate count, if the dev log allows it.

`room_m2.py` implements this. `just evalkit-room-m2 selftest` runs it against an
in-process fake room.

## Prediction, unchanged

`PREDICTION.txt` stands. The room owner reports a short-answer frame at a 4000
cap with markup stripped, which moves the prediction's own condition for P2 toward
passing. The prediction text is left as written.
