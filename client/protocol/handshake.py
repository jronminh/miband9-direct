# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Derived from Gadgetbridge (https://gadgetbridge.org), AGPL-3.0-or-later:
# a Python translation of XiaomiAuthService (nonce / step3 / devinfo) and the
# SPP v2 session-config packet. See CONTRIBUTORS.md.
"""SPP v2 session state and the encrypted auth handshake."""
import logging
import os
import struct
import time

from ..log import ensure_configured

from .constants import (PREAMBLE, PT_ACK, PT_SESSION, PT_DATA, CH_PROTOBUF,
                        OP_PLAIN, OP_ENC, UUID_TX, COMMAND_TYPE_AUTH,
                        CMD_NONCE, CMD_AUTH)
from .crc import crc16_arc
from .crypto import (hmac_sha256, compute_auth_step3, aes_ctr, aes_ccm_encrypt)
from .protobuf import pb_varint, pb_bytes, pb_float, pb_get
from .framing import parse_frame
from .capture import Capture

logger = logging.getLogger(__name__)


class Session:
    def __init__(self, daemon, secret: bytes, capture=True, capture_maxlen=1000):
        self.d = daemon
        self.secret = secret
        self.seq = 0
        self.enc_key = self.dec_key = None
        self.capture = Capture(capture_maxlen)
        self.capture_enabled = capture

    # -- capture
    def enable_capture(self, enabled=True):
        self.capture_enabled = enabled
        return self

    def clear_capture(self):
        self.capture.clear()

    def _note_tx(self, raw, ptype, seq, payload):
        if not self.capture_enabled:
            return
        ch = op = None
        if ptype == PT_DATA and len(payload) >= 2:
            ch, op = payload[0], payload[1]
        self.capture.add("tx", raw.hex(), ptype=ptype, seq=seq, channel=ch,
                         op=op, body=payload.hex())

    def _note_rx(self, raw, ptype, seq, payload, rtype=None, rsubtype=None,
                 decrypted=None):
        if not self.capture_enabled:
            return
        ch = op = None
        if ptype == PT_DATA and len(payload) >= 2:
            ch, op = payload[0], payload[1]
        self.capture.add(
            "rx", raw.hex(), ptype=ptype, seq=seq, channel=ch, op=op,
            type=rtype, subtype=rsubtype,
            body=(decrypted.hex() if decrypted is not None else payload.hex()))

    # -- framing
    def frame(self, ptype, payload):
        s = self.seq & 0xFF
        self.seq += 1
        raw = (PREAMBLE + bytes([ptype, s])
               + struct.pack("<H", len(payload))
               + struct.pack("<H", crc16_arc(payload))
               + payload)
        self._note_tx(raw, ptype, s, payload)
        return raw

    def data_packet(self, channel, body, encrypted=False):
        op = OP_ENC if encrypted else OP_PLAIN
        if encrypted:
            body = aes_ctr(self.enc_key, self.enc_key, body)
        return self.frame(PT_DATA, bytes([channel, op]) + body)

    def ack(self, seq):
        raw = PREAMBLE + bytes([PT_ACK, seq & 0xFF]) + b"\x00\x00\x00\x00"
        self._note_tx(raw, PT_ACK, seq & 0xFF, b"")
        return raw

    # -- auth
    def phone_nonce_command(self, phone_nonce: bytes) -> bytes:
        phone_nonce_msg = pb_bytes(1, phone_nonce)          # PhoneNonce.nonce
        auth = pb_bytes(30, phone_nonce_msg)                # Auth.phoneNonce
        return pb_varint(1, COMMAND_TYPE_AUTH) + pb_varint(2, CMD_NONCE) + pb_bytes(3, auth)

    def auth_step3_command(self, phone_nonce, watch_nonce, watch_hmac):
        step = compute_auth_step3(self.secret, phone_nonce, watch_nonce)
        self.dec_key, self.enc_key = step[0:16], step[16:32]
        dec_nonce, enc_nonce = step[32:36], step[36:40]

        confirm = hmac_sha256(self.dec_key, watch_nonce + phone_nonce)
        if confirm != watch_hmac:
            raise ValueError("watch HMAC mismatch — wrong auth key")

        encrypted_nonces = hmac_sha256(self.enc_key, phone_nonce + watch_nonce)
        devinfo = (pb_varint(1, 0)                       # unknown1 (required)
                   + pb_float(2, 36.0)                   # phoneApiLevel (float)
                   + pb_bytes(3, b"SM-S7110")            # phoneName
                   + pb_varint(4, 224)                   # unknown3
                   + pb_bytes(5, b"VN"))                 # region
        ccm_nonce = enc_nonce + struct.pack("<I", 0) + struct.pack("<I", 0)
        encrypted_devinfo = aes_ccm_encrypt(self.enc_key, ccm_nonce, devinfo)

        step3 = pb_bytes(1, encrypted_nonces) + pb_bytes(2, encrypted_devinfo)
        auth = pb_bytes(32, step3)                       # Auth.authStep3
        return pb_varint(1, COMMAND_TYPE_AUTH) + pb_varint(2, CMD_AUTH) + pb_bytes(3, auth)


SESSION_CONFIG_PAYLOAD = bytes([
    1,                      # opcode START_SESSION_REQUEST
    1, 3, 0, 1, 0, 0,       # VERSION = 01.00.00
    2, 2, 0, 0x00, 0xfc,    # MAX_FRAME_SIZE = 0xfc00
    3, 2, 0, 0x20, 0x00,    # TX_WIN = 0x20
    4, 2, 0, 0x10, 0x27,    # SEND_TIMEOUT = 0x2710
])


def authenticate(d, sess, use_session=False, timeout=8, verbose=True, attempts=3):
    """Run the encrypted handshake.

    use_session=True mirrors Gadgetbridge's V2 flow (send session-config, then
    auth); False matches the Mi Fitness capture (step 1 is the first packet).
    Retries, and only reports success once session keys are derived.
    """
    if verbose:
        ensure_configured()
    for attempt in range(1, attempts + 1):
        if use_session:
            cfg = sess.frame(PT_SESSION, SESSION_CONFIG_PAYLOAD)
            # The SESSION frame does not consume the DATA sequence number:
            # Mi Fitness sends it with seq 0 and its step1 is also seq 0.
            sess.seq = 0
            wrote = d.write_reliable(UUID_TX, cfg)
            logger.info("auth attempt %d: session config wrote=%s", attempt, wrote)
            # wait for the band's session-config response before sending auth
            dl = time.time() + 5
            while time.time() < dl:
                try:
                    line = d.poll(timeout=1)
                except TimeoutError:
                    continue
                except EOFError:
                    return False
                if line.startswith("EVENT DISCONNECTED"):
                    return False
                if line.startswith("NOTIFY "):
                    raw = bytes.fromhex(line.split(" ", 2)[2])
                    fr = parse_frame(raw)
                    if fr:
                        sess._note_rx(raw, fr[0], fr[1], fr[2])
                    if fr and fr[0] == PT_SESSION:
                        logger.debug("session config response received")
                        break
        pn = os.urandom(16)
        step1 = sess.data_packet(CH_PROTOBUF, sess.phone_nonce_command(pn))
        wrote = d.write_reliable(UUID_TX, step1)
        logger.info("auth attempt %d: step1 wrote=%s", attempt, wrote)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = d.poll(timeout=3)
            except TimeoutError:
                continue
            except EOFError:
                return False
            if line.startswith("EVENT DISCONNECTED"):
                return False
            if not line.startswith("NOTIFY "):
                continue
            _, uuid, hexv = line.split(" ", 2)
            raw = bytes.fromhex(hexv)
            fr = parse_frame(raw)
            if not fr:
                continue
            ptype, seq, payload = fr
            if ptype != PT_DATA:
                sess._note_rx(raw, ptype, seq, payload)
                continue
            d.write_reliable(UUID_TX, sess.ack(seq))
            ch, op = payload[0], payload[1]
            body = payload[2:]
            if op == OP_ENC and sess.dec_key:
                body = aes_ctr(sess.dec_key, sess.dec_key, body)
            ctype = pb_get(body, 1, 0)
            csub = pb_get(body, 2, 0)
            sess._note_rx(raw, ptype, seq, payload, rtype=ctype, rsubtype=csub,
                          decrypted=body)
            logger.debug("RX ch=%d op=%d body=%s", ch, op, body.hex())
            if ch == CH_PROTOBUF and op == OP_PLAIN:
                auth = pb_get(body, 3, 2)
                if ctype == COMMAND_TYPE_AUTH and csub == CMD_NONCE and auth:
                    wn = pb_get(auth, 31, 2)
                    if wn:
                        watch_nonce = pb_get(wn, 1, 2)
                        watch_hmac = pb_get(wn, 2, 2)
                        logger.debug("watch nonce=%s hmac=%s",
                                     watch_nonce.hex(), watch_hmac.hex())
                        step3 = sess.data_packet(
                            CH_PROTOBUF,
                            sess.auth_step3_command(pn, watch_nonce, watch_hmac))
                        wrote3 = d.write_reliable(UUID_TX, step3)
                        logger.info("auth step3 wrote=%s", wrote3)
                elif (ctype == COMMAND_TYPE_AUTH and csub == CMD_AUTH
                      and sess.enc_key is not None):
                    logger.info("AUTHENTICATED")
                    return True
        logger.warning("auth attempt %d failed", attempt)
    logger.error("authentication failed after %d attempt(s)", attempts)
    return False
