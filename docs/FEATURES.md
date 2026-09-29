# Features

Coarse inventory of the major capabilities housecast ships.

## Shipped

* **The grading half.** `housecast grade` under the `eval` extra: schema, pairing, annotation,
  taxonomy, export, `grade serve`, and `grade pin`. See [`grading.md`](grading.md).
* **The grading page.** One card per pair, both halves side by side, evidence highlighted.
  One file, no build step. See [`grading-page.md`](grading-page.md).
* **Observational boards.** From replies a subject already gave, so a cell can be decided and not a verdict. [`grading-non-scores.md`](grading-non-scores.md).
* **The room-facing half.** `grade deck` builds a scanned, slug-free deck and `grade present` serves
  it with anonymous voting. [`presenting.md`](presenting.md), [`deck.md`](deck.md).
* **The variant search.** Reads every variant against a measured noise floor and labels overfitting
  and overselling rather than netting them. `teable:coilyco-flight-deck/housecast#7802`.
* **The MCP tool-description loop.** `housecast mcpeval`, under `eval` and `mcp`: an HTTP MCP subject
  with flawed prose, a runner making real model calls and routing the returned calls back to it,
  deterministic grading, a concurrent run, a paired sign test, and the visual flow driving it.
  Record: agentic-os-kai `evaluations/mcp-tool-loop-2026-09-16/`.
* **The Jev routing bench.** `just jevroute`: one Jev choice per question over an MCP subject's live
  `tools/list`, pass at confidence 0.9, confident-wrong kept apart, dev and holdout splits. Cases and
  rounds: `evaluations/jevroute-eco/`, `teable:coilyco/sirens-echo#8221`.
* **The live room.** `housecast room serve` under the `room` extra: prompt intake, fan-out to every
  subject, a divergence score, and a restart log. [`room.md`](room.md).
  Prompt commitments and presenter-prepared cases: [`room-cases.md`](room-cases.md).
  Its attendee, shared-screen, and presenter pages: [`room-display.md`](room-display.md).
* **The PyPI release train.** A pushed `housecast-v*` tag gates, builds and uploads. [`publishing.md`](publishing.md).

## Not shipped

No release is on PyPI yet, only the 0.0.1 name claim. Attested bundles are designed, not built.
The variant search has no `Measurer`. The MCP loop runs on one task and one subject: a second task,
an LLM judge, HTTP fault injection and a holdout split are absent, and it has no `docs/` page
because the band is full at 20.

## See also

* [`../README.md`](../README.md) - what housecast is, and [`../AGENTS.md`](../AGENTS.md) for agents.
