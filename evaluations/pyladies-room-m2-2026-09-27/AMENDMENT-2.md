# Amendment 2: which provider served each answer

Seat: science. Written 2026-09-26T04:44Z, before any run. Source: prod-director
reports a LiteLLM fallback from `evaluation/deepseek-v4-pro` to Baseten's V4-Pro,
live on ser8 through deploy#999.

## Why

`bundle-divergence-2026-09-24` measured DeepSeek-direct. If a fallback serves some
M2 answers, the provider changes along with load, and a latency or divergence
move can't be put down to either one.

## What was checked, before the run

At about 04:43Z a one-line completion on `evaluation/deepseek-v4-pro` returned
`finish_reason: stop`. The response's `model` field was the route alias
`evaluation/deepseek-v4-pro`, not a provider. So the answer body can't show which
provider served it.

## The provenance method, tested before the run

SigNoz carries `litellm.provider.model` on each `litellm_request` span. It reads
`deepseek/deepseek-v4-pro` for DeepSeek-direct and
`openai/deepseek-ai/DeepSeek-V4-Pro-0813` for the Baseten fallback. A failed primary
attempt carries `error.llm_provider`. Checked 2026-09-26 at about 04:45Z, read-only:

* My 04:43:41Z probe is trace `3c7589c34eb9f750ea3612af3df7c804`. The DeepSeek-direct
  filter returned 1 span (Ok, 1.50s), and the Baseten filter returned 0.
* The fallback served at 04:37:13.96Z, in trace `bdcbfb6deb1937c6cd79db953385f0f9`,
  1.3s after that trace's primary attempt returned 402. That's earlier than
  deploy#999's reported 04:42Z. The Baseten model also has spans around 2026-09-25
  21:30Z.
* `error.llm_provider EXISTS` from 04:20Z returned 4 traces, all 402s between
  04:36:17Z and 04:37:12Z, and none after them.

**Attributing spans to the room.** Other seats share Agent Proxy, so the room tags
its calls. housecast PR #194 (`32beddd`) sends header `x-agent-session-id =
ROOM_USER`, and the dev deploy sets `pyladies-room-dev`. Agent Proxy writes it to
`agent.session_id` on its `request.chat`, `resilience.attempt` and `upstream.chat`
spans (service `agent-proxy`). The OpenAI `user` field is dropped, so it's not
used. The procedure:

1. Filter agent-proxy `request.chat` spans on `agent.session_id = 'pyladies-room-dev'`
   over the run window. That gives the room's trace ids, one per subject call.
2. For each trace, read every `litellm_request` span's `litellm.provider.model`
   and status. A trace is **fallback-served** if its Ok `litellm_request` is the
   Baseten model, and **primary-failed** if any `litellm_request` carries
   `error.llm_provider`.
3. The count of room traces should equal the answers that left `queued`. A gap
   means untagged calls, and it gets reported.

Checked at about 04:48Z against the room owner's probe, trace
`cd7b5641182031cff8e21d17c817beab`. It holds the four agent-proxy spans and one Ok
`litellm_request`. The only `agent.session_id` value in the store was the probe's
own `housecast-room-spanprobe2`, and `pyladies-room-dev` had no spans yet.

If the tag is missing at run time, a count over the run window is reported
instead, labelled as an upper bound.

## The rule

* **Provenance source:** the room's export rows, if the room logs a provider or
  upstream model per answer. Otherwise, Agent Proxy traces in SigNoz for the run
  window, read-only. The run window and the source used go in `results/`.
* **All DeepSeek-direct:** P1 to P4 are scored as preregistered.
* **Any answer served by the fallback:** P1 to P4 are reported twice, once over
  all answers and once over prompts whose four answers were all DeepSeek-direct.
  Only the second is compared with `bundle-divergence-2026-09-24`. The fallback
  share is reported beside both.
* **Provenance unknown:** the comparison with `bundle-divergence-2026-09-24` is
  reported as unconfirmed, and P1 to P4 still stand for the room as it ran.
* **Clock and ceilings, confirmed by the room owner:** every `at`, `started_at`, and
  `finished_at` comes from one server clock, as ISO 8601 UTC with milliseconds. The
  room caps an address at 30 prompts per 20s. The run peaks at 15 inside any 20s,
  so a 429 at M2 is unexpected and gets reported, not ignored.
* **A 402 or a provider outage during the run:** the affected prompts count as
  errors under P1, and the whole run is repeated once the route is healthy. Both
  runs are kept.
