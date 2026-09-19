#!/usr/bin/env python3
"""Daemon lifecycle: logging, pid file, signals, idle-exit.

    python -m mibandd --foreground --idle-timeout 600
    python -m mibandd --daemonize
"""
import argparse
import logging
import os
import re
import signal
import sys

from .domains import register_all
from .rpc import RpcServer, VERSION
from .session import SessionManager

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8478
DEFAULT_IDLE = 600.0

LOG_DIR = os.path.join(os.path.expanduser("~"), ".miband")
PID_FILE = os.path.join(LOG_DIR, "mibandd.pid")
LOG_FILE = os.path.join(LOG_DIR, "mibandd.log")

logger = logging.getLogger("mibandd")


class _MaskKeyFilter(logging.Filter):
    """Replace 32-hex runs (the auth key) in log records."""

    _re = re.compile(r"\b[0-9a-fA-F]{32}\b")

    def filter(self, record):
        try:
            record.msg = self._re.sub("0x<redacted>", str(record.msg))
            record.args = ()
        except Exception:
            pass
        return True


def _configure_logging(foreground, verbose):
    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    mask = _MaskKeyFilter()
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    os.makedirs(LOG_DIR, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(fmt)
    file_handler.addFilter(mask)
    root.addHandler(file_handler)
    if foreground:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        stream_handler.addFilter(mask)
        root.addHandler(stream_handler)


def _daemonize():
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)


def _write_pid():
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(PID_FILE, "w") as fh:
        fh.write(f"{os.getpid()}\n")


def _remove_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


class Daemon:
    """Ties the session manager to the RPC server."""

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT,
                 idle_timeout=DEFAULT_IDLE, session=None):
        self.session = session if session is not None else SessionManager()
        register_all(self.session)
        self.server = RpcServer((host, port), self.session)
        self.idle_timeout = idle_timeout
        self.host, self.port = self.server.server_address

    def install_signals(self):
        def handler(signum, _frame):
            logger.info("signal %s; shutting down", signum)
            self.server.state.stop.set()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, handler)

    def serve(self):
        logger.info("mibandd %s listening on %s:%s (idle=%s)",
                    VERSION, self.host, self.port, self.idle_timeout or "off")
        try:
            self.server.serve(idle_timeout=self.idle_timeout)
        finally:
            self.session.close()
            logger.info("mibandd stopped")


def build_parser():
    ap = argparse.ArgumentParser(prog="mibandd",
                                 description="Mi Band 9 Active backend daemon")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--idle-timeout", type=float, default=DEFAULT_IDLE,
                    help="exit after N idle seconds (0 = never)")
    ap.add_argument("--stay", action="store_true", help="never idle-exit")
    ap.add_argument("--foreground", action="store_true",
                    help="stay attached (default)")
    ap.add_argument("--daemonize", action="store_true",
                    help="detach and run in the background")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def serve_main(argv=None):
    args = build_parser().parse_args(argv)
    idle = None if args.stay else (args.idle_timeout or None)
    detached = args.daemonize and not args.foreground
    _configure_logging(foreground=not detached, verbose=args.verbose)
    if detached:
        _daemonize()
    _write_pid()
    try:
        daemon = Daemon(host=args.host, port=args.port, idle_timeout=idle)
        daemon.install_signals()
        daemon.serve()
    except OSError as exc:
        logger.error("cannot start: %s", exc)
        return 1
    finally:
        _remove_pid()
    return 0
