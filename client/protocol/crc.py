"""CRC-16/ARC, the checksum in the L1 frame trailer."""


def crc16_arc(payload: bytes) -> int:
    crc = 0
    for b in payload:
        for j in range(8):
            crc <<= 1
            if (((crc >> 16) & 1) ^ ((b >> j) & 1)) == 1:
                crc ^= 0x8005
    r = 0
    x = crc & 0xFFFFFFFF
    for i in range(32):
        r = (r << 1) | ((x >> i) & 1)
    return (r >> 16) & 0xFFFF
