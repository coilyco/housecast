# Pre-registration: does the PyLadies Remote room hold at ten attendees

Seat: science. Written 2026-09-26T04:32:14Z, before the room exists.
`teable:coilyco-flight-deck/housecast#8168`, milestone M2 in the plan on
`teable:coilyco-bridge/inbox#4019` (comment 20124). The session is Wed 2026-09-30,
07:00 PDT. agent-compose at `6c07240`.

## Claim

On the M2 dev deploy, the room answers ten simultaneous single-turn attendee
prompts on all four subjects within a time a live room will wait, shows each
subject as it lands, and keeps the divergence signal
`bundle-divergence-2026-09-24` measured on the pro route.

## Setup, frozen

* **Target:** the M2 dev deploy. Its base URL and housecast commit are recorded
  at run time. Endpoints come from the data contract eng-platform and
  frontend-eng record on #8168 at M1. If that contract is missing at M2, the run
  does not start.
* **Access:** only the room's own attendee-facing endpoints: submit a prompt, then
  read its state. No kubectl mutation, no pod restart, and no direct Agent Proxy
  call for the subjects' answers. Restart-log survival is an M3 check that needs a
  restart, so it is out of scope here.
* **Side effect, named:** submitted prompts land in the dev deploy's restart log.
  Every run prompt carries a `[m2-probe]` suffix so the room owner can filter
  them out, and the session instance must not share that log.
* **Prompts:** `../bundle-divergence-2026-09-24/prompts.json` unchanged. That's 8
  persona prompts (4 deck, 4 disc) and 2 factual controls.
* **Route:** whatever the room is configured with. Kai chose pro. The run
  records it from the room and does not set it.

## Stages

* **S1, sequential.** Each of the 10 prompts once, one at a time. This gives
  latency at concurrency 1 and the divergence check.
* **S2, concurrency sweep.** 1, 5, then 10 prompts submitted in the same second,
  with each level run twice. Persona prompts are drawn round-robin. **10 is
  the assumed attendee count, from Kai (2026-09-26), all submitting at once**,
  which is the worst case for a room of that size. S1 plus S2 is 42 prompts and
  168 subject answers.
* **Stop rule.** If more than 20% of prompts at a level fail, the sweep stops
  there and does not climb. The failed level is the finding.

## Measures, fixed here

* **Time to all four:** from submit until all four subjects show a final answer,
  read by polling the room once a second. p50, p95 and max per level.
* **Time to first subject:** the same clock, until the first subject lands.
* **Errors:** a non-2xx on submit, a subject the room marks failed, or a prompt
  not finished at 180s.
* **Empty answers and markup:** subject answers that are empty, or that contain
  tool-call markup.
* **Divergence:** the room's own score per prompt in S1. The gap is the mean over
  the 8 persona prompts minus the mean over the 2 controls, on the room's scale.
  If the room reports on Jev's 0 to 4 scale, the gap is in those levels.

## Pass, fixed here

* **P1 load:** 0 errors at 10, and time to all four at p95 is at most 90s.
* **P2 answers:** at most 5% of answers are empty, and none carry markup, over all
  168.
* **P3 divergence:** a persona minus control gap of at least 1.0 level, with both
  controls at or below 1.0.
* **P4 progress:** in at least 80% of prompts, the first subject lands at least 5s
  before the fourth, so per-subject progress is visible rather than instant.

Any miss is reported to prod-director with the raw rows. The measurement
carries no GO/NO-GO call, because that is M3.

## Disclosure

I wrote the #8166 prompt set this reuses, these measures, and the thresholds.
I did not build the room. Two other seats did, from a spec I did not write.
