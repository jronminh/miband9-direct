#!/usr/bin/env python3
"""SQLite database for Mi Band data — the storage layer.

Owns the connection, schema, and all write/read/lifecycle methods. No band or
protocol knowledge lives here; feed it `Response` objects or plain values.
`data.py` is the layer that talks to the band and calls into this.

Inspect from the shell:
    python store/db.py data/band.db stats
    python store/db.py data/band.db history --limit 10
"""
import argparse
import json
import os
import sqlite3
import threading
import time
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS exchanges (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL    NOT NULL,
    name    TEXT    NOT NULL,
    ctype   INTEGER,
    subtype INTEGER,
    request TEXT
);
CREATE INDEX IF NOT EXISTS idx_exchanges_name ON exchanges(name);

CREATE TABLE IF NOT EXISTS replies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id INTEGER NOT NULL REFERENCES exchanges(id),
    ts          REAL    NOT NULL,
    rtype       INTEGER,
    rsubtype    INTEGER,
    channel     INTEGER,
    encrypted   INTEGER,
    hex         TEXT,
    fields      TEXT
);
CREATE INDEX IF NOT EXISTS idx_replies_exchange ON replies(exchange_id);

CREATE TABLE IF NOT EXISTS samples (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     REAL    NOT NULL,
    date   TEXT,
    metric TEXT    NOT NULL,
    value  REAL,
    text   TEXT,
    raw    TEXT
);
CREATE INDEX IF NOT EXISTS idx_samples_metric_ts ON samples(metric, ts);

CREATE TABLE IF NOT EXISTS activity_files (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    file_ts INTEGER NOT NULL,
    suffix  TEXT    NOT NULL,
    raw     TEXT    NOT NULL,
    seen_at REAL    NOT NULL,
    UNIQUE(file_ts, suffix)
);

CREATE TABLE IF NOT EXISTS activity_blobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    file_ts    INTEGER NOT NULL,
    suffix     TEXT    NOT NULL,
    size       INTEGER NOT NULL,
    crc32      INTEGER,
    kind       TEXT,
    detail     TEXT,
    data       BLOB    NOT NULL,
    fetched_at REAL    NOT NULL,
    UNIQUE(file_ts, suffix)
);
"""

TABLES = ("exchanges", "replies", "samples", "activity_files", "activity_blobs")


def default_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "data", "band.db")


class Database:
    def __init__(self, path=None):
        self.path = os.path.abspath(path or default_path())
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Add columns introduced after the first schema, preserving rows."""
        columns = {row[1] for row in
                   self.conn.execute("PRAGMA table_info(samples)")}
        if "date" not in columns:
            self.conn.execute("ALTER TABLE samples ADD COLUMN date TEXT")
            self.conn.execute(
                "UPDATE samples SET date = datetime(ts, 'unixepoch', 'localtime') "
                "WHERE date IS NULL")
        self.conn.commit()

    # ---------------------------------------------------------------- write
    def record(self, name, responses, ctype=None, subtype=None, request=None,
               ts=None):
        """Store one command exchange plus each decoded reply."""
        ts = time.time() if ts is None else ts
        req = json.dumps(request, ensure_ascii=False) if request is not None else None
        with self._lock:
            try:
                cur = self.conn.execute(
                    "INSERT INTO exchanges(ts, name, ctype, subtype, request) "
                    "VALUES(?,?,?,?,?)", (ts, name, ctype, subtype, req))
                exchange_id = cur.lastrowid
                for r in responses:
                    self.conn.execute(
                        "INSERT INTO replies(exchange_id, ts, rtype, rsubtype, "
                        "channel, encrypted, hex, fields) VALUES(?,?,?,?,?,?,?,?)",
                        (exchange_id, ts, r.type, r.subtype, r.channel,
                         int(bool(r.encrypted)), r.hex,
                         json.dumps(r.to_dict()["fields"], ensure_ascii=False)))
                self.conn.commit()
            except Exception:
                # Don't leave a half-written exchange for a later commit to flush.
                self.conn.rollback()
                raise
        return exchange_id

    def sample(self, metric, value=None, text=None, raw=None, ts=None,
               date=None):
        """Store one parsed reading.

        `date` is a local `YYYY-MM-DD HH:MM:SS` string; it is derived from
        `ts` when not given, so every row carries a human-readable time.
        """
        ts = time.time() if ts is None else ts
        if date is None:
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        raw_json = json.dumps(raw, ensure_ascii=False) if raw is not None else None
        with self._lock:
            self.conn.execute(
                "INSERT INTO samples(ts, date, metric, value, text, raw) "
                "VALUES(?,?,?,?,?,?)", (ts, date, metric, value, text, raw_json))
            self.conn.commit()
        return ts

    def clear_samples(self, ts, prefix=None):
        """Delete samples at `ts`, optionally only metrics matching `prefix`."""
        with self._lock:
            if prefix:
                self.conn.execute(
                    "DELETE FROM samples WHERE ts = ? AND metric LIKE ?",
                    (float(ts), prefix + "%"))
            else:
                self.conn.execute("DELETE FROM samples WHERE ts = ?",
                                  (float(ts),))
            self.conn.commit()

    def add_activity_file(self, file_ts, suffix, raw, seen_at=None):
        seen_at = time.time() if seen_at is None else seen_at
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO activity_files(file_ts, suffix, raw, seen_at) "
                "VALUES(?,?,?,?)", (int(file_ts), suffix, raw, seen_at))
            self.conn.commit()

    def add_activity_blob(self, file_ts, suffix, data, crc32=None, kind=None,
                          detail=None, fetched_at=None):
        """Store a downloaded activity file body (bytes)."""
        fetched_at = time.time() if fetched_at is None else fetched_at
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO activity_blobs"
                "(file_ts, suffix, size, crc32, kind, detail, data, fetched_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (int(file_ts), suffix, len(data), crc32, kind, detail,
                 sqlite3.Binary(data), fetched_at))
            self.conn.commit()

    # ----------------------------------------------------------------- read
    def latest(self, metric):
        rows = self._select(
            "SELECT * FROM samples WHERE metric = ? ORDER BY id DESC LIMIT 1",
            (metric,))
        return rows[0] if rows else None

    def latest_ts(self, prefix=None):
        """The greatest sample `ts`, optionally only metrics matching `prefix`."""
        sql, params = "SELECT MAX(ts) FROM samples", []
        if prefix:
            sql += " WHERE metric LIKE ?"
            params.append(prefix + "%")
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
        return row[0] if row else None

    def samples(self, metric=None, prefix=None, since=None, limit=200):
        sql, where, params = "SELECT * FROM samples", [], []
        if metric:
            where.append("metric = ?"); params.append(metric)
        if prefix:
            where.append("metric LIKE ?"); params.append(prefix + "%")
        if since:
            where.append("ts >= ?"); params.append(float(since))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        return self._select(sql, params)

    def samples_at(self, ts, prefix=None, limit=200):
        """All samples at an exact `ts` (optionally a metric prefix)."""
        sql, where, params = "SELECT * FROM samples", ["ts = ?"], [float(ts)]
        if prefix:
            where.append("metric LIKE ?"); params.append(prefix + "%")
        sql += " WHERE " + " AND ".join(where) + " ORDER BY id ASC LIMIT ?"
        params.append(int(limit))
        return self._select(sql, params)

    def samples_by_ts(self, metric, limit=200):
        """The latest `limit` samples for `metric`, in chronological order."""
        return self._select(
            "SELECT * FROM (SELECT * FROM samples WHERE metric = ? "
            "ORDER BY ts DESC LIMIT ?) ORDER BY ts ASC",
            (metric, int(limit)))

    def history(self, name=None, since=None, limit=50):
        sql, where, params = "SELECT * FROM exchanges", [], []
        if name:
            where.append("name = ?"); params.append(name)
        if since:
            where.append("ts >= ?"); params.append(float(since))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        return self._select(sql, params)

    def activity_files(self, limit=500):
        return self._select(
            "SELECT * FROM activity_files ORDER BY file_ts DESC LIMIT ?",
            (int(limit),))

    def activity_blobs(self, limit=500):
        """Metadata for downloaded activity files (no body bytes)."""
        return self._select(
            "SELECT id, file_ts, suffix, size, crc32, kind, detail, fetched_at "
            "FROM activity_blobs ORDER BY file_ts DESC LIMIT ?",
            (int(limit),))

    def blob(self, file_ts, suffix):
        """The raw bytes of one downloaded activity file, or None."""
        rows = self._select(
            "SELECT data FROM activity_blobs WHERE file_ts = ? AND suffix = ?",
            (int(file_ts), suffix))
        return rows[0]["data"] if rows else None

    def stats(self):
        with self._lock:
            out = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                   for t in TABLES}
            out["first_sample_ts"] = self.conn.execute(
                "SELECT MIN(ts) FROM samples").fetchone()[0]
            files = self.conn.execute(
                "SELECT MIN(file_ts), MAX(file_ts) FROM activity_files").fetchone()
            out["first_file_ts"], out["last_file_ts"] = files[0], files[1]
        out["path"] = self.path
        return out

    # ------------------------------------------------------------ lifecycle
    def close(self):
        with self._lock:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _select(self, sql, params):
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row):
        if row is None:
            return None
        d = dict(row)
        for key in ("request", "raw", "fields"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except (TypeError, json.JSONDecodeError):
                    pass
        return d


def _main():
    ap = argparse.ArgumentParser(description="Inspect a Mi Band SQLite database")
    ap.add_argument("db", nargs="?", default=default_path())
    ap.add_argument("action", nargs="?", default="stats",
                    choices=["stats", "history", "samples", "files"])
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--name", default=None)
    ap.add_argument("--metric", default=None)
    args = ap.parse_args()

    with Database(args.db) as database:
        if args.action == "stats":
            out = database.stats()
        elif args.action == "history":
            out = database.history(name=args.name, limit=args.limit)
        elif args.action == "samples":
            out = database.samples(metric=args.metric, limit=args.limit)
        else:
            out = database.activity_files(limit=args.limit)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
