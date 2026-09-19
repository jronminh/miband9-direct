#!/usr/bin/env python3
"""Shared helpers for domain modules."""


def ack(responses):
    """Summarise a command's replies for a JSON response."""
    return {"ok": True, "responses": len(responses)}


def need_db(backend):
    """The backend's SQLite handle, or a clear error when it has none."""
    if backend.db is None:
        raise ValueError("this op needs the store; the daemon must run with it")
    return backend.db
