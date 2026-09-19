#!/usr/bin/env python3
"""Backwards-compatible shim for the old monolithic `api.api` module.

Prefer `from api import MiBand` or `python -m api`. Kept so existing
`from api.api import MiBand` and `python api/api.py ...` keep working.
"""
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from api.band import MiBand
    from api.cli import main
    from api.errors import (BandError, DaemonError, AuthError,
                            NotConnectedError, ConnectionLost, CommandError)
else:
    from .band import MiBand
    from .cli import main
    from .errors import (BandError, DaemonError, AuthError,
                         NotConnectedError, ConnectionLost, CommandError)

__all__ = [
    "MiBand", "BandError", "DaemonError", "AuthError", "NotConnectedError",
    "ConnectionLost", "CommandError",
]

if __name__ == "__main__":
    sys.exit(main())
