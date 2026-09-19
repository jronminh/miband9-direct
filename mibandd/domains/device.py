#!/usr/bin/env python3
"""Device domain: info, battery, state, clock, find, raw/cmd."""
import logging

from api import registry
from api.parse import to_dicts
from client.commands import build_clock
from client.protocol import pb_bytes, pb_varint

from .common import ack

logger = logging.getLogger("mibandd.device")


def _state(backend, **_args):
    return to_dicts(backend.raw("state", 2, 78))


def _clock(backend, h12=False, **_args):
    return ack(backend.raw("clock", 2, 3, build_clock(not h12)))


def _find(backend, stop=False, **_args):
    body = pb_bytes(4, pb_varint(5, 1 if stop else 0))
    return ack(backend.raw("findwatch", 2, 18, body))


def _raw(backend, type=None, subtype=None, body="", **_args):
    if type is None or subtype is None:
        raise ValueError("raw needs 'type' and 'subtype'")
    payload = bytes.fromhex(body) if body else b""
    return to_dicts(backend.raw(f"raw:{type}:{subtype}", type, subtype, payload))


def _cmd(backend, name=None, body="", **_args):
    if not name:
        raise ValueError("cmd needs 'name'")
    info = registry.lookup(name)
    if info is None:
        raise ValueError(f"unknown command {name!r}")
    payload = bytes.fromhex(body) if body else b""
    return to_dicts(backend.raw(info.name, info.type, info.subtype, payload))


OPS = {
    "battery": lambda backend, **a: backend.battery(),
    "info": lambda backend, **a: backend.info(),
    "state": _state,
    "clock": _clock,
    "find": _find,
    "raw": _raw,
    "cmd": _cmd,
}
