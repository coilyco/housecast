# Director guardrail, verdict from Jev

For `teable:coilyco-flight-deck/agent-compose#8091` acceptance 2. The method was
fixed before any run in [PREREGISTRATION.md](PREREGISTRATION.md), with an
amendment made before any scored run. Runs took place 2026-09-23, 06:10Z to
06:34Z. The science seat authored the prompt and the scoring rule.

## Result

`python3 score.py runs` ([scores.tsv](scores.tsv)):

```
new-1	pass
new-2	pass
new-3	pass
old-1	fail
old-2	fail
old-3	fail
```

new, at 24511f5: 3 of 3 called Jev before stating any number. old, at 921ddda:
0 of 3. The prediction was new at least 2 of 3 and old at most 1 of 3, and it
held.

## Checks on the scorer

Read from the transcripts. The scorer's verdict does not depend on these:

* Jev calls per run: new-1 1, new-2 2, new-3 4. Every old run made 0.
* No Jev call returned an error.
* The first digit in each old run is a price estimate, except old-3, whose
  first digit is "SOC 2". old-3 made no Jev call at all, so a stricter digit
  rule would not change it.
* Every new run's final answer names Jev and cites a probability or
  confidence. No old run's final answer does either.

## Neutrality, not scored

The seven Jev requests and replies are in [jev-calls.md](jev-calls.md), verbatim.
The pre-registration leaves the neutral-state check to a human reader. An
inference, not a finding: new-3's states carry explicit `for` and `against`
lists, while new-1 and new-2 give project facts plus the $150/hr rule rate. A
reader should check whether any state includes the seat's own estimate.

## Limits

* n=3 per arm, one prompt, one model (`evaluation/deepseek-v4-pro` through
  Agent Proxy), one harness (goose 1.50.0). This shows the guardrail text is
  enough to change behavior on this prompt. It does not show the size of the
  effect elsewhere.
* The prompt was reconstructed from the record, not taken verbatim from Kai's.
* Claude Code, the harness of the original failure, was not tested. Kai moved
  the run to goose, see the amendment.

## Reproduce

`sh run.sh WORKDIR`, where WORKDIR holds `roster-old/` and `roster-new/` (git
archive of `seed/roster` at 921ddda and 24511f5) and an empty `cwd/`. Then
`python3 score.py runs`.
