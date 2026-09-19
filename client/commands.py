#!/usr/bin/env python3
"""Xiaomi command builders, the shared `send_command()`, and the batch CLI.

Usage:
    python -m client.commands battery
    python -m client.commands info battery state
    python -m client.commands findwatch
    python -m client.commands --type 2 --subtype 2

Named commands map to Xiaomi Command{type,subtype}. The band allows exactly one
login per BLE connection, so all commands in one invocation share one
authenticated session (authenticate once, then send sequentially).
"""
import argparse
import datetime
import logging
import os
import sys
import time

from .log import configure
from .protocol.constants import CH_PROTOBUF, UUID_TX, UUID_RX
from .protocol.protobuf import pb_bytes, pb_varint
from .protocol.framing import read_frames
from .protocol.daemon import Daemon
from .protocol.handshake import Session, authenticate

# `python -m client.commands` sets __name__ to "__main__", which would bypass
# the `client` logger handler; keep a stable name for the CLI entry point.
logger = logging.getLogger("client.commands")

NAMED = {
    "battery":   (2, 1),
    "info":      (2, 2),
    "clock":     (2, 3),
    "language":  (2, 6),
    "findphone": (2, 17),
    "findwatch": (2, 18),
    "state":     (2, 78),
    "music":     (18, 1),
}


def command(ctype: int, subtype: int, body: bytes = b"") -> bytes:
    """Encode a Xiaomi Command{type, subtype, ...body}."""
    return pb_varint(1, ctype) + pb_varint(2, subtype) + body


def build_notification(nid, pkg, app, title, body, ts=None):
    """Command{type=7, subtype=0, notification{notification2{notification3{...}}}}."""
    ts = ts or time.strftime("%Y%m%dT%H%M%S")
    n3 = (pb_bytes(1, pkg.encode())
          + pb_bytes(2, app.encode())
          + pb_bytes(3, title.encode())
          + pb_bytes(4, b"")
          + pb_bytes(5, body.encode())
          + pb_bytes(6, ts.encode())
          + pb_varint(7, nid))
    notification = pb_bytes(3, pb_bytes(1, n3))
    return pb_bytes(9, notification)


def build_call(name, number, ts=None):
    """Incoming-call notification: Notification3{isCall=true, package=phone}."""
    ts = ts or time.strftime("%Y%m%dT%H%M%S")
    n3 = (pb_bytes(1, b"phone")
          + pb_bytes(2, b"phone")
          + pb_bytes(3, name.encode())
          + pb_bytes(4, b"")
          + pb_bytes(5, number.encode())
          + pb_bytes(6, ts.encode())
          + pb_varint(7, 0)
          + pb_varint(8, 1))
    notification = pb_bytes(3, pb_bytes(1, n3))
    return pb_bytes(9, notification)


def build_call_end():
    """Dismiss the call: NotificationDismiss{NotificationId{id=0, package=phone}}."""
    return build_dismiss(0, "phone")


def build_dismiss(nid=0, pkg="com.termux"):
    """Dismiss a notification: NotificationDismiss{NotificationId{id, package}}."""
    nid_msg = pb_varint(1, nid) + pb_bytes(2, pkg.encode())
    dismiss = pb_bytes(1, nid_msg)
    return pb_bytes(9, pb_bytes(4, dismiss))


def _zigzag(n):
    return (n << 1) ^ (n >> 31)


def build_clock(is_24h=True, tzname=None):
    """Command{type=2, subtype=3, system{clock{date,time,timezone,isNot24hour}}}."""
    now = datetime.datetime.now().astimezone()
    off = now.utcoffset() or datetime.timedelta(0)
    dst = now.dst() or datetime.timedelta(0)
    zone_blocks = int(off.total_seconds() // 60 // 15)
    dst_blocks = int(dst.total_seconds() // 60 // 15)
    date = (pb_varint(1, now.year) + pb_varint(2, now.month)
            + pb_varint(3, now.day))
    tm = (pb_varint(1, now.hour) + pb_varint(2, now.minute)
          + pb_varint(3, now.second) + pb_varint(4, now.microsecond // 1000))
    tz = (pb_varint(1, _zigzag(zone_blocks)) + pb_varint(2, _zigzag(dst_blocks))
          + pb_bytes(3, (tzname or now.tzname() or "UTC").encode()))
    clock = (pb_bytes(1, date) + pb_bytes(2, tm) + pb_bytes(3, tz)
             + pb_varint(4, 0 if is_24h else 1))
    return pb_bytes(4, pb_bytes(4, clock))


def load_key(arg):
    """Resolve the 16-byte auth key from --key, $MB_AUTHKEY, or notes/.authkey.

    Raises ValueError with a clear message if it is missing or malformed,
    rather than an opaque FileNotFoundError from deep in the call chain.
    """
    k = arg or os.environ.get("MB_AUTHKEY")
    if not k:
        p = os.path.join(os.path.dirname(__file__), "..", "notes", ".authkey")
        try:
            with open(p) as fh:
                k = fh.read().strip()
        except OSError as exc:
            raise ValueError(
                f"no auth key: pass --key, set MB_AUTHKEY, or create {p} ({exc})")
    k = k[2:] if k.startswith("0x") else k
    try:
        secret = bytes.fromhex(k)
    except ValueError as exc:
        raise ValueError(f"auth key is not valid hex: {exc}") from exc
    if len(secret) != 16:
        raise ValueError(f"auth key must be 16 bytes, got {len(secret)}")
    return secret


def send_command(d, sess, ctype, csub, body=b"", listen=8, expect="auto"):
    """Send one `Command` over the session; return decoded `Response` list.

    `expect` defaults to the command's own (type, subtype), so unrelated async
    frames are filtered out of the reply; pass `expect=None` to return every
    frame in the window instead. Raises IOError if the write did not land,
    ConnectionError on link loss.
    """
    if expect == "auto":
        expect = (ctype, csub)
    logger.debug("TX command type=%d subtype=%d expect=%s body=%s",
                 ctype, csub, expect, body.hex())
    pkt = sess.data_packet(CH_PROTOBUF, command(ctype, csub, body), encrypted=True)
    if not d.write_reliable(UUID_TX, pkt):
        sess.seq -= 1  # never landed; reuse this sequence number next time
        logger.error("BLE write failed (type=%d subtype=%d)", ctype, csub)
        raise IOError("BLE write failed")
    return read_frames(d, sess, time.time() + listen, expect=expect)


def send_and_listen(d, sess, label, ctype, csub, body, listen):
    logger.info("-> %s Command{type=%d, subtype=%d} body=%s",
                label, ctype, csub, body.hex())
    try:
        replies = send_command(d, sess, ctype, csub, body, listen)
    except IOError:
        logger.error("%s: write failed", label)
        return
    except ConnectionError as exc:
        logger.error("%s: %s", label, exc)
        return
    for r in replies:
        lines = [f"<= {label} RX ch={r.channel} enc={r.encrypted} "
                 f"type={r.type} subtype={r.subtype}",
                 f"   hex: {r.hex}"]
        lines += [f"   {ln}" for ln in r.tree()]
        logger.info("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("commands", nargs="*", help="named command(s)")
    ap.add_argument("--type", type=int)
    ap.add_argument("--subtype", type=int)
    ap.add_argument("--body", default="", help="extra protobuf bytes (hex)")
    ap.add_argument("--listen", type=float, default=8, help="seconds per command")
    ap.add_argument("--no-session", action="store_true",
                    help="skip the type-2 start request (Mi Fitness sends it "
                         "inside enableNotifications before auth)")
    ap.add_argument("--key", default=None)
    ap.add_argument("--port", type=int, default=8477)
    ap.add_argument("--id", type=int, default=1, help="notification id")
    ap.add_argument("--pkg", default="com.termux", help="notification package")
    ap.add_argument("--app", default="Termux", help="notification app name")
    ap.add_argument("--title", default="Test notification", help="notification title")
    ap.add_argument("--text", default="Sent from Termux over direct BLE",
                    help="notification body")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="debug logging (frame-level trace)")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="only warnings and errors")
    args = ap.parse_args()

    configure(logging.DEBUG if args.verbose else
              logging.WARNING if args.quiet else logging.INFO)

    plan = []
    if args.commands:
        for name in args.commands:
            if name == "notify":
                body = build_notification(args.id, args.pkg, args.app,
                                          args.title, args.text)
                plan.append(("notify", 7, 0, body))
            elif name == "call":
                plan.append(("call", 7, 0, build_call(args.title, args.text)))
            elif name == "callend":
                plan.append(("callend", 7, 1, build_call_end()))
            elif name == "dismiss":
                plan.append(("dismiss", 7, 1,
                             build_dismiss(args.id, args.pkg)))
            elif name == "findwatch":
                plan.append(("findwatch", 2, 18, pb_bytes(4, pb_varint(5, 0))))
            elif name == "findwatchstop":
                plan.append(("findwatchstop", 2, 18, pb_bytes(4, pb_varint(5, 1))))
            elif name == "clock":
                plan.append(("clock", 2, 3, build_clock()))
            elif name in NAMED:
                plan.append((name, NAMED[name][0], NAMED[name][1], b""))
            else:
                sys.exit(f"unknown command '{name}'; known: notify, "
                         f"{', '.join(NAMED)}")
    elif args.type is not None and args.subtype is not None:
        body = bytes.fromhex(args.body) if args.body else b""
        plan.append((f"type{args.type}.{args.subtype}", args.type, args.subtype, body))
    else:
        sys.exit("give one or more command names, or --type/--subtype")

    try:
        secret = load_key(args.key)
    except ValueError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    d = Daemon(port=args.port)
    try:
        logger.info("connected; mtu=%s (%s)",
                    d.mtu(512), d.wait_event("EVENT mtu"))
        logger.info("subscribe=%s (%s)",
                    d.subscribe(UUID_RX), d.wait_event("EVENT subscribed"))

        sess = Session(d, secret)
        if not authenticate(d, sess, use_session=not args.no_session):
            logger.error("authentication failed")
            sys.exit(1)

        for label, ctype, csub, body in plan:
            send_and_listen(d, sess, label, ctype, csub, body, args.listen)
    finally:
        d.close()


if __name__ == "__main__":
    main()
