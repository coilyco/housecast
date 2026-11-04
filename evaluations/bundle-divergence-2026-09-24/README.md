# Do four composed bundles diverge? Yes on pro, noisily on flash

2026-09-24, science seat, `teable:coilyco-flight-deck/agent-compose#8166`, for the
PyLadies Remote room. Four `frontier`/`compiled` bundles (scientist, frontend-eng,
game-dev, dev-advocate) from `just compose-bundles` at `94e4e11`, with `compiled.md` as
the system prompt. 10 prompts x 4 bundles x 4 samples x 2 routes = 320 calls, all
answered. 160 Jev quartet scores, all `jev-1.13.0`. Run 03:35-03:43 UTC.
`PREREGISTER.md` and `PREDICTION.txt` were pushed before any call (`e785313`).

## The open check
Every non-archived role ships a `compiled` bundle (`scripts/compose-bundles.py`,
`DELIVERY_MODES`), so `delivery/compiled.md` exists for a harness-less target. Scientist
ships only the `frontier` tier. The bundles carry no seat names (Evie, Delphi, Sprite,
Gem): the scientist identity line reads "Agent // Frog-Ox".

## Measured (`results/`)
* Latency, per route: flash p50 4.10s, p95 8.95s, max 10.40s. pro p50 15.07s, p95
  42.59s, max 44.64s.
* Token cap (1500, reasoning included): flash 32/160 truncated and 18 empty. pro 31/160
  truncated and 29 empty. They concentrate on long-answer prompts (friday, python-js,
  review), and the deck prompts are mostly clean.
* Raw tool-call markup in the answer: flash 6/160, pro 4/160. The compiled prompt tells
  the agent to run commands, and a plain completion has no tools.
* Jev stance divergence, between minus within quartets (0-4):
  * pro: deck +2.25 (purple), +0.17, +1.87, +1.02. discriminating +0.46, +0.73, +1.31,
    +1.42. controls +0.07, +0.03.
  * flash: deck +0.42, +0.93, +0.51, +1.09. discriminating +0.19, +0.61, +1.06, +1.48.
    controls -0.26, +0.61.
* Post-hoc, not preregistered (`sensitivity.txt`): with quartets holding any truncated or
  empty answer dropped, the deck and control numbers hold. Friday and python-js lose
  every quartet.
* Visible in the raw answers: on pro each bundle names its own favourite colour for
  "purple" (`#14d5b8`, `#ee7eea`, `#3b82ff`, `#f7a060`), and all four say "Paris".
* Jev scoring latency p50 0.21s, p95 0.43s. Spearman(Jev, lexical) 0.47 flash, 0.69 pro.
* Go or no-go, Jev `jev-1.13.0` noul on the premise: p=0.58. Route choice: flash 0.52,
  pro 0.48, confidence 0.05.

## Against the prediction
Controls lowest and deck prompts diverging: held on pro, not on flash, where
ctl-capital showed +0.61. Lexical signal small: held. Jev-lexical agreement under 0.4:
wrong, it was 0.47 and 0.69. Flash latency 5-15s: faster, at p50 4.1s. Pro p95 over
30s: held, at 42.6s. GO on flash: Jev gave a weak 0.58 on the premise and no route
preference.

## Inference, not measured
* The premise is supported on pro. Its controls sit at about 0 while persona prompts
  separate by 1-2 levels. Flash separates the persona prompts too, but its controls are
  noisy enough to put a factual prompt on the leaderboard.
* Jev is fast enough to score live (0.2s). Lexical distance tracks it only loosely, so
  it works as a fallback, not as the score.
* Two cheap fixes the room needs either way: a higher cap, or a one-line "answer in a
  sentence or two" frame, and stripping tool-call markup before display.
* The route is a trade Jev would not make: clean signal at about 15s (pro) against a
  noisier signal at about 4s (flash). That call belongs to the room's owner.
