#!/bin/sh
# Offline gates. The pre-commit suite is managed by agentic-os, so repo-local
# Python linting runs here instead of being hand-added to that file.
#
# --all-extras because the grader's imports are in the `eval` extra: the engine
# stays installable without them, and the gates still have to see it.
set -e
uv run --all-extras ruff check housecast evalkit
uv run --all-extras ruff format --check housecast evalkit
uv run --all-extras mypy
uv run --all-extras pytest -q
