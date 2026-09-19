#!/usr/bin/env python3
"""Shared plumbing for the mibandd CLIs (the daemon CLI and per-field clients)."""
import argparse
import json
import sys

from . import client


def add_client_flags(parser):
    """Connection/output flags shared by every client op."""
    parser.add_argument("--host", default=client.DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=client.DEFAULT_PORT)
    parser.add_argument("--no-spawn", action="store_true",
                        help="do not auto-start mibandd if it is down")
    parser.add_argument("--json", action="store_true", help="compact JSON output")
    return parser


def _op(sub, name, help=None):
    return add_client_flags(sub.add_parser(name, help=help))


def call(args, domain, op, **kwargs):
    """Dispatch one op using the connection flags parsed into `args`."""
    return client.call(domain, op, kwargs, host=args.host, port=args.port,
                       spawn=not args.no_spawn)


def run(parser, argv=None):
    """Parse, run the selected op (`args.fn`), print the result."""
    args = parser.parse_args(argv)
    try:
        result = args.fn(args)
    except client.RpcFailure as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1
    except (client.DaemonUnavailable, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result is not None:
        indent = None if getattr(args, "json", False) else 2
        print(json.dumps(result, ensure_ascii=False, indent=indent, default=str))
    return 0


# --------------------------------------------------------------- domain ops
def add_device_ops(sub):
    """Add the `device` domain ops to a subparsers object."""
    _op(sub, "battery").set_defaults(fn=lambda a: call(a, "device", "battery"))
    _op(sub, "info").set_defaults(fn=lambda a: call(a, "device", "info"))
    _op(sub, "state").set_defaults(fn=lambda a: call(a, "device", "state"))

    p = _op(sub, "clock")
    p.add_argument("--h12", action="store_true")
    p.set_defaults(fn=lambda a: call(a, "device", "clock", h12=a.h12))

    p = _op(sub, "find")
    p.add_argument("--stop", action="store_true")
    p.set_defaults(fn=lambda a: call(a, "device", "find", stop=a.stop))

    p = _op(sub, "cmd", help="send a registry command by name")
    p.add_argument("--command", required=True)
    p.add_argument("--body", default="", help="payload hex")
    p.set_defaults(fn=lambda a: call(a, "device", "cmd",
                                     name=a.command, body=a.body))

    p = _op(sub, "raw", help="send an arbitrary type/subtype")
    p.add_argument("--type", type=int, required=True)
    p.add_argument("--subtype", type=int, required=True)
    p.add_argument("--body", default="", help="payload hex")
    p.set_defaults(fn=lambda a: call(a, "device", "raw", type=a.type,
                                     subtype=a.subtype, body=a.body))


def add_notify_ops(sub):
    """Add the `notify` domain ops to a subparsers object."""
    p = _op(sub, "notify")
    p.add_argument("--title", default="Test notification")
    p.add_argument("--text", default="Sent from Termux over direct BLE")
    p.add_argument("--app", default="Termux")
    p.add_argument("--pkg", default="com.termux")
    p.add_argument("--id", type=int, default=1)
    p.set_defaults(fn=lambda a: call(a, "notify", "notify", title=a.title,
                                     text=a.text, app=a.app, pkg=a.pkg,
                                     nid=a.id))

    p = _op(sub, "call")
    p.add_argument("--name", default="Unknown")
    p.add_argument("--number", default="")
    p.set_defaults(fn=lambda a: call(a, "notify", "call", name=a.name,
                                     number=a.number))

    _op(sub, "callend").set_defaults(fn=lambda a: call(a, "notify", "callend"))

    p = _op(sub, "dismiss")
    p.add_argument("--id", type=int, default=0)
    p.add_argument("--pkg", default="com.termux")
    p.set_defaults(fn=lambda a: call(a, "notify", "dismiss", nid=a.id,
                                     pkg=a.pkg))


def _blob_op(args):
    result = call(args, "health", "blob",
                  file_ts=args.file_ts, suffix=args.suffix)
    if args.out:
        with open(args.out, "wb") as fh:
            fh.write(bytes.fromhex(result["hex"]))
        return {"file_ts": result["file_ts"], "suffix": result["suffix"],
                "out": args.out, "size": result["size"]}
    return result


def add_health_ops(sub):
    """Add the `health` domain ops to a subparsers object."""
    p = _op(sub, "list", help="list the band's recorded file ids")
    p.add_argument("--past", action="store_true")
    p.set_defaults(fn=lambda a: call(a, "health", "list", past=a.past))

    p = _op(sub, "collect")
    p.add_argument("--past", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument("--max-misses", type=int, default=2)
    p.add_argument("--raw", action="store_true",
                   help="store raw files only; skip decoding")
    p.set_defaults(fn=lambda a: call(a, "health", "collect", past=a.past,
                                     limit=a.limit, timeout=a.timeout,
                                     max_misses=a.max_misses, raw=a.raw))

    p = _op(sub, "decode", help="decode stored summaries into samples")
    p.add_argument("--file-ts", type=int, default=None)
    p.set_defaults(fn=lambda a: call(a, "health", "decode", file_ts=a.file_ts))

    p = _op(sub, "summary", help="latest day's decoded fields")
    p.add_argument("--file-ts", type=int, default=None)
    p.set_defaults(fn=lambda a: call(a, "health", "summary", file_ts=a.file_ts))

    p = _op(sub, "trend", help="one metric over time")
    p.add_argument("--metric", required=True)
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(fn=lambda a: call(a, "health", "trend", metric=a.metric,
                                     limit=a.limit))

    p = _op(sub, "blob")
    p.add_argument("--file-ts", type=int, required=True)
    p.add_argument("--suffix", required=True)
    p.add_argument("--out", default=None, help="write raw bytes here")
    p.set_defaults(fn=_blob_op)


def add_store_ops(sub):
    """Add the `store` domain ops to a subparsers object."""
    p = _op(sub, "history")
    p.add_argument("--name", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=lambda a: call(a, "store", "history", name=a.name,
                                     limit=a.limit))

    p = _op(sub, "samples")
    p.add_argument("--metric", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=lambda a: call(a, "store", "samples", metric=a.metric,
                                     limit=a.limit))

    _op(sub, "stats").set_defaults(fn=lambda a: call(a, "store", "stats"))

    p = _op(sub, "files")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=lambda a: call(a, "store", "files", limit=a.limit))

    p = _op(sub, "blobs")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=lambda a: call(a, "store", "blobs", limit=a.limit))
