"""Tests that read the agent-compose source or its binary skip when neither is present."""

from __future__ import annotations

import os
import pathlib
import shutil

import pytest

SRC = os.environ.get("AGENT_COMPOSE_SRC")


def _src() -> pathlib.Path | None:
    return pathlib.Path(SRC) if SRC and pathlib.Path(SRC).is_dir() else None


@pytest.fixture(scope="session")
def agent_compose_src() -> pathlib.Path:
    src = _src()
    if src is None:
        pytest.skip("AGENT_COMPOSE_SRC does not name an agent-compose source checkout")
    return src


@pytest.fixture(scope="session")
def agent_compose_bin() -> str:
    found = shutil.which("agent-compose")
    if found is None:
        pytest.skip("agent-compose is not on PATH")
    return found
