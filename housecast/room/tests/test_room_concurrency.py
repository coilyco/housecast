"""What concurrent attendees do to the room's revs and to a listening page."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from housecast.room.tests.serving import TOKEN, Served, free_port, stub

CLIENTS = 30


async def graders(base: str) -> list[int]:
    headers = {"x-control-token": TOKEN}
    async with httpx.AsyncClient(base_url=base, timeout=30, headers=headers) as ctl:
        await ctl.post("api/control/phase", json={"phase": "submissions"})
        prompt = (await ctl.post("api/prompts", json={"text": "probe", "device": "p0"})).json()
        await asyncio.sleep(0.3)
        await ctl.post("api/control/pick", json={"prompt_id": prompt["id"]})

        async def grade(i: int) -> int:
            async with httpx.AsyncClient(base_url=base, timeout=30) as one:
                body = {"round": 1, "device": f"d{i}", "grades": {"s1": "pass"}}
                return int((await one.post("api/grades", json=body)).json()["graded"])

        return list(await asyncio.gather(*(grade(i) for i in range(CLIENTS))))


def test_concurrent_grades_take_distinct_contiguous_revs(tmp_path: Path) -> None:
    """A rev is how a page tells it missed something, so two events must never share one."""
    log = tmp_path / "room.jsonl"
    served = Served(log, free_port(), stub()).start()
    try:
        counted = asyncio.run(graders(served.base))
    finally:
        served.stop()
    revs = [json.loads(line)["rev"] for line in log.read_text().splitlines()]
    assert sorted(counted) == list(range(1, CLIENTS + 1))
    assert revs == list(range(1, len(revs) + 1)), "revs repeat or skip under concurrent grades"
