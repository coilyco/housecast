"""Check a room's edge before an event: the public pages, the room API, and the two gates.

Reads only. Every request is a bare GET with no token, cookie or body, and no redirect
is followed, so a 302 is seen as a 302. Prints PASS or FAIL per check, then exits 1 if
any check failed. The redirect target is printed without its query, since a login URL
can carry state that does not belong in a log. `--help` names the checks. There is no
docs page, since docs/ is at its cap.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, NamedTuple
from urllib.parse import urlsplit

LEGEND = """\
Checks, in order:
  public /          --public origin answers 200
  public /screen    --public origin answers 200
  public /api/room  --public origin answers 200 with a JSON snapshot, prints rev and phase
  public /present   --public origin answers 403, the presenter page is not public
  gated /present    --gated origin answers 302 to a login page, not 200 and not an error
"""

CA_FALLBACK = "/etc/ssl/cert.pem"  # the macOS system bundle


def tls_context() -> ssl.SSLContext:
    """The default trust, plus the system bundle when the default holds no certificate.

    A python.org build on macOS has no CA file until its installer runs, and `uv run` picks
    it from some directories. Every https GET then fails with CERTIFICATE_VERIFY_FAILED, which
    reads as a dead room.
    """
    context = ssl.create_default_context()
    if context.cert_store_stats()["x509_ca"] == 0 and os.path.exists(CA_FALLBACK):
        context.load_verify_locations(cafile=CA_FALLBACK)
    return context


class Reply(NamedTuple):
    status: int
    headers: dict[str, str]
    body: bytes


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def get(url: str, timeout: float) -> Reply:
    """One GET. A 3xx, 4xx or 5xx comes back as a Reply. A transport error raises."""
    opener = urllib.request.build_opener(
        _NoRedirect, urllib.request.HTTPSHandler(context=tls_context())
    )
    request = urllib.request.Request(url, method="GET", headers={"Accept": "*/*"})
    try:
        with opener.open(request, timeout=timeout) as reply:
            return Reply(reply.status, dict(reply.headers), reply.read())
    except urllib.error.HTTPError as err:
        return Reply(err.code, dict(err.headers), b"")


Verdict = tuple[bool, str]


def expect_status(want: int) -> Callable[[Reply], Verdict]:
    def check(reply: Reply) -> Verdict:
        ok = reply.status == want
        return ok, f"status {reply.status}" + ("" if ok else f", wanted {want}")

    return check


def room_snapshot(reply: Reply) -> Verdict:
    """Passes with the rev and phase the room reports, so a person can read which room it is."""
    if reply.status != 200:
        return False, f"status {reply.status}, wanted 200"
    try:
        body = json.loads(reply.body)
    except ValueError:
        return False, "status 200 but the body is not JSON, is a sign-in page in front of it?"
    if not isinstance(body, dict) or "rev" not in body or "phase" not in body:
        return False, "status 200 but the body is not a room snapshot"
    return True, f"status 200, rev {body['rev']} phase {body['phase']}"


def login_redirect(reply: Reply) -> Verdict:
    location = next((v for k, v in reply.headers.items() if k.lower() == "location"), "")
    if reply.status != 302 or not location:
        return False, f"status {reply.status}, wanted 302 with a Location"
    parts = urlsplit(location)
    return True, f"status 302 to {parts.netloc}{parts.path}"


def checks(public: str, gated: str) -> list[tuple[str, str, Callable[[Reply], Verdict]]]:
    return [
        ("public /", f"{public}/", expect_status(200)),
        ("public /screen", f"{public}/screen", expect_status(200)),
        ("public /api/room", f"{public}/api/room", room_snapshot),
        ("public /present", f"{public}/present", expect_status(403)),
        ("gated /present", f"{gated}/present", login_redirect),
    ]


def run(public: str, gated: str, timeout: float, emit: Callable[[str], None] = print) -> bool:
    """Runs every check, even after a failure, so one report shows everything wrong."""
    everything = True
    for name, url, judge in checks(public, gated):
        try:
            passed, detail = judge(get(url, timeout))
        except (urllib.error.URLError, OSError, TimeoutError) as err:
            passed = False
            detail = str(err.reason if isinstance(err, urllib.error.URLError) else err)
        emit(f"{'PASS' if passed else 'FAIL'} {name}: {detail}")
        everything = everything and passed
    return everything


def origin(parser: argparse.ArgumentParser, flag: str, value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path not in {"", "/"}:
        parser.error(f"{flag} is an http or https origin with no path")
    return f"{parts.scheme}://{parts.netloc}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0],
        epilog=LEGEND,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--public", required=True, help="attendee origin, e.g. https://room.example")
    parser.add_argument("--gated", required=True, help="signed-in origin, e.g. https://room.example.dev")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds to wait on one GET")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout is positive")
    passed = run(
        origin(parser, "--public", args.public),
        origin(parser, "--gated", args.gated),
        args.timeout,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
