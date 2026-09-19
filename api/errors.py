#!/usr/bin/env python3
"""Exception hierarchy for the high-level API.

`api` never leaks the client package's transport exceptions (`OSError`,
`TimeoutError`, `IOError`, `ConnectionError`) to callers; it translates them
into the classes below so application code can catch one stable type.
"""


class BandError(Exception):
    """Base class for every error raised by `api`."""


class DaemonError(BandError):
    """The local BLE daemon could not be reached, or spoke garbage."""


class AuthError(BandError):
    """The Xiaomi handshake was rejected or timed out."""


class NotConnectedError(BandError):
    """An operation needs a live session, but none is open."""


class ConnectionLost(BandError):
    """The BLE link dropped mid-command; the session has been closed."""


class CommandError(BandError):
    """A command was not written to the band (write rejected / no ACK)."""
