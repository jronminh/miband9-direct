#!/usr/bin/env python3
"""Command-line front end for the high-level API.

Usage:
    python -m api battery info
    python -m api notify --title Hi --text hello
    python -m api findwatch
    python -m api --command face-list
    python -m api raw --type 2 --subtype 2
    python -m api events --duration 30
    python -m api commands

Every verb runs inside one authenticated session, so several can be chained in
a single invocation (the band allows only one login per BLE connection). Any
name from the `client.registry` catalogue works as a verb too.
"""
import argparse
import json
import logging
import sys

from . import registry
from .band import MiBand, DEFAULT_PORT
from .errors import BandError
from .events import stream
from .parse import (parse_activity_files, parse_battery, parse_info, to_dicts)

logger = logging.getLogger("api.cli")


def _emit(label, value):
    print(f"== {label}")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _run_verb(band, name, args):
    """Execute one verb; return (label, printable value)."""
    if name == "battery":
        responses = band.battery()
        return name, parse_battery(responses) or to_dicts(responses)
    if name == "info":
        responses = band.info()
        return name, parse_info(responses) or to_dicts(responses)
    if name == "state":
        return name, to_dicts(band.state())
    if name == "clock":
        return name, to_dicts(band.clock())
    if name == "findwatch":
        return name, to_dicts(band.find_watch(True))
    if name == "findwatchstop":
        return name, to_dicts(band.find_watch(False))
    if name == "language":
        return name, to_dicts(band.language(args.code))
    if name == "dnd":
        return name, to_dicts(band.dnd(not args.disable))
    if name == "screen-on":
        return name, to_dicts(band.screen_on_notification(not args.disable))
    if name == "notify":
        return name, to_dicts(band.notify(args.title, args.text, args.app,
                                         args.pkg, args.id))
    if name == "call":
        return name, to_dicts(band.call(args.title, args.text))
    if name == "callend":
        return name, to_dicts(band.call_end())
    if name == "dismiss":
        return name, to_dicts(band.dismiss(args.id, args.pkg))
    if name == "activity-files":
        responses = band.activity_files(past=args.past)
        return name, parse_activity_files(responses) or to_dicts(responses)
    if name == "activity-request":
        if not args.file_id:
            raise BandError("activity-request needs --file-id <hex>")
        return name, to_dicts(band.activity_request(args.file_id))
    if name == "activity-ack":
        if not args.file_id:
            raise BandError("activity-ack needs --file-id <hex>")
        return name, to_dicts(band.activity_ack(args.file_id))
    if name == "raw":
        if args.type is None or args.subtype is None:
            raise BandError("raw needs --type and --subtype")
        return name, to_dicts(band.raw(args.type, args.subtype, args.body))
    if registry.lookup(name) is not None:
        body = bytes.fromhex(args.body) if args.body else b""
        return name, to_dicts(band.command(name, body))
    raise BandError(f"unknown verb {name!r}; try 'commands'")


def build_parser():
    ap = argparse.ArgumentParser(
        prog="python -m api", description="Mi Band 9 Active high-level API")
    ap.add_argument("verbs", nargs="*", help="one or more verbs to run")
    ap.add_argument("--command", default=None,
                    help="run any registry command by name (hyphens ok)")
    ap.add_argument("--key", default=None, help="auth key (default: notes/.authkey)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--listen", type=float, default=4.0, help="seconds per reply")
    ap.add_argument("--duration", type=float, default=15.0,
                    help="seconds for 'events'")
    ap.add_argument("--no-session", action="store_true")
    ap.add_argument("--title", default="Test notification")
    ap.add_argument("--text", default="Sent from Termux over direct BLE")
    ap.add_argument("--app", default="Termux")
    ap.add_argument("--pkg", default="com.termux")
    ap.add_argument("--id", type=int, default=1, help="notification id")
    ap.add_argument("--code", default="en_us", help="language code")
    ap.add_argument("--file-id", default=None, help="activity file id (hex)")
    ap.add_argument("--past", action="store_true", help="past activity files")
    ap.add_argument("--disable", action="store_true", help="toggle off")
    ap.add_argument("--type", type=int, help="raw command type")
    ap.add_argument("--subtype", type=int, help="raw command subtype")
    ap.add_argument("--body", default="", help="raw/generic body (hex)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    return ap


def _make_band(args):
    return MiBand(key=args.key, port=args.port, listen=args.listen,
                  use_session=not args.no_session, verbose=args.verbose)


def main(argv=None):
    args = build_parser().parse_args(argv)
    level = (logging.DEBUG if args.verbose else
             logging.WARNING if args.quiet else logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    if args.command:
        try:
            with _make_band(args) as band:
                _emit(*_run_verb(band, args.command, args))
        except BandError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    if not args.verbs:
        build_parser().print_help()
        return 0
    if args.verbs == ["commands"]:
        for ctype, subtype, name, status in MiBand.known_commands():
            print(f"{ctype:>2},{subtype:<4} {status:<6} {name}")
        return 0

    try:
        with _make_band(args) as band:
            if args.verbs == ["events"]:
                for response in stream(band, duration=args.duration):
                    _emit("event", response.to_dict())
                return 0
            for name in args.verbs:
                _emit(*_run_verb(band, name, args))
    except BandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
