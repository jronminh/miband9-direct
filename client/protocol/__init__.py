"""Xiaomi SPP v2 protocol: framing, crypto, transport, and the auth handshake."""
from .constants import (PREAMBLE, PT_ACK, PT_SESSION, PT_DATA,
                        CH_PROTOBUF, CH_DATA, CH_ACTIVITY, OP_PLAIN, OP_ENC,
                        UUID_TX, UUID_RX, COMMAND_TYPE_AUTH, CMD_NONCE, CMD_AUTH)
from .crc import crc16_arc
from .protobuf import (ProtobufError, pb_varint, pb_bytes, pb_float, pb_read,
                       pb_get, pb_tree)
from .crypto import (hmac_sha256, compute_auth_step3, aes_ctr, aes_ccm_encrypt)
from .framing import Response, parse_frame, read_frames
from .daemon import Daemon
from .capture import Capture, Frame
from .handshake import Session, SESSION_CONFIG_PAYLOAD, authenticate

__all__ = [
    "PREAMBLE", "PT_ACK", "PT_SESSION", "PT_DATA",
    "CH_PROTOBUF", "CH_DATA", "CH_ACTIVITY", "OP_PLAIN", "OP_ENC",
    "UUID_TX", "UUID_RX", "COMMAND_TYPE_AUTH", "CMD_NONCE", "CMD_AUTH",
    "crc16_arc", "ProtobufError", "pb_varint", "pb_bytes", "pb_float",
    "pb_read", "pb_get", "pb_tree", "hmac_sha256", "compute_auth_step3",
    "aes_ctr", "aes_ccm_encrypt", "Response", "parse_frame", "read_frames",
    "Daemon", "Capture", "Frame", "Session", "SESSION_CONFIG_PAYLOAD",
    "authenticate",
]
