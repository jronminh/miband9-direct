#!/usr/bin/env python3
"""Reply parsing helpers.

The band-specific decoders are owned by `store.data` (the band-data layer) so
there is a single source of truth; this module re-exports them for `api` users
and adds small generic helpers for working with `Response` lists.

Parse-only (no band, no daemon):
    from api.parse import parse_battery, first, to_dicts
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from store.data import parse_battery, parse_info, parse_activity_files

__all__ = [
    "parse_battery", "parse_info", "parse_activity_files",
    "first", "to_dicts",
]


def first(responses, ctype, subtype):
    """Return the first `Response` matching (ctype, subtype), or None."""
    for r in responses:
        if r.type == ctype and r.subtype == subtype:
            return r
    return None


def to_dicts(responses):
    """Render a `Response` list as plain dicts (for JSON output)."""
    return [r.to_dict() for r in responses]
