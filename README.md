# housecast

Human-graded behavior evaluations, for any agent

housecast is the grading half of an evaluation: the case and dataset schema,
the pairing rule, one-keystroke annotation, the grading page, the room-facing
deck, and the MCP tool-description loop. It knows nothing about who the subject
is. A consumer brings its own cases, entity projection, profile, and runner, and
housecast grades what came back. It ships no profile, so every board names its
own.

[`docs/FEATURES.md`](docs/FEATURES.md) is the inventory. The name `housecast` is
held on PyPI as a 0.0.1 placeholder. The release train that turns a
`housecast-v*` tag into a real upload is wired, and until the first tag runs it,
consumers install from GitHub.

## The name

A house cast is the resident standing company of a theatre: a fixed troupe held
by one house under one set of conventions, able to mount any role in its book.
`house` is the authority noun. `cast` carries both casting a play and casting
metal, and that second sense is the immutable bundle.

Two other readings of the string are live, and neither one is this project.

* **house plus forecast** - `housecast` also parses that way, and three of the
  four existing GitHub repositories under the string are dead housing-price
  forecasters. This engine forecasts nothing.
* **type casting** - `cast` is a live Python concept, so a Python reader lands
  on coercion for a beat before they land on the theatre. This engine does no
  type casting worth the name.

`housecast` unhyphenated is the repository, the import name, and the primary
distribution. `house-cast` is held defensively and never shipped.

## Quick start

```
git clone https://github.com/coilyco/housecast.git
cd housecast
uv sync --extra room
uv run --extra room housecast room serve \
  --subjects examples/two-agents/subjects.json --log /tmp/room.jsonl
```

That serves the live room on port 8767 with two example agents, against any
OpenAI-compatible endpoint you name. [`docs/room.md`](docs/room.md) covers the
endpoint, key, and model settings, and [`examples/`](examples/README.md) has the
steps. `just` with no arguments lists the dev verbs, and `just check` is the
offline gate: lint, format check, types, and tests in one recipe.

## Installing it elsewhere

No release is on PyPI yet, only the reserved name. Depend on it from GitHub
with uv:

```toml
[project]
dependencies = ["housecast"]

[tool.uv.sources]
housecast = { git = "https://github.com/coilyco/housecast.git", tag = "housecast-v0.1.0" }
```

That is the same shape the estate already uses for `aos-eval`. Add the `eval`
extra when the consumer needs the grader rather than the base package alone.
Once a `housecast-v*` tag has run the train in
[`docs/publishing.md`](docs/publishing.md), `pip install housecast` is the
shorter path.

## Layout

* `housecast/` - the package: `digest.py`, `grade/`, `mcpeval/`, `mcp/`.
* Evaluations live in the repo that consumes their result, never here.
* `scripts/` - release, kit sync, and the MCP demo recorder.

## License

MIT. Kai Ase Siren holds the copyright. See [`LICENSE`](LICENSE).

## See also

* [`AGENTS.md`](AGENTS.md) - agent-facing operating context for this repository.
* [`docs/FEATURES.md`](docs/FEATURES.md) - what ships today.
