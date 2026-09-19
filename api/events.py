#!/usr/bin/env python3
"""Asynchronous frames the band pushes outside a command reply.

The band emits DATA frames on its own (incoming call, notification-icon
requests, settings pushes). `read_events()` drains that stream for a bounded
window, acking every frame; `stream()` yields them until a deadline or
`KeyboardInterrupt`.

    from api import MiBand
    from api.events import stream
    with MiBand() as band:
        for response in stream(band, duration=30):
            print(response.type, response.subtype, response.tree())
"""
import time

from client.protocol.framing import read_frames

__all__ = ["read_events", "stream"]


def read_events(band, timeout=2.0):
    """Block up to `timeout` seconds; return every frame received."""
    band._require_connected()
    return read_frames(band.d, band.sess, time.time() + timeout,
                       stop_after_first=False, expect=None)


def stream(band, duration=None, chunk=2.0):
    """Yield frames as they arrive, for `duration` seconds (None = forever)."""
    band._require_connected()
    deadline = None if duration is None else time.time() + duration
    while deadline is None or time.time() < deadline:
        window = chunk if deadline is None else min(chunk, deadline - time.time())
        if window <= 0:
            break
        try:
            frames = read_frames(band.d, band.sess, time.time() + window,
                                 stop_after_first=False, expect=None)
        except KeyboardInterrupt:
            return
        for response in frames:
            yield response
