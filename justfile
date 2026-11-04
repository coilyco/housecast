# Per-repo task manifest. Run `just` (or `just --list`) to see every verb.
#
# One line of comment per recipe on purpose: just reads only the LAST comment
# line above a recipe, so a wrapped description silently truncates to its tail.
#
# `ward exec` is retired, and so is the `.ward/ward.yaml` that outlived it.

set positional-arguments

# Default target: list every available recipe.
default:
    @just --list --unsorted

# Run the offline gates: lint, format check, types, tests.
check *ARGS:
    @sh scripts/check.sh "$@"

# Run the unit test suite.
test *ARGS:
    @uv run --all-extras pytest "$@"

# Format Python sources.
format *ARGS:
    @uv run --all-extras ruff format housecast evalkit "$@"

# Check Python formatting without rewriting.
format-check *ARGS:
    @uv run --all-extras ruff format --check housecast evalkit "$@"

# Run the Python linter.
lint *ARGS:
    @uv run --all-extras ruff check housecast evalkit "$@"

# Run the Python type checker.
typecheck *ARGS:
    @uv run --all-extras mypy "$@"

# Run the repository validation hooks over all files.
pre-commit *ARGS:
    @pre-commit run --all-files "$@"

# Install the pre-commit and pre-push hooks into a fresh clone.
pre-commit-install *ARGS:
    @pre-commit install --hook-type pre-commit --hook-type pre-push "$@"

# Seal an MCP tool board into a standalone page. `just mcp-board RUN out.html kai`.
mcp-board RUN OUT GRADER="":
    @uv run --extra eval --extra mcp python -m housecast grade seal "{{RUN}}" \
      --out "{{OUT}}" --profile housecast/data/mcp-tools-profile.yaml \
      {{ if GRADER != "" { "--grader " + GRADER } else { "" } }}

# Re-vendor the coilyco kit's primitives into the grading page. `just sync-kit ../website`.
sync-kit *ARGS:
    @uv run python scripts/sync_kit.py "$@"

# Report grading-page palette drift from the kit. Skips with no website checkout.
sync-kit-check *ARGS:
    @uv run python scripts/sync_kit.py --check "$@"

# Sync the engine and eval dependencies.
sync *ARGS:
    @uv sync --all-extras "$@"

# Refuse a publish whose tag disagrees with the packaged version. `just release-check housecast-v0.3.0`.
release-check *ARGS:
    @uv run python scripts/release_tag.py "$@"

# Build the sdist and wheel into dist/.
build *ARGS:
    @uv build "$@"

# Upload dist/ to PyPI. Reads the token from UV_PUBLISH_TOKEN, never from argv.
publish *ARGS:
    @uv publish --trusted-publishing never --check-url https://pypi.org/simple/housecast/ "$@"

# Upload dist/ to TestPyPI, the throwaway index. Same token variable, different registry.
publish-test *ARGS:
    @uv publish --trusted-publishing never --publish-url https://test.pypi.org/legacy/ --check-url https://test.pypi.org/simple/housecast/ "$@"

# Project a committed run into a display payload, one way only.
grade-export *ARGS:
    @uv run --extra eval housecast grade export "$@"

# Serve the MCP subject under evaluation, over HTTP MCP.
mcpeval-subject *ARGS:
    @uv run --extra eval --extra mcp housecast mcpeval subject "$@"

# One live request, before a board rather than inside one.
mcpeval-preflight *ARGS:
    @uv run --extra eval --extra mcp housecast mcpeval preflight "$@"

# Run every prompt of one task against one definition set.
mcpeval-run *ARGS:
    @uv run --extra eval --extra mcp housecast mcpeval run "$@"

# Pair two runs of one task, prompt to prompt. Never two averages.
mcpeval-compare *ARGS:
    @uv run --extra eval --extra mcp housecast mcpeval compare "$@"

# Jev tool-routing bench: one Jev choice per question over an MCP subject's tools/list.
jevroute *ARGS:
    @uv run --extra mcp python -m housecast.jevroute.bench "$@"

# Server-first Jev routing: pick an MCP server, then a tool, plus the multi-request question.
jevroute-servers *ARGS:
    @uv run --extra mcp python -m housecast.jevroute.servers "$@"

# Snapshot every MCP server's description and tools for jevroute-servers.
jevroute-inventory *ARGS:
    @uv run --extra mcp python -m housecast.jevroute.inventory "$@"

# The visual flow: task, run, triaged queue, prose editor, comparison.
mcpeval-serve *ARGS:
    @uv run --extra eval --extra mcp housecast mcpeval serve "$@"

# Record the loop page as a demo video against a running mcpeval-serve. `just mcpeval-demo --out DIR`.
mcpeval-demo *ARGS:
    @uv run --with playwright python scripts/record_mcpeval_demo.py "$@"

# Cluster annotation critiques into a ranked failure taxonomy.
grade-taxonomy *ARGS:
    @uv run --extra eval housecast grade taxonomy "$@"

# Pin or check the five grade inputs. `just grade-pin --dataset D --profile P --entities E`.
grade-pin *ARGS:
    @uv run --extra eval housecast grade pin "$@"

# How often two graders split a case. `just grade-disagreement --dataset D --annotations A --annotations B --tester a --tester b`.
grade-disagreement *ARGS:
    @uv run --extra eval housecast grade disagreement "$@"

# Build the room-facing deck. `just grade-deck ROUNDS --run RUN_DIR --out DECK`.
grade-deck *ARGS:
    @uv run --extra eval housecast grade deck "$@"

# Write a graded run into a self-contained copy of the page. `just grade-seal RUN --out B.html`.
grade-seal *ARGS:
    @uv run --extra eval housecast grade seal "$@"

# Screenshot one card of a sealed board, offline. `just grade-shot B.html --out C.png --width 390`.
grade-shot *ARGS:
    @uv run --with playwright==1.57.0 python scripts/shoot_card.py "$@"

# Serve a built deck to a room, with anonymous voting. `just grade-present DECK`.
grade-present *ARGS:
    @uv run --extra eval housecast grade present "$@"

# Export the room pages as a static site (default dist/room-site) for S3 and CloudFront.
room-site *ARGS:
    @uv run --all-extras python scripts/room_site.py "$@"

# Walk the room's phone checklist in Firefox and WebKit against a dev room (writes to its log).
room-engine-pass *ARGS:
    @uv run --with playwright==1.57.0 python scripts/room_engine_pass.py "$@"

# Hold a dev or rehearsal room under 30 simulated attendees for three rounds (writes to its log).
room-load-test *ARGS:
    @uv run --extra room python scripts/room_load_test.py "$@"

# Watch a live room read-only, one GET of /api/room per poll. `just room-watch --base https://room.example`.
room-watch *ARGS:
    @uv run --no-project python scripts/room_watch.py "$@"

# Check a room's edge before an event, read only. `just room-preflight --public https://room.example --gated https://room.example.dev`.
room-preflight *ARGS:
    @uv run --no-project python scripts/room_preflight.py "$@"

# Replay a trajectory ledger file into a live agent-proxy intake, dry run unless --apply (writes to the target). `just ledger-replay --source LEDGER.sqlite3 --url http://HOST:8080`.
ledger-replay *ARGS:
    @uv run --no-project python scripts/ledger_replay.py "$@"

# Run one full grading round on a throwaway room, with real attendee browsers (writes to its log). `just room-e2e --public URL --direct URL --token-file FILE --writes`.
room-e2e *ARGS:
    @uv run --no-project --with playwright==1.57.0 python scripts/room_e2e.py "$@"

# Re-resolve uv.lock after a pyproject dependency pin moves.
lock *ARGS:
    @uv lock "$@"

# Compose one compiled bundle per role as the eval system prompts.
evalkit-prompts *ARGS:
    @sh scripts/eval-prompts.sh "$@"

# One live request through Agent Proxy, before a full board run.
evalkit-smoke *ARGS:
    @sh scripts/eval-smoke.sh "$@"

# Run the board through Inspect against Agent Proxy.
evalkit-run *ARGS:
    @sh scripts/eval-run.sh "$@"

# Open the Inspect log viewer.
evalkit-view *ARGS:
    @uv run --all-extras inspect view --log-dir .evalkit/logs "$@"

# Project a committed run into a display payload, one way only, under this board's profile.
evalkit-export *ARGS:
    @mkdir -p .evalkit && uv run --all-extras python -m evalkit.profile --out .evalkit/profile.yaml
    @uv run --all-extras housecast grade export --profile .evalkit/profile.yaml "$@"

# Read an Inspect eval log and build the dataset the annotator grades.
evalkit-filter *ARGS:
    @uv run --all-extras python -m evalkit.filter "$@"

# Ask whether response dispersion predicted the grade. `just evalkit-validity RUN/annotations.kai.yaml`.
evalkit-validity ANNOTATIONS:
    @uv run --all-extras python evaluations/split-candidates-2026-09-08/validity.py "{{ANNOTATIONS}}"

# PyLadies Remote room M2 check. `just evalkit-room-m2 selftest`, `run <base url> <out>`, `score <out> [export]`.
evalkit-room-m2 *ARGS:
    @uv run --all-extras python evaluations/pyladies-room-m2-2026-09-27/room_m2.py "$@"

# Why seats ask to merge, from transcripts. `just evalkit-merge-asks selftest`, `extract DIR HOURS OUT`, `classify OUT`.
evalkit-merge-asks *ARGS:
    @uv run --all-extras python evaluations/merge-asks-2026-10-02/mergeasks.py "$@"

# Jev as a read-time filter over Basic Memory. `just evalkit-jev-filter selftest HOUSECAST`, `summary OUT_DIR`.
evalkit-jev-filter *ARGS:
    @uv run --all-extras python evaluations/jev-filter-2026-10-02/jevfilter.py "$@"

# Cross-harness memory bench. `just evalkit-memory-bench selftest`, `run FIXTURE c0|c1 LABEL CASES`, `sentinels FIXTURE old|new`, `score FIXTURE LABEL...`.
evalkit-memory-bench *ARGS:
    @uv run --all-extras python evaluations/memory-bench-2026-10-02/bench.py "$@"

# Per-persona backend check for the room. `just evalkit-persona-backends selftest`, `routes`, `run <bundles> <out> <config> <label> [reps]`, `jev <out> <label>`, `score <out> <label>...`.
evalkit-persona-backends *ARGS:
    @uv run --all-extras python evaluations/persona-backends-2026-09-29/backends.py "$@"

# Pressure-variant cases for the room. `just evalkit-persona-pressure selftest`, `run <cases.json> <bundles> <out> <config> <reps> [case_id...]`, `summary <out> <config>...`, `seed <out> <config> <case_id> <rep> <out.json>`.
evalkit-persona-pressure *ARGS:
    @uv run --all-extras python evaluations/persona-backends-2026-09-29/pressure.py "$@"

# Cluster annotation critiques into a ranked failure taxonomy.
evalkit-taxonomy *ARGS:
    @uv run --all-extras housecast grade taxonomy "$@"

# Annotate the eval dataset by hand, one keystroke per challenge.
evalkit-annotate *ARGS:
    @sh scripts/eval-annotate.sh "$@"

# Emit this board's profile as YAML, for a grading surface that takes --profile.
evalkit-profile *ARGS:
    @uv run --all-extras python -m evalkit.profile "$@"

# Project the roster as entities.json, the --entities a grading surface takes.
evalkit-entities *ARGS:
    @sh scripts/eval-entities.sh "$@"

# Grade a JSONL of {half, response} on stdin with the autonomy grader.
evalkit-autonomy *ARGS:
    @uv run --all-extras python -m evalkit.autonomy "$@"

# Reshape challenges.yaml into eval_cases.yaml, housecast's EvalCase wire schema.
evalkit-reshape *ARGS:
    @uv run --all-extras python scripts/reshape_eval_cases.py "$@"

# Grade one committed run in a browser, with this roster's entities and profile. `just grade-serve evaluations/pilot/RUN`.
grade-serve *ARGS:
    @sh scripts/eval-serve.sh "$@"
