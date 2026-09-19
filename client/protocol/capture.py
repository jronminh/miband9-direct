"""In-memory capture of every frame in both directions.

A `Session` owns a `Capture` buffer that records each outbound frame it builds
(TX) and each inbound frame it parses (RX), including the raw L1 bytes and, for
encrypted DATA frames, the decrypted payload. This is the structured equivalent
of the DEBUG log, for programmatic use (analysis, replay, feeding the API).
"""
import time
from collections import deque
from dataclasses import asdict, dataclass


@dataclass
class Frame:
    """One captured frame. `body` is decrypted for encrypted DATA frames."""

    ts: float
    direction: str            # "tx" | "rx"
    raw: str                  # full L1 frame, hex
    ptype: int | None = None
    seq: int | None = None
    channel: int | None = None
    op: int | None = None
    type: int | None = None
    subtype: int | None = None
    body: str | None = None   # frame payload (channel+op+body for DATA), hex

    def to_dict(self):
        return asdict(self)


class Capture:
    """A bounded, iterable buffer of `Frame`s (oldest dropped first).

    `on_frame`, if set, is called with each new `Frame` as it is added (e.g. for
    a live monitor); exceptions from it are swallowed so capture never breaks
    the protocol path.
    """

    def __init__(self, maxlen=1000, on_frame=None):
        self.frames = deque(maxlen=maxlen)
        self.on_frame = on_frame

    def add(self, direction, raw, ptype=None, seq=None, channel=None, op=None,
            type=None, subtype=None, body=None):
        frame = Frame(ts=time.time(), direction=direction, raw=raw, ptype=ptype,
                      seq=seq, channel=channel, op=op, type=type,
                      subtype=subtype, body=body)
        self.frames.append(frame)
        callback = self.on_frame
        if callback is not None:
            try:
                callback(frame)
            except Exception:
                pass
        return frame

    def clear(self):
        self.frames.clear()

    def to_list(self):
        return [f.to_dict() for f in self.frames]

    def __iter__(self):
        return iter(self.frames)

    def __len__(self):
        return len(self.frames)

    def __getitem__(self, i):
        return self.frames[i]
