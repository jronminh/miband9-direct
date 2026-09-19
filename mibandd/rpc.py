#!/usr/bin/env python3
"""JSON-lines RPC server for mibandd.

One JSON request per line, one JSON response per line:

    {"id": 1, "domain": "device", "op": "battery", "args": {}}
    {"id": 1, "ok": true, "result": {"level": 85, "state": 2}}
    {"id": 1, "ok": false, "error": {"code": "...", "msg": "..."}}

Built-in ops live on the empty domain: `ping`, `version`, `state`, `shutdown`.
"""
import json
import logging
import os
import socketserver
import threading
import time

logger = logging.getLogger("mibandd.rpc")

VERSION = "0.1.0"


class RpcError(Exception):
    """A request failure with a machine-readable `code`."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class _State:
    """Shared idle/shutdown state for the accept loop and handlers."""

    def __init__(self):
        self.last_activity = time.monotonic()
        self.stop = threading.Event()

    def touch(self):
        self.last_activity = time.monotonic()


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            raw = raw.strip()
            if not raw:
                continue
            self.server.state.touch()
            try:
                req = json.loads(raw)
            except ValueError:
                self._write({"id": None, "ok": False,
                             "error": {"code": "bad_json",
                                       "msg": "request is not valid JSON"}})
                continue
            self._write(self.server.dispatch(req))

    def _write(self, obj):
        try:
            self.wfile.write((json.dumps(obj, default=str) + "\n").encode())
        except OSError:
            pass


class RpcServer(socketserver.ThreadingTCPServer):
    """Threaded JSON-lines server; one session, one dispatch table."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, session):
        super().__init__(address, _Handler)
        self.session = session
        self.state = _State()

    # ------------------------------------------------------------ dispatch
    def dispatch(self, req):
        rid = req.get("id")
        domain = req.get("domain") or ""
        op = req.get("op")
        args = req.get("args") or {}
        try:
            return {"id": rid, "ok": True,
                    "result": self._call(domain, op, args)}
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code is None:
                logger.exception("op %s.%s failed", domain, op)
                code = "error"
            return {"id": rid, "ok": False,
                    "error": {"code": code, "msg": str(exc)}}

    def _call(self, domain, op, args):
        if not domain:
            return self._builtin(op)
        return self.session.request(domain, op, args)

    def _builtin(self, op):
        if op == "ping":
            return "pong"
        if op == "version":
            return {"version": VERSION, "pid": os.getpid()}
        if op == "state":
            return {"pid": os.getpid(), "version": VERSION,
                    "session": self.session.status()}
        if op == "shutdown":
            self.state.stop.set()
            return {"stopping": True}
        raise RpcError("unknown_op", f"unknown built-in op {op!r}")

    # --------------------------------------------------------------- serve
    def serve(self, idle_timeout=None, poll=0.5):
        """Serve until `shutdown`, a signal, or `idle_timeout` seconds idle."""
        self.timeout = poll
        self.state.touch()
        try:
            while not self.state.stop.is_set():
                self.handle_request()
                if idle_timeout and (time.monotonic() - self.state.last_activity
                                     > idle_timeout):
                    logger.info("idle for %.0fs; exiting", idle_timeout)
                    break
        finally:
            self.server_close()
