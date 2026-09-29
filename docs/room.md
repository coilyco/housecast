# The live room

`housecast room serve --subjects subjects.json --log /data/room.jsonl` runs one
room. Attendees submit prompts, every subject answers each one, the room scores
how far apart they landed, and the presenter picks a round for the room to
grade PASS or FAIL. Record and full data contract:
`teable:coilyco-flight-deck/housecast#8168`.

## What a consumer brings

`subjects.json` alone. Each subject is `{id, label, system}` or
`{id, label, system_file}`, with optional `color`, `emblem`, `logo`, `role`, and `line` for the page.
`label` is the seat's canonical creature name, never a session name, and `logo` is a path under the page directory. The pages hold no subject's name, colour, or logo of their own.
A subject may also name its own `model`, and the room may name a fallback: [`room-models.md`](room-models.md).

## Your own agents

Any OpenAI-compatible endpoint runs a room, set by three variables. Copy the folder in [`examples/`](../examples/README.md).

* `ROOM_PROXY` - the base URL with no `/v1`. The room posts to `<base>/v1/chat/completions`, and a local Ollama is `http://localhost:11434`.
* `ROOM_PROXY_KEY` - sent as `Authorization: Bearer <key>`. Unset sends no header, which a local server accepts.
* `ROOM_MODEL` - the model name that endpoint serves. A subject's own `model` overrides it.

The defaults are the author's: `http://ser8:8080` is a tailnet host, `evaluation/deepseek-v4-pro` a route on it, and `jev-1.13.0` (`ROOM_JEV_MODEL`) a scoring model at `<base>/v1/systemone`. Without a Jev endpoint every score falls back to word overlap, which the presenter page marks `*`. Answers are unaffected.

`ROOM_CONTROL_TOKEN` gates the presenter, or one is minted and printed. Behind a proxy or CDN: [`room-site.md`](room-site.md). The restart log: [`room-models.md`](room-models.md#restart).

## Surfaces

`GET /api/room` is the snapshot and `/api/room/events` streams the same shapes
with a `rev`. `?view=screen` withholds unpicked prompt text. Answer text shows
once its prompt is picked, and grades travel as a count until the split.
`/api/control/*` is the presenter. Commitments, prepared cases: [`room-cases.md`](room-cases.md).

## Answers and scores

An answer is the subject's system prompt plus the prompt and a short-answer
frame, at a 4000-token cap, with tool-call markup stripped. Divergence asks Jev
for the stance distance over the answers, as a level from 0 to 4 reported over
4, and falls back to lexical distance, marked `lexical` (`*` on the presenter page), when Jev fails.
