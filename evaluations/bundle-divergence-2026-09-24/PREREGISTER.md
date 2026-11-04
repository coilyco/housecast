# Pre-registration: do four composed bundles diverge on single-turn prompts

Seat: science. Written 2026-09-24T03:33:32Z, before any bundle call.
`teable:coilyco-flight-deck/agent-compose#8166`, for the PyLadies Remote room
(2026-09-29). agent-compose at `94e4e11`.

## Setup, frozen
* Bundles: `scientist`, `frontend-eng`, `game-dev`, `dev-advocate`, each at
  `frontier` tier, `compiled` delivery, from `just compose-bundles` on this commit.
  The system prompt is `delivery/compiled.md` verbatim. The `frontier` tier is the only
  one all four share (scientist ships no other). The bundles carry no seat names.
* Routes: `evaluation/deepseek-v4-flash` and `evaluation/deepseek-v4-pro` via Agent
  Proxy `/v1/chat/completions`. temperature 0.7 and max_tokens 1500 for every call.
  Both routes return reasoning that counts against the cap.
* User message: the prompt text verbatim, single turn, no history.
* Prompts (`prompts.json`): the four deck samples, four discriminating prompts, and two
  factual controls.
* Samples: 4 per bundle per prompt per route, so 10 x 4 x 4 x 2 = 320 calls. 8 wide.

## Measures, fixed here
* Latency: wall time per call, p50 and p95 per route. Errors and truncations
  (`finish_reason` length) are counted and reported.
* Quartets. A between quartet is the four bundles at the same sample index, 4 per prompt
  per route. A within quartet is one bundle's four samples, 4 per prompt per route. The
  within quartets are the noise floor.
* Lexical divergence: mean pairwise (1 - Jaccard) over lowercased word sets.
* Jev divergence: `jev-1.13.0` score on "How far apart are the stances these four answers
  take on the prompt?" over levels same, slight, moderate, large, opposite (0 to 4).
  The state is the prompt and the four answers labelled A-D in a seeded shuffle, with no
  bundle names. The score is the expected level. Jev latency per call is reported.
* Signal per prompt per route: mean between-quartet score minus mean within-quartet
  score, for each measure.
* Agreement: Spearman rho between Jev and lexical over all quartets, per route.
* Go or no-go: one Jev noul on the session premise, with the measured facts as a
  neutral state. It is reported with its probability and confidence.

## Disclosure
I wrote the prompt set, the measures and the Jev wording, and I run the scorer.
