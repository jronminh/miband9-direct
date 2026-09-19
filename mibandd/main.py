#!/usr/bin/env python3
"""mibandd entry point: run the backend, or use it as a CLI.

    mibandd serve [--foreground|--daemonize|--idle-timeout N|--stay]
    mibandd ping | version | state | shutdown
    mibandd call <domain> <op> [--args JSON]
    mibandd device  battery|info|state|clock|find|cmd|raw
    mibandd notify  notify|call|callend|dismiss
    mibandd health  list|collect|decode|summary|trend|blob
    mibandd store   history|samples|stats|files|blobs
    mibandd key | schedule | watch | commands            (local utilities)

The daemon subcommands talk to a running `mibandd serve` (auto-starting it if
needed), so the same command works for one-offs and for scripts.
"""
import argparse
import json
import sys
import time

from . import cli
from .lifecycle import serve_main

SERVE_TOKENS = ("serve", "daemon")


# --------------------------------------------------------------- local fns
def _call_raw(args):
    return cli.call(args, args.domain, args.op, **json.loads(args.args))


def _key(args):
    from .setup import extract_key, save_key
    key = extract_key()
    saved = None if args.no_save else save_key(key)
    shown = ("0x" + key) if args.show else f"0x{key[:6]}...{key[-6:]}"
    return {"key": shown, "saved": saved}


def _schedule_install(args):
    from .setup import schedule_install
    return schedule_install(args.period_min, not args.no_persist, args.charging)


def _schedule_status(args):
    from .setup import schedule_status
    return schedule_status()


def _schedule_remove(args):
    from .setup import schedule_remove
    return schedule_remove()


def _commands(args):
    from api import registry
    return [{"type": c.type, "subtype": c.subtype, "name": c.name,
             "status": c.status} for c in registry.COMMANDS]


def _completion(args):
    from .complete import script
    sys.stdout.write(script(args.shell))
    return None


def _complete(args):
    from .complete import candidates
    for candidate in candidates(args.words):
        print(candidate)
    return None


def _watch(args):
    deadline = None if args.duration <= 0 else time.time() + args.duration
    while deadline is None or time.time() < deadline:
        reading = cli.call(args, "device", "battery")
        print(json.dumps({"ts": time.time(), "battery": reading}, default=str))
        if deadline is not None and time.time() + args.interval > deadline:
            break
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            break
    return None


# ---------------------------------------------------------------- parser
def _local(sub, name, help=None):
    parser = sub.add_parser(name, help=help)
    parser.add_argument("--json", action="store_true")
    return parser


def client_parser():
    """The full `mibandd <domain> <op>` command tree."""
    ap = argparse.ArgumentParser(
        prog="mibandd", description="Mi Band 9 Active backend + CLI")
    sub = ap.add_subparsers(dest="root", required=True)

    for name in ("ping", "version", "state", "shutdown"):
        p = cli.add_client_flags(sub.add_parser(name, help="daemon built-in"))
        p.set_defaults(fn=lambda a, n=name: cli.call(a, "", n))

    p = cli.add_client_flags(sub.add_parser("call", help="raw domain/op call"))
    p.add_argument("domain")
    p.add_argument("op")
    p.add_argument("--args", default="{}", help="JSON args object")
    p.set_defaults(fn=_call_raw)

    for domain, add_ops in (("device", cli.add_device_ops),
                            ("notify", cli.add_notify_ops),
                            ("health", cli.add_health_ops),
                            ("store", cli.add_store_ops)):
        group = sub.add_parser(domain)
        add_ops(group.add_subparsers(dest="op", required=True))

    p = _local(sub, "key", help="extract/save the auth key (ADB)")
    p.add_argument("--show", action="store_true")
    p.add_argument("--no-save", action="store_true")
    p.set_defaults(fn=_key)

    p = _local(sub, "schedule", help="periodic collection job (JobScheduler)")
    actions = p.add_subparsers(dest="action", required=True)
    actions.add_parser("status").set_defaults(fn=_schedule_status)
    actions.add_parser("remove").set_defaults(fn=_schedule_remove)
    install = actions.add_parser("install")
    install.add_argument("--period-min", type=float, default=15.0)
    install.add_argument("--charging", action="store_true")
    install.add_argument("--no-persist", action="store_true")
    install.set_defaults(fn=_schedule_install)

    p = cli.add_client_flags(sub.add_parser("watch", help="sample battery"))
    p.add_argument("--interval", type=float, default=60.0)
    p.add_argument("--duration", type=float, default=0.0)
    p.set_defaults(fn=_watch)

    _local(sub, "commands", help="list the command registry").set_defaults(
        fn=_commands)

    p = _local(sub, "completion", help="print a shell completion script")
    p.add_argument("shell", choices=["bash", "zsh", "fish"])
    p.set_defaults(fn=_completion)

    p = sub.add_parser("__complete", help=argparse.SUPPRESS)
    p.add_argument("words", nargs=argparse.REMAINDER)
    p.set_defaults(fn=_complete)
    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return serve_main([])
    if argv[0] in ("-h", "--help"):
        client_parser().print_help()
        print("\nBackend: `mibandd serve --help` (run the daemon).")
        return 0
    if argv[0] in SERVE_TOKENS:
        return serve_main(argv[1:])
    if argv[0].startswith("-"):
        return serve_main(argv)
    return cli.run(client_parser(), argv)
