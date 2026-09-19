#!/usr/bin/env python3
"""Notification domain: notify, call, callend, dismiss."""
from client.commands import (build_call, build_call_end, build_dismiss,
                             build_notification)

from .common import ack


def _notify(backend, title="", text="", app="Termux", pkg="com.termux",
            nid=1, **_args):
    body = build_notification(nid, pkg, app, title, text)
    return ack(backend.raw("notify", 7, 0, body))


def _call(backend, name="", number="", **_args):
    return ack(backend.raw("call", 7, 0, build_call(name, number)))


def _callend(backend, **_args):
    return ack(backend.raw("callend", 7, 1, build_call_end()))


def _dismiss(backend, nid=0, pkg="com.termux", **_args):
    return ack(backend.raw("dismiss", 7, 1, build_dismiss(nid, pkg)))


OPS = {
    "notify": _notify,
    "call": _call,
    "callend": _callend,
    "dismiss": _dismiss,
}
