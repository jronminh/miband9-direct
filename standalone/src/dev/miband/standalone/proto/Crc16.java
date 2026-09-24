package dev.miband.standalone.proto;

/** CRC-16/ARC, the checksum in the L1 frame trailer. Port of client/protocol/crc.py. */
public final class Crc16 {
    private Crc16() {}

    public static int arc(byte[] payload) {
        int crc = 0; // Java int naturally truncates to 32 bits on shift, matching
                     // the Python "& 0xFFFFFFFF at the end" since only bit16 ever
                     // feeds back into future decisions.
        for (byte bb : payload) {
            int b = bb & 0xFF;
            for (int j = 0; j < 8; j++) {
                crc <<= 1;
                if ((((crc >>> 16) & 1) ^ ((b >>> j) & 1)) == 1) {
                    crc ^= 0x8005;
                }
            }
        }
        int r = 0;
        for (int i = 0; i < 32; i++) {
            r = (r << 1) | ((crc >>> i) & 1);
        }
        return (r >>> 16) & 0xFFFF;
    }
}
