"""The housecast CLI: grade a board.

python -m housecast grade annotate --dataset D --out O
"""

from __future__ import annotations

import argparse
import sys


def _grade(argv: list[str]) -> int:
    """Forward to the click group. It keeps its own parser, so argparse stops here."""
    try:
        import click

        from housecast.grade.cli import main as grade_main
    except ImportError as missing:  # the grading half rides the eval extra
        raise SystemExit(
            f"housecast grade needs the eval extra: pip install 'housecast[eval]' ({missing})"
        ) from missing
    try:
        return grade_main(args=argv, standalone_mode=False) or 0
    except click.ClickException as refused:
        # standalone_mode=False is what lets this return an int rather than
        # exiting, and it also turns off click's own error printing.
        refused.show()
        return refused.exit_code


def _mcpeval(argv: list[str]) -> int:
    """Forward to the click group, exactly as `grade` does."""
    try:
        import click

        from housecast.mcpeval.cli import mcpeval as group
    except ImportError as missing:  # the loop rides the eval and mcp extras
        raise SystemExit(
            f"housecast mcpeval needs the eval and mcp extras: "
            f"pip install 'housecast[eval,mcp]' ({missing})"
        ) from missing
    try:
        return group.main(args=argv, standalone_mode=False) or 0
    except click.ClickException as refused:
        refused.show()
        return refused.exit_code


def _room(argv: list[str]) -> int:
    """Forward to the click group, exactly as `grade` does."""
    try:
        import click

        from housecast.room.cli import room as group
    except ImportError as missing:  # the room rides the room extra
        raise SystemExit(
            f"housecast room needs the room extra: pip install 'housecast[room]' ({missing})"
        ) from missing
    try:
        return group.main(args=argv, standalone_mode=False) or 0
    except click.ClickException as refused:
        refused.show()
        return refused.exit_code


def main(argv: list[str] | None = None) -> int:
    from housecast.crash import init_crash_reporting

    init_crash_reporting()
    # `grade` owns its own parser, so it is split off before argparse sees it.
    raw = sys.argv[1:] if argv is None else argv
    if raw and raw[0] == "grade":
        return _grade(raw[1:])
    if raw and raw[0] == "mcpeval":
        return _mcpeval(raw[1:])
    if raw and raw[0] == "room":
        return _room(raw[1:])

    parser = argparse.ArgumentParser(prog="housecast")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("grade", help="grade a board dataset (needs the eval extra)")
    sub.add_parser("mcpeval", help="the MCP tool-description loop (needs the eval and mcp extras)")
    sub.add_parser("room", help="the live room (needs the room extra)")

    # Reachable only for an unrecognized command or --help: both `grade` and
    # `mcpeval` return above before argparse ever sees argv.
    parser.parse_args(argv)
    return 2


if __name__ == "__main__":
    sys.exit(main())
