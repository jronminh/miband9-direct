package dev.miband.standalone.proto;

/** L1 frame codec. Port of client/protocol/framing.py (parse_frame only; the
 *  encode side lives in XiaoSession.frame()). */
public final class Frame {
    public final int ptype;
    public final int seq;
    public final byte[] payload;

    private Frame(int ptype, int seq, byte[] payload) {
        this.ptype = ptype;
        this.seq = seq;
        this.payload = payload;
    }

    /** Decode one L1 frame, or null if malformed/corrupt (bad preamble, length overrun, CRC mismatch). */
    public static Frame parse(byte[] raw) {
        if (raw == null || raw.length < 8 || raw[0] != Constants.PREAMBLE[0] || raw[1] != Constants.PREAMBLE[1]) {
            return null;
        }
        int ptype = raw[2] & 0xF;
        int seq = raw[3] & 0xFF;
        int plen = (raw[4] & 0xFF) | ((raw[5] & 0xFF) << 8);
        int crc = (raw[6] & 0xFF) | ((raw[7] & 0xFF) << 8);
        if (8 + plen > raw.length) return null;
        byte[] payload = new byte[plen];
        System.arraycopy(raw, 8, payload, 0, plen);
        int actual = Crc16.arc(payload);
        if (actual != crc) return null;
        return new Frame(ptype, seq, payload);
    }
}
