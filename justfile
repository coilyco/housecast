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
    @uv run --all-extras ruff format housecast "$@"

# Check Python formatting without rewriting.
format-check *ARGS:
    @uv run --all-extras ruff format --check housecast "$@"

# Run the Python linter.
lint *ARGS:
    @uv run --all-extras ruff check housecast "$@"

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

# Serve a built deck to a room, with anonymous voting. `just grade-present DECK`.
grade-present *ARGS:
    @uv run --extra eval housecast grade present "$@"

# Export the room pages as a static site (default dist/room-site) for S3 and CloudFront.
room-site *ARGS:
    @uv run --all-extras python scripts/room_site.py "$@"
