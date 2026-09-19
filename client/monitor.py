#!/usr/bin/env python3
"""Live frame monitor: print every captured TX/RX frame to the screen as it
happens, both directions.

Usage:
    python -m client.monitor                      # passive listen
    python -m client.monitor --poll 4 battery     # send battery every 4s
    python -m client.monitor --duration 30
    python -m client.monitor --body               # also show payload hex
"""
import argparse
import logging
import sys
import time

from .log import configure
from .commands import load_key, send_command, NAMED
from .session import open_session
from .protocol.framing import read_frames

logger = logging.getLogger("client.monitor")


def format_frame(f, show_body=False):
    arrow = "->" if f.direction == "tx" else "<-"
    bits = [time.strftime("%H:%M:%S"), f.direction, arrow,
            f"ptype={f.ptype}", f"seq={f.seq}"]
    if f.channel is not None:
        bits.append(f"ch={f.channel} op={f.op}")
    if f.type is not None:
        bits.append(f"type={f.type} sub={f.subtype}")
    bits.append(f"raw={f.raw}")
    if show_body and f.body:
        bits.append(f"body={f.body}")
    return " ".join(bits)


def main():
    ap = argparse.ArgumentParser(description="Live bidirectional frame monitor")
    ap.add_argument("--poll", type=float, default=0,
                    help="seconds between polls (0 = passive, no commands)")
    ap.add_argument("command", nargs="?", default="battery",
                    help="named command to send on each poll")
    ap.add_argument("--duration", type=float, default=0,
                    help="stop after N seconds (0 = run until Ctrl-C)")
    ap.add_argument("--body", action="store_true", help="also print payload hex")
    ap.add_argument("--key", default=None)
    ap.add_argument("--port", type=int, default=8477)
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="debug logging (frame-level trace)")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="only warnings and errors")
    args = ap.parse_args()

    configure(logging.DEBUG if args.verbose else
              logging.WARNING if args.quiet else logging.INFO)

    if args.command not in NAMED and args.command != "notify":
        sys.exit(f"unknown poll command '{args.command}'; known: {', '.join(NAMED)}")

    d, sess = open_session(key=args.key, port=args.port, verbose=False)
    sess.capture.on_frame = lambda f: print(format_frame(f, args.body), flush=True)

    print(f"# live capture — {'passive' if not args.poll else f'poll {args.command} every {args.poll}s'}"
          f" — Ctrl-C to stop", flush=True)

    deadline = time.time() + args.duration if args.duration else None
    next_poll = time.time()
    try:
        while deadline is None or time.time() < deadline:
            if args.poll and time.time() >= next_poll:
                ctype, csub = NAMED.get(args.command, (2, 1))
                try:
                    send_command(d, sess, ctype, csub, listen=2, expect=None)
                except (IOError, ConnectionError) as exc:
                    logger.error("poll failed: %s", exc)
                next_poll = time.time() + args.poll
            read_frames(d, sess, time.time() + 1, stop_after_first=False,
                        expect=None)
    except KeyboardInterrupt:
        pass
    finally:
        d.close()
        print("# stopped", flush=True)


if __name__ == "__main__":
    main()
