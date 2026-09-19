"""Minimal protobuf wire codec (encode, decode, inspect).

Decoding is deliberately lenient: a truncated or malformed buffer stops the
iteration instead of raising, so a corrupt band reply can never crash a caller.
"""
import struct


class ProtobufError(ValueError):
    """Raised internally when a protobuf buffer is malformed or truncated."""


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def pb_varint(field: int, value: int) -> bytes:
    return _varint((field << 3) | 0) + _varint(value)


def pb_bytes(field: int, value: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(value)) + value


def pb_float(field: int, value: float) -> bytes:
    return _varint((field << 3) | 5) + struct.pack("<f", value)


def pb_read(buf: bytes):
    """Yield (field, wiretype, value), stopping cleanly on malformed input.

    Never raises on truncated/garbage buffers: a bad frame is dropped rather
    than crashing the caller mid-decode.
    """
    i = 0
    while i < len(buf):
        try:
            tag, i = _read_varint(buf, i)
            fn, wt = tag >> 3, tag & 7
            if wt == 0:
                v, i = _read_varint(buf, i)
            elif wt == 2:
                ln, i = _read_varint(buf, i)
                if i + ln > len(buf):
                    return
                v = buf[i:i + ln]; i += ln
            elif wt == 5:
                if i + 4 > len(buf):
                    return
                v = buf[i:i + 4]; i += 4
            elif wt == 1:
                if i + 8 > len(buf):
                    return
                v = buf[i:i + 8]; i += 8
            else:
                return
        except ProtobufError:
            return
        yield fn, wt, v


def _read_varint(b, i):
    r = s = 0
    while True:
        if i >= len(b):
            raise ProtobufError("truncated varint")
        x = b[i]; i += 1
        r |= (x & 0x7F) << s
        if not (x & 0x80):
            return r, i
        s += 7
        if s > 63:
            raise ProtobufError("varint too long")


def pb_get(buf: bytes, field: int, wt: int):
    for fn, w, v in pb_read(buf):
        if fn == field and w == wt:
            return v
    return None


def pb_tree(b: bytes, depth: int = 0, maxdepth: int = 4):
    out = []
    for fn, wt, v in pb_read(b):
        pad = "  " * depth
        if wt == 0:
            out.append(f"{pad}#{fn} varint {v}")
        elif wt == 5:
            out.append(f"{pad}#{fn} fixed32 {v.hex()}")
        elif wt == 1:
            out.append(f"{pad}#{fn} fixed64 {v.hex()}")
        else:
            s = None
            try:
                s = v.decode("utf-8")
                if not all(32 <= ord(c) < 127 for c in s):
                    s = None
            except Exception:
                s = None
            if s is not None:
                out.append(f"{pad}#{fn} str {s!r}")
            elif depth < maxdepth and len(v) > 0:
                sub = pb_tree(v, depth + 1, maxdepth)
                if sub:
                    out.append(f"{pad}#{fn} msg:")
                    out.extend(sub)
                else:
                    out.append(f"{pad}#{fn} bytes {v.hex()}")
            else:
                out.append(f"{pad}#{fn} bytes {v.hex()}")
    return out
