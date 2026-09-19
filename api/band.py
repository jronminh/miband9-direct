#!/usr/bin/env python3
"""High-level, importable API for the Mi Band 9 Active.

`MiBand` is a stateful facade over the `client` package:

    client.protocol   wire protocol / daemon transport (`Daemon`, `Response`)
    client.commands   command builders + `send_command` (Command -> replies)
    client.session    `open_session()` (connect + subscribe + authenticate)

It owns one persistent, authenticated session (the band allows a single login
per BLE connection), serialises every command behind an internal lock so an
instance is safe to share between threads, and maps the client's transport
exceptions onto the `api.errors` hierarchy.

Coverage
--------
Every command in `client.registry` is reachable by name, three ways:

    band.command("face-list")            # explicit, any catalogue command
    band.face_list()                     # dynamic (underscores for hyphens)
    band.raw(4, 10)                      # by raw type/subtype

Methods defined here (with payload builders or reply parsers) take precedence
over the dynamic registry verbs. `band.commands()` lists the whole catalogue.

Library:
    from api import MiBand
    with MiBand() as band:
        band.battery_status()          # {'level': 85, 'state': 2}
        band.notify("Hi", "from Termux")
        band.face_list()               # any registry command

CLI:
    python -m api battery info
    python -m api notify --title Hi --text hello
    python -m api --command face-list
"""
import logging
import os
import sys
import threading

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from client.commands import (send_command, build_notification, build_call,
                             build_call_end, build_dismiss, build_clock, NAMED)
from client.protocol import pb_bytes, pb_varint
from client.session import open_session

from . import registry
from .errors import (BandError, DaemonError, AuthError, NotConnectedError,
                     ConnectionLost, CommandError)
from .parse import parse_battery, parse_info

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8477
DEFAULT_LISTEN = 4.0

logger = logging.getLogger("api.band")


class MiBand:
    """One persistent, authenticated session to the band.

    The band allows a single login per BLE connection, so a `MiBand` owns its
    connection for its whole lifetime. Every command is serialised behind
    `self._lock`, so one instance can be shared between threads.
    """

    def __init__(self, key=None, port=DEFAULT_PORT, listen=DEFAULT_LISTEN,
                 use_session=True, auth_timeout=60.0, verbose=False,
                 capture=True, capture_maxlen=1000):
        self._key = key
        self.port = port
        self.listen = listen
        self.use_session = use_session
        self.auth_timeout = auth_timeout
        self.verbose = verbose
        self._capture = capture
        self._capture_maxlen = capture_maxlen
        self._lock = threading.RLock()
        self.d = None
        self.sess = None

    # ------------------------------------------------------------ lifecycle
    @property
    def connected(self) -> bool:
        """True when a daemon socket and an authenticated session exist."""
        return self.d is not None and self.sess is not None

    def _require_connected(self):
        if not self.connected:
            raise NotConnectedError("no live session; call connect() first")

    def connect(self):
        """Open the daemon socket and run the handshake; idempotent."""
        with self._lock:
            if self.connected:
                return self
            try:
                self.d, self.sess = open_session(
                    key=self._key, port=self.port,
                    use_session=self.use_session,
                    auth_timeout=self.auth_timeout, verbose=self.verbose,
                    capture=self._capture, capture_maxlen=self._capture_maxlen)
            except ConnectionError as exc:
                self.close()
                raise AuthError(str(exc)) from exc
            except (OSError, TimeoutError, EOFError) as exc:
                self.close()
                raise DaemonError(
                    f"cannot reach BLE daemon on {DEFAULT_HOST}:{self.port}: "
                    f"{exc}") from exc
            return self

    @property
    def captures(self):
        """The live two-way frame capture, or None when not connected."""
        return self.sess.capture if self.sess is not None else None

    def clear_capture(self):
        """Drop the buffered frame capture (no-op when not connected)."""
        if self.sess is not None:
            self.sess.clear_capture()

    def close(self):
        """Close the session; safe to call more than once."""
        with self._lock:
            if self.d is not None:
                try:
                    self.d.close()
                except Exception:
                    pass
            self.d = self.sess = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------ transport
    def send(self, ctype: int, subtype: int, body: bytes = b"", listen=None):
        """Send one `Command` and return the decoded `Response` list.

        Connects on first use. Waits `listen` seconds for replies. Raises
        `ConnectionLost` if the link drops and `CommandError` if the write did
        not land.
        """
        with self._lock:
            if not self.connected:
                self.connect()
            listen = self.listen if listen is None else listen
            try:
                return send_command(self.d, self.sess, ctype, subtype, body,
                                    listen)
            except ConnectionError as exc:
                self.close()
                raise ConnectionLost(str(exc)) from exc
            except IOError as exc:
                raise CommandError(
                    f"command type={ctype} subtype={subtype} was not written"
                ) from exc

    def raw(self, ctype: int, subtype: int, body_hex: str = "", listen=None):
        """Like `send()`, with the body given as a hex string."""
        body = bytes.fromhex(body_hex) if body_hex else b""
        return self.send(ctype, subtype, body, listen)

    def send_named(self, name: str, listen=None):
        """Send a command from `client.commands.NAMED` (no payload)."""
        try:
            ctype, subtype = NAMED[name]
        except KeyError as exc:
            raise BandError(
                f"unknown named command {name!r}; known: {', '.join(NAMED)}"
            ) from exc
        return self.send(ctype, subtype, listen=listen)

    # ------------------------------------------------------- registry verbs
    def command(self, name: str, body: bytes = b"", listen=None):
        """Send any catalogue command by name (hyphens or underscores).

        The type/subtype come from `client.registry`; `body` is an optional
        protobuf payload for commands that need one.
        """
        info = registry.lookup(name)
        if info is None:
            raise BandError(f"unknown command {name!r}; see band.commands()")
        logger.debug("registry %s -> (%d,%d) status=%s",
                     info.name, info.type, info.subtype, info.status)
        return self.send(info.type, info.subtype, body, listen)

    def commands(self):
        """The full catalogue as a list of `registry.CommandInfo`."""
        return registry.COMMANDS

    @staticmethod
    def known_commands():
        """The catalogue as `(type, subtype, name, status)` tuples."""
        return [(c.type, c.subtype, c.name, c.status)
                for c in registry.COMMANDS]

    def __getattr__(self, name):
        """Expose every registry command as a method (hyphens -> underscores).

        `band.face_list()` sends registry command `face-list`. Only called when
        normal attribute lookup fails, so methods defined on the class win.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        info = registry.lookup(name)
        if info is None:
            raise AttributeError(
                f"{type(self).__name__!r} has no attribute {name!r} "
                f"and no registry command matches")
        reg_name = info.name

        def verb(body: bytes = b"", listen=None):
            return self.command(reg_name, body, listen)

        verb.__name__ = name
        verb.__qualname__ = f"{type(self).__name__}.{name}"
        verb.__doc__ = (f"{info.description} — registry ({info.type},"
                        f"{info.subtype}); status={info.status}.")
        setattr(self, name, verb)  # cache so __getattr__ runs once
        return verb

    def __dir__(self):
        base = set(super().__dir__())
        return sorted(base | {c.name.replace("-", "_") for c in registry.COMMANDS})

    # ------------------------------------------------------------- events
    def events(self, timeout=2.0):
        """Drain asynchronous frames for `timeout` seconds (see api.events)."""
        from .events import read_events
        return read_events(self, timeout)

    # ------------------------------------------------------------- system
    def battery(self):
        """Raw reply to battery status (2,1)."""
        return self.send(2, 1)

    def battery_status(self):
        """Parsed battery: `{'level': int, 'state': int}` or None."""
        return parse_battery(self.battery())

    def info(self):
        """Raw reply to device info (2,2)."""
        return self.send(2, 2)

    def device_info(self):
        """Parsed info: `{'serial', 'firmware', 'model'}` or None."""
        return parse_info(self.info())

    def state(self):
        """Device state (2,78)."""
        return self.send(2, 78)

    def clock(self, is_24h=True, tzname=None):
        """Set the band clock/timezone from the phone (2,3)."""
        return self.send(2, 3, build_clock(is_24h, tzname))

    def find_watch(self, start=True):
        """Vibrate the band (2,18); `start=False` stops it."""
        return self.send(2, 18, pb_bytes(4, pb_varint(5, 0 if start else 1)))

    def language(self, code="en_us"):
        """Set the band UI language (2,6). Payload not yet verified live."""
        return self.send(2, 6, pb_bytes(4, pb_bytes(20, pb_bytes(1, code.encode()))))

    def dnd(self, enabled=True):
        """Set do-not-disturb (2,23): 0 = on, 2 = off."""
        return self.send(2, 23, pb_bytes(4, pb_bytes(11, pb_varint(1, 0 if enabled else 2))))

    def screen_on_notification(self, enabled=True):
        """Toggle wake-screen-on-notification (7,7)."""
        return self.send(7, 7, pb_bytes(9, pb_varint(7, 1 if enabled else 0)))

    # -------------------------------------------------------- notification
    def notify(self, title, body, app="Termux", package="com.termux", nid=1):
        """Send a notification to the band (7,0)."""
        return self.send(7, 0, build_notification(nid, package, app, title, body))

    def call(self, name, number):
        """Fake an incoming call (7,0 with isCall)."""
        return self.send(7, 0, build_call(name, number))

    def call_end(self):
        """End the faked call (7,1)."""
        return self.send(7, 1, build_call_end())

    def dismiss(self, nid=0, package="com.termux"):
        """Dismiss a notification (7,1)."""
        return self.send(7, 1, build_dismiss(nid, package))

    # --------------------------------------------------------------- health
    def heart_rate_config(self):
        """Heart-rate config (8,10)."""
        return self.send(8, 10)

    def spo2_config(self):
        """SpO2 config (8,8)."""
        return self.send(8, 8)

    def stress_config(self):
        """Stress config (8,14)."""
        return self.send(8, 14)

    def vitality_score(self):
        """Vitality score (8,35)."""
        return self.send(8, 35)

    def activity_files(self, past=False):
        """Request the activity file-id list (8,1 today / 8,2 past)."""
        body = b"" if past else pb_bytes(5, pb_varint(1, 0))
        return self.send(8, 2 if past else 1, body)

    def activity_request(self, file_id_hex):
        """Ask the band to send one recorded activity file (8,3)."""
        fid = bytes.fromhex(file_id_hex)
        return self.send(8, 3, pb_bytes(10, pb_bytes(2, fid)))

    def activity_ack(self, file_id_hex):
        """Ack a downloaded activity file (8,5)."""
        fid = bytes.fromhex(file_id_hex)
        return self.send(8, 5, pb_bytes(10, pb_bytes(3, fid)))

    # ----------------------------------------------------------------- misc
    def music(self):
        """Now-playing media info (18,1)."""
        return self.send(18, 1)
