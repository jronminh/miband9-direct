#!/usr/bin/env python3
"""Health domain: activity collection, decoding, and daily summaries.

`collect` stores the raw activity files and, unless `raw=True`, decodes the
daily summaries into `daily.*` samples (idempotently). `decode` backfills,
`summary` returns one day's decoded fields, `trend` a metric over time.
"""
from store.summary import (DEFAULT_PREFIX, SUMMARY_DETAIL, SUMMARY_KIND,
                           daily_metrics, parse_daily_summary)

from .common import need_db


def _is_summary(row):
    return row.get("kind") == SUMMARY_KIND and row.get("detail") == SUMMARY_DETAIL


def _decode_blobs(backend, file_ts=None, limit=500):
    """Decode stored summary blobs into `daily.*` samples (idempotent)."""
    db = need_db(backend)
    decoded = []
    for row in backend.activity_blobs(limit=limit):
        if file_ts is not None and row["file_ts"] != file_ts:
            continue
        if not _is_summary(row):
            continue
        fields = parse_daily_summary(backend.blob(row["file_ts"], row["suffix"]))
        if not fields:
            continue
        ts = row["file_ts"]
        db.clear_samples(ts, prefix=DEFAULT_PREFIX)
        for metric, value in daily_metrics(fields).items():
            db.sample(metric, value=value, raw=fields, ts=ts)
        decoded.append({"file_ts": ts, "suffix": row["suffix"],
                        "fields": fields})
    return decoded


def _collect(backend, past=False, limit=None, timeout=8.0, max_misses=2,
             raw=False, **_args):
    stored = backend.collect_activity(past=past, limit=limit, timeout=timeout,
                                      max_misses=max_misses)
    decoded = [] if raw else _decode_blobs(backend)
    return {"stored": stored, "decoded": len(decoded)}


def _decode(backend, file_ts=None, **_args):
    decoded = _decode_blobs(backend, file_ts=file_ts)
    return {"decoded": len(decoded), "files": decoded}


def _num(value):
    """Render an integral float as int (SQLite stores samples as REAL)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _summary(backend, file_ts=None, **_args):
    db = need_db(backend)
    if file_ts is None:
        file_ts = db.latest_ts(DEFAULT_PREFIX)
        if file_ts is None:
            return {"file_ts": None, "date": None, "fields": {}}
    rows = db.samples_at(file_ts, prefix=DEFAULT_PREFIX)
    fields = {r["metric"][len(DEFAULT_PREFIX):]: _num(r["value"]) for r in rows}
    return {"file_ts": file_ts,
            "date": rows[0]["date"] if rows else None,
            "fields": fields}


def _trend(backend, metric=None, limit=30, **_args):
    if not metric:
        raise ValueError("trend needs 'metric'")
    rows = need_db(backend).samples_by_ts(metric, limit=limit)
    series = [{"ts": r["ts"], "date": r["date"], "value": _num(r["value"])}
              for r in rows]
    return {"metric": metric, "series": series}


def _blob(backend, file_ts=None, suffix=None, **_args):
    if file_ts is None or not suffix:
        raise ValueError("blob needs 'file_ts' and 'suffix'")
    data = backend.blob(file_ts, suffix)
    if data is None:
        raise ValueError(f"no stored blob for {file_ts}/{suffix}")
    return {"file_ts": file_ts, "suffix": suffix, "size": len(data),
            "hex": data.hex()}


def _list(backend, past=False, **_args):
    """List the band's recorded activity file ids (no download)."""
    return backend.activity_files(past=past)


OPS = {
    "list": _list,
    "collect": _collect,
    "decode": _decode,
    "summary": _summary,
    "trend": _trend,
    "blob": _blob,
}
