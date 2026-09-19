#!/usr/bin/env python3
"""Band data API: run commands and return usable data.

This is the layer that talks to the band. It opens one authenticated session
via `session.open_session()` and sends commands with
`command.send_command()`, then parses the replies into plain values. If a
`Database` is attached it also persists the exchange and the parsed samples
(see `db.py`).

    from store import BandData
    with BandData() as band:
        band.battery()                 # {'level': 85, 'state': 2}
        band.info()                    # {'serial': ..., 'firmware': ..., 'model': ...}
        band.activity_files()          # [{'ts': ..., 'suffix': ...}, ...]
        band.db.latest("battery.level")

Parse-only (no band, no db):
    from store.data import parse_battery, parse_info, parse_activity_files
"""
import json
import logging
import os
import sys
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from client.activity import ActivityFileId, ack_file, fetch_file
from client.protocol import pb_get, pb_bytes, pb_varint
from client.commands import send_command
from client.session import open_session
from .db import Database

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ parsing
def parse_battery(responses):
    """Extract `{level, state}` from a 2,1 reply, or None."""
    for r in responses:
        if r.type == 2 and r.subtype == 1:
            system = pb_get(r.body, 4, 2)
            power = pb_get(system, 2, 2) if system else None
            battery = pb_get(power, 1, 2) if power else None
            if battery is not None:
                return {"level": pb_get(battery, 1, 0),
                        "state": pb_get(battery, 2, 0)}
    return None


def parse_info(responses):
    """Extract `{serial, firmware, model}` from a 2,2 reply, or None."""
    for r in responses:
        if r.type == 2 and r.subtype == 2:
            system = pb_get(r.body, 4, 2)
            di = pb_get(system, 3, 2) if system else None
            if di is None:
                continue

            def s(field):
                v = pb_get(di, field, 2)
                return v.decode("utf-8", "replace") if v else None

            return {"serial": s(1), "firmware": s(2), "model": s(4)}
    return None


def parse_activity_files(responses):
    """Parse activity file-id lists (Health #2, 7-byte LE entries)."""
    out = []
    for r in responses:
        if r.type != 8 or r.subtype not in (1, 2):
            continue
        health = pb_get(r.body, 10, 2)
        blob = pb_get(health, 2, 2) if health else None
        if not blob:
            continue
        for i in range(0, len(blob) - 6, 7):
            entry = blob[i:i + 7]
            out.append({"ts": int.from_bytes(entry[0:4], "little"),
                        "suffix": entry[4:7].hex(),
                        "raw": entry.hex()})
    return out


# --------------------------------------------------------------------- API
class BandData:
    """Run band commands and return usable data, optionally persisting them.

    `store=False` disables the database; `path=` picks the SQLite file.
    """

    def __init__(self, key=None, path=None, use_session=True, port=8477,
                 auth_timeout=300, listen=6.0, verbose=False, store=True,
                 capture=True, capture_maxlen=1000):
        self._key = key
        self._port = port
        self._use_session = use_session
        self._auth_timeout = auth_timeout
        self._listen = listen
        self._verbose = verbose
        self._capture = capture
        self._capture_maxlen = capture_maxlen
        self._lock = threading.RLock()
        self.db = Database(path) if store else None
        self.d = None
        self.sess = None

    @property
    def connected(self):
        return self.d is not None and self.sess is not None

    def connect(self):
        with self._lock:
            if self.connected:
                return self
            try:
                self.d, self.sess = open_session(
                    key=self._key, port=self._port,
                    use_session=self._use_session,
                    auth_timeout=self._auth_timeout, verbose=self._verbose,
                    capture=self._capture, capture_maxlen=self._capture_maxlen)
            except BaseException:
                self.close()
                raise
            return self

    @property
    def captures(self):
        """The live two-way frame capture, or None when not connected."""
        return self.sess.capture if self.sess is not None else None

    def clear_capture(self):
        if self.sess is not None:
            self.sess.clear_capture()

    def close(self):
        with self._lock:
            if self.d is not None:
                self.d.close()
            self.d = self.sess = None
            if self.db is not None:
                self.db.close()
                self.db = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # --------------------------------------------------------------- runner
    def _run(self, name, ctype, subtype, body=b"", listen=None, ts=None):
        with self._lock:
            if not self.connected:
                self.connect()
            listen = self._listen if listen is None else listen
            responses = send_command(self.d, self.sess, ctype, subtype, body,
                                     listen)
            if self.db is not None:
                self.db.record(name, responses, ctype, subtype, ts=ts)
            return responses

    # --------------------------------------------------------------- verbs
    def battery(self, ts=None):
        responses = self._run("battery", 2, 1, ts=ts)
        b = parse_battery(responses)
        if self.db is not None and b:
            self.db.sample("battery.level", b.get("level"), raw=b, ts=ts)
            self.db.sample("battery.state", b.get("state"), raw=b, ts=ts)
        return b

    def info(self, ts=None):
        responses = self._run("info", 2, 2, ts=ts)
        info = parse_info(responses)
        if self.db is not None and info:
            self.db.sample("device.info", text=json.dumps(info), raw=info, ts=ts)
        return info

    def activity_files(self, past=False, ts=None):
        body = b"" if past else pb_bytes(10, pb_bytes(5, pb_varint(1, 0)))
        responses = self._run(
            "activity_files_past" if past else "activity_files",
            8, 2 if past else 1, body, ts=ts)
        files = parse_activity_files(responses)
        if self.db is not None:
            for f in files:
                self.db.add_activity_file(f["ts"], f["suffix"], f["raw"], seen_at=ts)
        return files

    def raw(self, name, ctype, subtype, body=b"", listen=None, ts=None):
        """Run any Command and return the raw `Response` list."""
        return self._run(name, ctype, subtype, body, listen, ts)

    # ------------------------------------------------------------ collector
    def activity_blobs(self, limit=500):
        """Metadata for downloaded activity files (no body bytes)."""
        return self.db.activity_blobs(limit=limit) if self.db else []

    def blob(self, file_ts, suffix):
        """The raw bytes of one downloaded activity file, or None."""
        return self.db.blob(file_ts, suffix) if self.db else None

    def collect_activity(self, past=False, limit=None, timeout=8.0,
                         max_misses=2, ts=None):
        """Download recorded activity files and store their raw bytes.

        Lists the file ids (8,1 / 8,2), requests each one (8,3), reassembles
        the Activity-channel chunks, verifies the CRC32, stores the body, and
        acks it (8,5). Returns a summary per stored file.

        This band lists files it never serves (details/sleep); `max_misses`
        consecutive timeouts stop the run early so a scheduled collection stays
        short. Pass `max_misses=0` to try every listed file.
        """
        with self._lock:
            if not self.connected:
                self.connect()
            files = self.activity_files(past=past, ts=ts)
            if limit is not None:
                files = files[:limit]
            stored = []
            misses = 0
            for f in files:
                file_id = ActivityFileId.from_bytes(bytes.fromhex(f["raw"]))
                try:
                    result = fetch_file(self.d, self.sess, file_id,
                                        timeout=timeout)
                except Exception as exc:
                    logger.warning("fetch %s failed: %s", file_id, exc)
                    result = None
                if result is None:
                    misses += 1
                    if max_misses and misses >= max_misses:
                        logger.info("stopping after %d unserved file(s)", misses)
                        break
                    continue
                misses = 0
                if self.db is not None:
                    self.db.add_activity_blob(
                        f["ts"], f["suffix"], result["raw"],
                        crc32=result["crc32"], kind=file_id.kind,
                        detail=file_id.detail, fetched_at=ts)
                ack_file(self.d, self.sess, file_id)
                stored.append({"ts": f["ts"], "suffix": f["suffix"],
                               "size": len(result["raw"]),
                               "kind": file_id.kind, "detail": file_id.detail})
            return stored
