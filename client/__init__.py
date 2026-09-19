"""Mi Band 9 Active direct-control client.

Layers:
    client.protocol   wire protocol (framing, crypto, transport, handshake)
    client.commands   Xiaomi command builders + batch CLI
    client.session    `open_session()` (connect + auth)
    client.shell      interactive stdin session

The high-level `MiBand` API lives in the top-level `api/` package; the storage
and band-data layers live in `store/`.

Public names are re-exported lazily (PEP 562) so importing the package does not
eagerly pull in every submodule, and `python -m client.commands` / `-m
client.shell` do not warn about a pre-imported module.
"""
import importlib
import logging

_PROTOCOL = (
    "PREAMBLE", "PT_ACK", "PT_SESSION", "PT_DATA",
    "CH_PROTOBUF", "CH_DATA", "CH_ACTIVITY", "OP_PLAIN", "OP_ENC",
    "UUID_TX", "UUID_RX", "COMMAND_TYPE_AUTH", "CMD_NONCE", "CMD_AUTH",
    "crc16_arc", "ProtobufError", "pb_varint", "pb_bytes", "pb_float",
    "pb_read", "pb_get", "pb_tree", "hmac_sha256", "compute_auth_step3",
    "aes_ctr", "aes_ccm_encrypt", "Response", "parse_frame", "read_frames",
    "Daemon", "Capture", "Frame", "Session", "SESSION_CONFIG_PAYLOAD",
    "authenticate",
)
_COMMANDS = (
    "command", "NAMED", "build_notification", "build_call", "build_call_end",
    "build_dismiss", "build_clock", "load_key", "send_command",
    "send_and_listen",
)
_LAZY = {}
for _name in _PROTOCOL:
    _LAZY[_name] = "protocol"
for _name in _COMMANDS:
    _LAZY[_name] = "commands"
del _name
_LAZY["open_session"] = "session"
_LAZY["configure"] = "log"
_LAZY["ensure_configured"] = "log"

__all__ = list(_LAZY)


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module("." + submodule, __name__), name)
    globals()[name] = value  # cache for subsequent lookups
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))


# Library default: stay silent unless the application configures logging.
logging.getLogger(__name__).addHandler(logging.NullHandler())
