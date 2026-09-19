#!/usr/bin/env python3
"""Store domain: read-only queries over the SQLite band data."""
from .common import need_db


def _history(backend, name=None, limit=20, **_args):
    return need_db(backend).history(name=name, limit=limit)


def _samples(backend, metric=None, limit=20, **_args):
    return need_db(backend).samples(metric=metric, limit=limit)


def _stats(backend, **_args):
    return need_db(backend).stats()


def _files(backend, limit=50, **_args):
    return need_db(backend).activity_files(limit=limit)


def _blobs(backend, limit=500, **_args):
    return backend.activity_blobs(limit=limit)


OPS = {
    "history": _history,
    "samples": _samples,
    "stats": _stats,
    "files": _files,
    "blobs": _blobs,
}
