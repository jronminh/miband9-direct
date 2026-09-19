# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Derived from Gadgetbridge (https://gadgetbridge.org), AGPL-3.0-or-later:
# a Python translation of XiaomiAuthService.computeAuthStep3Hmac.
# See CONTRIBUTORS.md.
"""Crypto primitives for the Xiaomi auth handshake and data channel."""
import hashlib
import hmac

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM


def hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def compute_auth_step3(secret: bytes, phone_nonce: bytes, watch_nonce: bytes) -> bytes:
    inner = hmac_sha256(phone_nonce + watch_nonce, secret)
    out, tmp, b = b"", b"", 1
    while len(out) < 64:
        tmp = hmac_sha256(inner, tmp + b"miwear-auth" + bytes([b]))
        out += tmp
        b += 1
    return out[:64]


def aes_ctr(key: bytes, iv: bytes, data: bytes) -> bytes:
    c = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
    return c.update(data) + c.finalize()


def aes_ccm_encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
    return AESCCM(key, tag_length=4).encrypt(nonce, plaintext, None)
