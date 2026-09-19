#!/usr/bin/env python3
"""mibandd — single backend daemon for the Mi Band 9 Active.

One long-lived process owns the authenticated session, the SQLite writer and
the request routing; the same `mibandd` command is also the CLI that drives it
(`mibandd health summary`, `mibandd store stats`, ...). See `docs/DAEMON.md`.
"""
from .session import SessionManager, UnknownOp
from .rpc import RpcServer, RpcError, VERSION
from .lifecycle import Daemon, serve_main
from .main import main

__all__ = [
    "SessionManager", "UnknownOp",
    "RpcServer", "RpcError", "VERSION",
    "Daemon", "serve_main", "main",
]
