#!/usr/bin/env python3
"""Interactive session shell: retries the handshake, then reads verbs from stdin.

Usage:
    python -m client.shell [--listen 6] [--auth-timeout 300]
    # then type: info / battery / state / findwatch / type:2:18 / quit

Non-interactively:
    printf 'info\nbattery\n' | python -m client.shell
"""
import argparse
import logging
import sys

from .log import configure
from .commands import NAMED, send_and_listen
from .session import open_session

logger = logging.getLogger("client.shell")


def parse_command(line):
    """Return (label, type, subtype, body), or None for a blank line.

    Raises ValueError for anything unrecognised, including malformed hex or
    non-integer type/subtype, so callers get one clear failure mode.
    """
    line = line.strip()
    if not line:
        return None
    low = line.lower()
    if low in NAMED:
        ctype, csub = NAMED[low]
        return low, ctype, csub, b""
    parts = line.split(":")
    if parts[0].lower() in ("type", "t") and len(parts) >= 3:
        try:
            body = bytes.fromhex(parts[3]) if len(parts) > 3 and parts[3] else b""
            return line, int(parts[1]), int(parts[2]), body
        except ValueError as exc:
            raise ValueError(f"bad command {line!r}: {exc}") from exc
    raise ValueError(f"unrecognised: {line!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=float, default=6, help="seconds per command")
    ap.add_argument("--auth-timeout", type=float, default=300,
                    help="seconds to keep retrying the handshake")
    ap.add_argument("--no-session", action="store_true",
                    help="skip the type-2 start request (Mi Fitness sends it "
                         "inside enableNotifications before auth)")
    ap.add_argument("--key", default=None)
    ap.add_argument("--port", type=int, default=8477)
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="debug logging (frame-level trace)")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="only warnings and errors")
    args = ap.parse_args()

    configure(logging.DEBUG if args.verbose else
              logging.WARNING if args.quiet else logging.INFO)

    d, sess = open_session(key=args.key, port=args.port,
                           use_session=not args.no_session,
                           auth_timeout=args.auth_timeout, verbose=False)

    logger.info("SESSION READY — type commands (info, battery, state, "
                "findwatch, type:2:18, quit)")

    try:
        for line in sys.stdin:
            if line.strip().lower() in ("quit", "exit", "q"):
                break
            try:
                cmd = parse_command(line)
            except ValueError as exc:
                logger.warning("%s", exc)
                continue
            if cmd is None:
                continue
            label, ctype, csub, body = cmd
            send_and_listen(d, sess, label, ctype, csub, body, args.listen)
    finally:
        d.close()


if __name__ == "__main__":
    main()
