# The live room

`housecast room serve --subjects subjects.json --log /data/room.jsonl` runs one
room. Attendees submit prompts, every subject answers each one, the room scores
how far apart they landed, and the presenter picks a round for the room to
grade PASS or FAIL. Record and full data contract:
`teable:coilyco-flight-deck/housecast#8168`.

## What a consumer brings

`subjects.json` alone. Each subject is `{id, label, system}` or
`{id, label, system_file}`, with optional `color`, `emblem`, `logo`, `role`,
and `line` for the page. `label` is the seat's canonical creature name, never
a session name. `logo` is a path under the page directory, and the pages hold
no subject's name, colour, or logo of their own.

## Environment

`ROOM_PROXY` is an OpenAI-compatible base URL (`/v1/chat/completions` answers, `/v1/systemone` scores). `ROOM_MODEL` and `ROOM_JEV_MODEL` pick the routes, and `ROOM_CONTROL_TOKEN` gates the presenter, or one is minted and printed.

Rate limits key on the viewer's address. `ROOM_TRUSTED_HOPS` counts the `X-Forwarded-For` entries trusted proxies append, and the viewer is the leftmost of them: 1 behind one ingress (the default), 3 behind CloudFront plus a Google external Application Load Balancer, which appends `<client-ip>,<load-balancer-ip>`. Too low, and every phone shares one limit. `ROOM_CLIENT_HEADER=CloudFront-Viewer-Address` reads it from that header when an origin request policy forwards it (`teable:coilyco/deploy#8452`).

## Surfaces

`GET /api/room` is the snapshot and `/api/room/events` streams the same shapes
with a `rev`. `?view=screen` withholds unpicked prompt text for the recorded
screen. Answer text shows only once its prompt is picked, and grades travel as a
count until the presenter reaches the split. `/api/control/*` is the presenter.

## Answers and scores

An answer is the subject's system prompt plus the prompt and a short-answer
frame, at a 4000-token cap, with tool-call markup stripped. Divergence asks Jev
for the stance distance over the answers, as a level from 0 to 4 reported over
4, and falls back to lexical distance, marked `lexical`, when Jev fails.

## The restart log

Every event is appended before it is applied, and a start replays the log,
dropping a torn last line. Answers a restart cut off are asked again.
