#!/usr/bin/env python3
"""Thin RPC client for mibandd (used by the per-field CLIs).

`call(domain, op, args)` sends one JSON line to the daemon and returns the
result. If the daemon is down it is auto-spawned (`bin/mibandd --daemonize`)
unless `spawn=False`.
"""
import json
import os
import socket
import subprocess
import sys
import time

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8478
SPAWN_WAIT = 10.0


class RpcFailure(Exception):
    """The daemon answered with an error."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class DaemonUnavailable(Exception):
    """mibandd could not be reached or started."""


def call(domain, op, args=None, host=DEFAULT_HOST, port=DEFAULT_PORT,
         spawn=True, timeout=30.0):
    """Run one op on the daemon; raises `RpcFailure` / `DaemonUnavailable`."""
    req = {"id": 1, "domain": domain, "op": op, "args": args or {}}
    try:
        return _exchange(host, port, req, timeout)
    except (ConnectionError, OSError):
        if not spawn:
            raise DaemonUnavailable(f"mibandd not running on {host}:{port}")
    _spawn()
    deadline = time.time() + SPAWN_WAIT
    while time.time() < deadline:
        try:
            return _exchange(host, port, req, timeout)
        except (ConnectionError, OSError):
            time.sleep(0.2)
    raise DaemonUnavailable(f"mibandd did not come up on {host}:{port}")


def _exchange(host, port, req, timeout):
    with socket.create_connection((host, port), timeout) as sock:
        sock.sendall((json.dumps(req) + "\n").encode())
        line = sock.makefile("r").readline()
    if not line:
        raise ConnectionError("empty response from mibandd")
    resp = json.loads(line)
    if not resp.get("ok"):
        err = resp.get("error") or {}
        raise RpcFailure(err.get("code", "error"), err.get("msg", "unknown"))
    return resp.get("result")


def _spawn():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    daemon = os.path.join(root, "bin", "mibandd")
    subprocess.Popen([sys.executable, daemon, "--daemonize"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True)
