# A model per subject, and the fallback

Both are off until set, and with neither set every subject answers on `ROOM_MODEL`.

## Per subject

A subject may carry a `model` in `subjects.json`, which replaces `ROOM_MODEL` for that subject alone:
`{"id": "gem", "label": "Violet", "system_file": "gem.md", "model": "evaluation/mistral-medium-3.5"}`.
The room never shows it. Snapshots and the event stream drop `model` the way they drop `system`.

## The fallback

`ROOM_FALLBACK_MODEL` (or `--fallback-model`) names one route for the whole room. When every answer to a
prompt is terminal and any ended `failed` after its retry, the room logs a `fallback` event and asks every
subject again on that route, so a round is never split across models. It happens once per prompt, and not
after the presenter has picked it, since the answers would change under the grading room.

There is no default, so with none set a failed answer stays failed. Attendees and the presenter stream see
that a switch happened and never the model. The event log and the server log carry the model name.

## Restart

The switch is one log event, and replaying it re-queues every answer of that prompt. A restart mid-round
neither loses the switch nor repeats it. Answers the restart cut off resume on the model the event
recorded, whatever the restart's own setting says.

## No Anthropic models

The room refuses to load a subject `model` or a fallback whose name contains `claude` or `anthropic`, in any
case. That is a name heuristic only. What the proxy routes a name to is the real control, so an Anthropic
model behind a neutral alias is not caught here.
