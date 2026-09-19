# SPDX-License-Identifier: AGPL-3.0-or-later
"""L1 frame codec and decoded `Response` objects."""
import logging
import time
from dataclasses import dataclass

from .constants import PREAMBLE, PT_DATA, OP_ENC, UUID_TX
from .crc import crc16_arc
from .crypto import aes_ctr
from .protobuf import pb_get, pb_read, pb_tree

logger = logging.getLogger(__name__)


@dataclass
class Response:
    """A decoded `Command` reply from the band."""

    type: int | None
    subtype: int | None
    channel: int
    encrypted: bool
    body: bytes

    @property
    def hex(self) -> str:
        return self.body.hex()

    def get(self, field: int, wiretype: int):
        return pb_get(self.body, field, wiretype)

    def tree(self, maxdepth: int = 4):
        return pb_tree(self.body, 1, maxdepth)

    def fields(self):
        out = []
        for fn, wt, v in pb_read(self.body):
            if wt == 0:
                val = v
            elif wt in (1, 5):
                val = v.hex()
            else:
                try:
                    s = v.decode("utf-8")
                    val = s if all(32 <= ord(c) < 127 for c in s) else v.hex()
                except Exception:
                    val = v.hex()
            out.append({"field": fn, "wiretype": wt, "value": val})
        return out

    def to_dict(self):
        return {
            "type": self.type,
            "subtype": self.subtype,
            "channel": self.channel,
            "encrypted": self.encrypted,
            "hex": self.hex,
            "fields": self.fields(),
            "tree": self.tree(),
        }


def parse_frame(raw: bytes):
    """Decode one L1 frame, or None if it is malformed/corrupt.

    Validates the declared payload length and the CRC16-ARC trailer (confirmed
    against captured band traffic), so a corrupt notification is rejected
    instead of being handed to the protobuf decoder.
    """
    if len(raw) < 8 or raw[0:2] != PREAMBLE:
        logger.debug("reject frame: short/bad preamble (%d bytes)", len(raw))
        return None
    ptype, seq = raw[2] & 0xF, raw[3]
    plen = raw[4] | (raw[5] << 8)
    crc = raw[6] | (raw[7] << 8)
    if 8 + plen > len(raw):
        logger.debug("reject frame: length overrun plen=%d have=%d", plen,
                     len(raw) - 8)
        return None
    payload = raw[8:8 + plen]
    actual = crc16_arc(payload)
    if actual != crc:
        logger.debug("reject frame: crc mismatch got=%04x want=%04x", actual, crc)
        return None
    return ptype, seq, payload


def read_frames(d, sess, deadline: float, stop_after_first=True, expect=None):
    """Read/ack/decode DATA notifications until `deadline`.

    With `stop_after_first` (command queries) it returns ~0.6s after the first
    reply; with False it keeps draining an async stream for the whole window.

    `expect=(type, subtype)` filters query replies: unrelated frames (async
    pushes, stale replies) are still acked but not returned, and the grace
    window only starts once a matching reply arrives. If nothing matches by
    the deadline, all frames are returned so no data is silently lost.
    """
    out = []
    while time.time() < deadline:
        try:
            line = d.poll(timeout=max(0.05, deadline - time.time()))
        except TimeoutError:
            continue
        except EOFError:
            raise ConnectionError("daemon closed")
        if line.startswith("EVENT DISCONNECTED"):
            raise ConnectionError("band disconnected")
        if not line.startswith("NOTIFY "):
            continue
        _, _uuid, hexv = line.split(" ", 2)
        frame_bytes = bytes.fromhex(hexv)
        fr = parse_frame(frame_bytes)
        if not fr:
            continue
        ptype, seq, payload = fr
        if ptype != PT_DATA:
            sess._note_rx(frame_bytes, ptype, seq, payload)
            logger.debug("ignore non-DATA frame type=%d seq=%d", ptype, seq)
            continue
        d.write_reliable(UUID_TX, sess.ack(seq))
        logger.debug("ack seq=%d", seq)
        ch, op = payload[0], payload[1]
        raw = payload[2:]
        if op == OP_ENC and sess.dec_key:
            raw = aes_ctr(sess.dec_key, sess.dec_key, raw)
        resp = Response(pb_get(raw, 1, 0), pb_get(raw, 2, 0), ch,
                        op == OP_ENC, raw)
        sess._note_rx(frame_bytes, ptype, seq, payload, rtype=resp.type,
                      rsubtype=resp.subtype, decrypted=raw)
        out.append(resp)
        logger.debug("RX ch=%d op=%d type=%s subtype=%s len=%d",
                     ch, op, resp.type, resp.subtype, len(raw))
        if expect is not None:
            if (resp.type, resp.subtype) == tuple(expect):
                deadline = min(deadline, time.time() + 0.6)
            else:
                logger.debug("filtered out type=%s subtype=%s (expect %s)",
                             resp.type, resp.subtype, tuple(expect))
        elif stop_after_first:
            deadline = min(deadline, time.time() + 0.6)
    if expect is not None and stop_after_first:
        matched = [r for r in out if (r.type, r.subtype) == tuple(expect)]
        if matched:
            return matched
    logger.debug("read_frames done: %d frame(s)", len(out))
    return out
