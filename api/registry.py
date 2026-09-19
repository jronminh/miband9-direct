#!/usr/bin/env python3
"""Registry access: every known command by name.

A thin, read-only view over `client.registry` (the single source of truth), so
`api` can expose the whole catalogue without duplicating it. Names may be given
with hyphens (`face-list`, as in the registry) or underscores (`face_list`).
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from client.registry import COMMANDS, SERVICES, CommandInfo

BY_NAME = {c.name: c for c in COMMANDS}
BY_SERVICE = SERVICES

__all__ = ["CommandInfo", "BY_NAME", "BY_SERVICE", "lookup", "names",
           "by_status", "by_service", "services"]


def lookup(name):
    """Return the `CommandInfo` for `name`, or None if unknown."""
    return BY_NAME.get(name) or BY_NAME.get(name.replace("_", "-"))


def names():
    """All known command names, in catalogue order."""
    return [c.name for c in COMMANDS]


def by_status(status):
    """Commands whose status is `live`, `set`, `reply`, or `known`."""
    return [c for c in COMMANDS if c.status == status]


def by_service():
    """`{service_name: [CommandInfo, ...]}` in catalogue order."""
    out = {}
    for c in COMMANDS:
        out.setdefault(SERVICES.get(c.type, str(c.type)), []).append(c)
    return out


def services():
    """`{type_id: service_name}`."""
    return dict(SERVICES)
