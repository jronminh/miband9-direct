"""Mi Band 9 Active high-level API.

Public surface:

    MiBand                  one persistent, authenticated session
    BandError + subclasses  the only exceptions `api` raises
    parse_* / first / to_dicts   reply decoding helpers
    registry                full command catalogue access
    read_events / stream    asynchronous band frames

`MiBand` is a facade over the `client` package (protocol, command builders,
session); the band-data decoders are re-exported from `store.data`. Every
command in `client.registry` is reachable as `band.command("name")` or
`band.name()` (hyphens become underscores). See `api/band.py` for the verb
reference and `python -m api` for the CLI.
"""
from . import registry
from .band import MiBand
from .errors import (BandError, DaemonError, AuthError, NotConnectedError,
                     ConnectionLost, CommandError)
from .events import read_events, stream
from .parse import (parse_battery, parse_info, parse_activity_files,
                    first, to_dicts)

__all__ = [
    "MiBand", "registry", "read_events", "stream",
    "BandError", "DaemonError", "AuthError", "NotConnectedError",
    "ConnectionLost", "CommandError",
    "parse_battery", "parse_info", "parse_activity_files", "first", "to_dicts",
]
