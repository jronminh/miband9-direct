#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Derived from Gadgetbridge (https://gadgetbridge.org), AGPL-3.0-or-later:
# a Python translation of XiaomiActivityFileFetcher / XiaomiActivityFileId.
# See CONTRIBUTORS.md.
"""Activity file transfer: request a recorded file, reassemble its chunks.

Ported from Gadgetbridge's `XiaomiActivityFileFetcher` / `XiaomiActivityFileId`
(AGPLv3). The band serves activity data on the **Activity channel** (5) as
numbered chunks; the phone asks for one file at a time by its 7-byte id and
acks it once stored.

Wire flow (all `Command{type=8}` on the protobuf channel):
    8,1  fetch today  -> band replies with the file-id list (Health field 2)
    8,2  fetch past   -> same, for older files
    8,3  request file -> Health{activityRequestFileIds = <7-byte id>}
    8,5  ack file     -> Health{activitySyncAckFileIds   = <7-byte id>}

Each activity chunk on channel 5 is `[uint16 total][uint16 num][data...]`;
concatenating `data` across `num = 1..total` yields
`[7-byte file id][0x00][payload][uint32 LE CRC32 of everything before it]`.
"""
import logging
import time
import zlib
from dataclasses import dataclass

from .commands import command
from .protocol.constants import CH_ACTIVITY, CH_PROTOBUF, UUID_TX
from .protocol.framing import read_frames
from .protocol.protobuf import pb_bytes

logger = logging.getLogger(__name__)

CMD_FETCH_TODAY = 1
CMD_FETCH_PAST = 2
CMD_FETCH_REQUEST = 3
CMD_FETCH_ACK = 5

TYPE_ACTIVITY, TYPE_SPORTS = 0, 1
SUBTYPE_NAMES = {
    (TYPE_ACTIVITY, 0x00): "activity-daily",
    (TYPE_ACTIVITY, 0x03): "sleep-stages",
    (TYPE_ACTIVITY, 0x06): "manual-samples",
    (TYPE_ACTIVITY, 0x08): "sleep",
}
DETAIL_NAMES = {0: "details", 1: "summary", 2: "gps"}


@dataclass(frozen=True)
class ActivityFileId:
    """The 7-byte activity file identifier."""

    timestamp: int          # Unix seconds
    timezone: int           # 15-minute blocks
    version: int
    type: int
    subtype: int
    detail_type: int

    @classmethod
    def from_bytes(cls, b: bytes) -> "ActivityFileId":
        if len(b) != 7:
            raise ValueError(f"activity file id must be 7 bytes, got {len(b)}")
        ts = int.from_bytes(b[0:4], "little")
        tz = b[4] - 256 if b[4] > 127 else b[4]
        flags = b[6]
        return cls(timestamp=ts, timezone=tz, version=b[5],
                   type=(flags >> 7) & 1, subtype=(flags & 127) >> 2,
                   detail_type=flags & 3)

    def to_bytes(self) -> bytes:
        flags = (self.type << 7) | (self.subtype << 2) | self.detail_type
        return (self.timestamp.to_bytes(4, "little")
                + bytes([self.timezone & 0xFF, self.version & 0xFF, flags & 0xFF]))

    @property
    def suffix(self) -> str:
        return self.to_bytes()[4:].hex()

    @property
    def kind(self) -> str:
        return SUBTYPE_NAMES.get((self.type, self.subtype), "sports" if self.type else "unknown")

    @property
    def detail(self) -> str:
        return DETAIL_NAMES.get(self.detail_type, str(self.detail_type))

    @property
    def filename(self) -> str:
        stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime(self.timestamp))
        return (f"xiaomi_{stamp}_{self.type:02X}_{self.subtype:02X}_"
                f"{self.detail_type:02X}_v{self.version}.bin")


class ChunkAssembler:
    """Reassemble one file from its numbered activity chunks."""

    def __init__(self):
        self.buf = bytearray()
        self.total = None

    def feed(self, chunk: bytes):
        """Add a chunk; return the assembled file bytes once complete, else None."""
        if len(chunk) < 4:
            return None
        total = int.from_bytes(chunk[0:2], "little")
        num = int.from_bytes(chunk[2:4], "little")
        if num == 1:
            self.buf = bytearray()
            self.total = total
        self.buf += chunk[4:]
        if total and num == total:
            data, self.buf = bytes(self.buf), bytearray()
            return data
        return None


def verify(data: bytes) -> dict:
    """Validate an assembled activity file; return its parts.

    Layout: `[7-byte id][0x00][payload][uint32 LE crc32]`.
    """
    if len(data) < 13:
        raise ValueError(f"activity file too short ({len(data)} bytes)")
    expected = int.from_bytes(data[-4:], "little")
    actual = zlib.crc32(data[:-4]) & 0xFFFFFFFF
    if actual != expected:
        raise ValueError(f"activity crc32 mismatch: got {actual:08X} "
                         f"want {expected:08X}")
    if data[7] != 0:
        logger.warning("activity payload byte 7 is 0x%02X, expected 0x00", data[7])
    return {"file_id": ActivityFileId.from_bytes(data[0:7]),
            "payload": data[8:-4], "raw": data, "crc32": actual}


def _write(d, sess, subtype, health):
    body = pb_bytes(10, health)
    pkt = sess.data_packet(CH_PROTOBUF, command(8, subtype, body), encrypted=True)
    if not d.write_reliable(UUID_TX, pkt):
        sess.seq -= 1
        raise IOError(f"activity command 8,{subtype} was not written")


def request_file(d, sess, file_id: ActivityFileId):
    """Ask the band to send one recorded file (8,3)."""
    logger.debug("request activity file %s", file_id)
    _write(d, sess, CMD_FETCH_REQUEST, pb_bytes(2, file_id.to_bytes()))


def ack_file(d, sess, file_id: ActivityFileId):
    """Tell the band the file was received (8,5)."""
    _write(d, sess, CMD_FETCH_ACK, pb_bytes(3, file_id.to_bytes()))


def fetch_file(d, sess, file_id: ActivityFileId, timeout=8.0):
    """Request one file and return `verify()`'s dict, or None on timeout."""
    request_file(d, sess, file_id)
    assembler = ChunkAssembler()
    deadline = time.time() + timeout
    while time.time() < deadline:
        frames = read_frames(d, sess, time.time() + 1.0,
                             stop_after_first=False, expect=None)
        for resp in frames:
            if resp.channel != CH_ACTIVITY:
                continue
            logger.debug("activity chunk: %d bytes %s", len(resp.body),
                         resp.body[:4].hex())
            data = assembler.feed(resp.body)
            if data is not None:
                return verify(data)
    logger.warning("timed out waiting for activity file %s", file_id)
    return None
