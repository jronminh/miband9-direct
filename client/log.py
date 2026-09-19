"""Logging setup for the client package.

Libraries log through ``logging.getLogger(__name__)`` and never configure
handlers themselves. Applications (the CLIs) call :func:`configure`; the
convenience :func:`ensure_configured` is used by ``verbose=`` flags so a direct
library caller still sees output without wiring logging up first.

Levels:
    DEBUG    every frame TX/RX, acks, and reject reasons
    INFO     handshake progress and command/reply summaries
    WARNING  retries and recoverable failures
    ERROR    write/auth/link failures
"""
import logging
import sys

DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"
_ROOT = "client"


def configure(level=logging.INFO, stream=None, fmt=DEFAULT_FORMAT):
    """Attach a stderr handler to the `client` logger and set its level.

    Idempotent: a second call updates the level but does not add a handler.
    """
    root = logging.getLogger(_ROOT)
    root.setLevel(level)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setFormatter(logging.Formatter(fmt, datefmt=_DATE_FORMAT))
        root.addHandler(handler)
    return root


def ensure_configured(level=logging.INFO):
    """Configure only if no stream handler is attached yet (for `verbose=`)."""
    root = logging.getLogger(_ROOT)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        configure(level)
    return root
