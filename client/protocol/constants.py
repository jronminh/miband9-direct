# SPDX-License-Identifier: AGPL-3.0-or-later
"""Xiaomi SPP v2 wire constants (L1 framing and command IDs)."""

PREAMBLE = b"\xa5\xa5"

PT_ACK, PT_SESSION, PT_DATA = 1, 2, 3
CH_PROTOBUF, CH_DATA, CH_ACTIVITY = 1, 2, 5
OP_PLAIN, OP_ENC = 1, 2

UUID_TX = "0000005f-0000-1000-8000-00805f9b34fb"   # write to band
UUID_RX = "0000005e-0000-1000-8000-00805f9b34fb"   # notify from band

COMMAND_TYPE_AUTH = 1
CMD_NONCE, CMD_AUTH = 26, 27
