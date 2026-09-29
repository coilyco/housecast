# Examples

`two-agents/` is a room with two subjects, each a system prompt in a markdown
file. Point the room at any OpenAI-compatible endpoint and serve it:

```
export ROOM_PROXY=http://localhost:11434   # base URL, no /v1
export ROOM_MODEL=llama3.2                 # any model that endpoint serves
uv run --extra room housecast room serve \
  --subjects examples/two-agents/subjects.json --log /tmp/room.jsonl
```

Open `http://localhost:8767/` for an attendee, `/screen` for the shared screen,
and `/present` for the presenter, who pastes the control token the room prints.
Add a subject by adding an entry and a markdown file. The full setup, keys and
scoring are in [`docs/room.md`](../docs/room.md).
