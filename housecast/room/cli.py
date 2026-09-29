"""`housecast room serve`: run one room from a subjects file and a restart log."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import click

from housecast.room.models import ModelRefusedError, Settings
from housecast.room.server import DEFAULT_PORT, serve
from housecast.room.store import Room
from housecast.room.subjects import SubjectsError, load_subjects


def parse_route_limits(text: str) -> dict[str, int]:
    """`chat/glm-5-3=4,other=8` as {model: most answers in flight}."""
    limits: dict[str, int] = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        model, _, count = part.rpartition("=")
        if not model or not count.isdigit() or int(count) < 1:
            raise click.BadParameter(f"{part!r} is not model=count", param_hint="--route-limits")
        limits[model] = int(count)
    return limits


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def room() -> None:
    """The live room: intake, fan-out, divergence, restart log."""


@room.command(name="serve")
@click.option(
    "--subjects", "subjects_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option(
    "--log",
    "log_path",
    type=click.Path(path_type=Path),
    required=True,
    help="append-only restart log; replayed on start",
)
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=DEFAULT_PORT, show_default=True)
@click.option(
    "--proxy",
    envvar="ROOM_PROXY",
    default="http://ser8:8080",
    show_default=True,
    help="OpenAI-compatible proxy base URL",
)
@click.option(
    "--model", envvar="ROOM_MODEL", default="evaluation/deepseek-v4-pro", show_default=True
)
@click.option(
    "--fallback-model",
    envvar="ROOM_FALLBACK_MODEL",
    default=None,
    help="a non-Anthropic route the whole round moves to when an answer fails; unset is none",
)
@click.option("--jev-model", envvar="ROOM_JEV_MODEL", default="jev-1.13.0", show_default=True)
@click.option(
    "--route-limits",
    envvar="ROOM_ROUTE_LIMITS",
    default="",
    help="most answers in flight per route, as model=count,model=count; others are uncapped",
)
@click.option(
    "--retries",
    envvar="ROOM_RETRIES",
    default=1,
    show_default=True,
    type=click.IntRange(min=0),
    help="extra asks after a transient proxy error such as a 429 or 5xx, backing off 2s, 4s, ...",
)
@click.option(
    "--user",
    "user_tag",
    envvar="ROOM_USER",
    default="housecast-room",
    show_default=True,
    help="the `user` field on every chat completion, for tracing",
)
@click.option(
    "--rate-seconds", default=20.0, show_default=True, help="one prompt per client per window"
)
@click.option(
    "--address-burst",
    default=30,
    show_default=True,
    help="prompts per address per window; the ceiling on minted device tokens",
)
@click.option(
    "--devices-per-address",
    default=100,
    show_default=True,
    help="distinct grading devices per address per round",
)
@click.option(
    "--trusted-hops",
    envvar="ROOM_TRUSTED_HOPS",
    default=1,
    show_default=True,
    type=click.IntRange(min=1),
    help="X-Forwarded-For entries appended by trusted proxies; the viewer is the leftmost of them",
)
@click.option(
    "--client-header",
    envvar="ROOM_CLIENT_HEADER",
    default="",
    help="a header a trusted proxy sets to the viewer address, e.g. CloudFront-Viewer-Address",
)
def serve_cmd(
    subjects_path: Path,
    log_path: Path,
    host: str,
    port: int,
    proxy: str,
    model: str,
    fallback_model: str | None,
    jev_model: str,
    route_limits: str,
    retries: int,
    user_tag: str,
    rate_seconds: float,
    address_burst: int,
    devices_per_address: int,
    trusted_hops: int,
    client_header: str,
) -> None:
    """Serve the room. ROOM_CONTROL_TOKEN gates the presenter controls."""
    try:
        subjects = load_subjects(subjects_path)
    except SubjectsError as refused:
        raise click.ClickException(str(refused)) from refused
    state = Room(subjects=subjects, log_path=log_path)
    state.load()
    token = os.environ.get("ROOM_CONTROL_TOKEN") or secrets.token_urlsafe(9)
    if "ROOM_CONTROL_TOKEN" not in os.environ:
        click.echo(f"control token: {token}", err=True)
    try:
        cfg = Settings(
            proxy=proxy.rstrip("/"),
            model=model,
            jev_model=jev_model,
            key=os.environ.get("ROOM_PROXY_KEY"),
            user=user_tag,
            fallback_model=fallback_model or None,
            route_limits=parse_route_limits(route_limits),
            retries=retries,
        )
    except ModelRefusedError as refused:
        raise click.BadParameter(str(refused), param_hint="--fallback-model") from refused
    click.echo(f"room: {len(subjects)} subjects, rev {state.rev}, http://{host}:{port}", err=True)
    serve(
        state,
        cfg,
        token,
        host,
        port,
        rate_seconds,
        address_burst,
        devices_per_address,
        trusted_hops,
        client_header,
    )
