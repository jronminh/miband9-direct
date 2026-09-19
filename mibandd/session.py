#!/usr/bin/env python3
"""Session manager: one authenticated band session behind a lock.

The daemon owns a single session (the band allows one login per BLE
connection) and serialises every request through it. Domains register
`(domain, op) -> callable(backend, **args)`; the backend is opened lazily on
first use and dropped when the link dies, so the next request reconnects and
re-authenticates.
"""
import logging
import os
import sys
import threading

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logger = logging.getLogger("mibandd.session")


class UnknownOp(Exception):
    """Raised for a (domain, op) the daemon does not know."""

    code = "unknown_op"


def _default_backend():
    from store import BandData
    return BandData()


def _connection_errors():
    from api.errors import AuthError, ConnectionLost, DaemonError
    return (ConnectionError, EOFError, OSError, TimeoutError,
            ConnectionLost, DaemonError, AuthError)


class SessionManager:
    """Owns one band session; serialises and dispatches domain requests.

    `backend_factory` is injectable so tests can run without a band.
    """

    def __init__(self, backend_factory=None):
        self._lock = threading.RLock()
        self._factory = backend_factory or _default_backend
        self._backend = None
        self._ops = {}

    def register(self, domain, ops):
        """Register `{op: fn}` for `domain`; `fn(backend, **args)`."""
        for op, fn in ops.items():
            self._ops[(domain, op)] = fn

    @property
    def connected(self) -> bool:
        return self._backend is not None and self._backend.connected

    def status(self):
        """Daemon-visible session state (never opens the backend)."""
        return {"connected": self.connected}

    def request(self, domain, op, args=None):
        """Run one op under the session lock, opening the session if needed."""
        with self._lock:
            fn = self._ops.get((domain, op))
            if fn is None:
                raise UnknownOp(f"unknown op {domain}.{op}")
            backend = self._ensure()
            try:
                return fn(backend, **(args or {}))
            except Exception as exc:
                if isinstance(exc, _connection_errors()):
                    logger.warning("session error on %s.%s: %s", domain, op, exc)
                    self._drop()
                raise

    def _ensure(self):
        if self._backend is None:
            logger.info("opening band session")
            self._backend = self._factory()
        return self._backend

    def _drop(self):
        if self._backend is not None:
            try:
                self._backend.close()
            except Exception:
                pass
            self._backend = None

    def close(self):
        with self._lock:
            self._drop()
