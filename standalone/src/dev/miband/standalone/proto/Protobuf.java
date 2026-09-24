package dev.miband.standalone.proto;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * Minimal protobuf wire codec (encode + lenient decode).
 * Direct port of client/protocol/protobuf.py.
 */
public final class Protobuf {
    private Protobuf() {}

    public static final int WT_VARINT = 0;
    public static final int WT_FIXED64 = 1;
    public static final int WT_BYTES = 2;
    public static final int WT_FIXED32 = 5;

    /** One decoded (field, wiretype, raw-value-bytes-or-varint) entry. */
    public static final class Field {
        public final int number;
        public final int wireType;
        public final long varint;   // valid when wireType == WT_VARINT
        public final byte[] bytes;  // valid otherwise (raw payload bytes)

        Field(int number, int wireType, long varint, byte[] bytes) {
            this.number = number;
            this.wireType = wireType;
            this.varint = varint;
            this.bytes = bytes;
        }
    }

    private static byte[] varintBytes(long n) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        long v = n;
        while (true) {
            int b = (int) (v & 0x7F);
            v >>>= 7;
            if (v != 0) {
                out.write(b | 0x80);
            } else {
                out.write(b);
                return out.toByteArray();
            }
        }
    }

    public static byte[] pbVarint(int field, long value) {
        return concat(varintBytes(((long) field << 3) | 0), varintBytes(value));
    }

    public static byte[] pbBytes(int field, byte[] value) {
        return concat(varintBytes(((long) field << 3) | 2), varintBytes(value.length), value);
    }

    public static byte[] pbBytes(int field, String value) {
        return pbBytes(field, utf8(value));
    }

    public static byte[] pbFloat(int field, float value) {
        int bits = Float.floatToIntBits(value);
        byte[] le = new byte[4];
        le[0] = (byte) (bits & 0xFF);
        le[1] = (byte) ((bits >>> 8) & 0xFF);
        le[2] = (byte) ((bits >>> 16) & 0xFF);
        le[3] = (byte) ((bits >>> 24) & 0xFF);
        return concat(varintBytes(((long) field << 3) | 5), le);
    }

    /** Lenient decode: stops cleanly on truncated/malformed input instead of throwing. */
    public static List<Field> pbRead(byte[] buf) {
        List<Field> out = new ArrayList<>();
        int i = 0;
        int len = buf.length;
        while (i < len) {
            long[] tagRes = readVarint(buf, i);
            if (tagRes == null) return out;
            long tag = tagRes[0];
            i = (int) tagRes[1];
            int fn = (int) (tag >>> 3);
            int wt = (int) (tag & 7);
            if (wt == WT_VARINT) {
                long[] r = readVarint(buf, i);
                if (r == null) return out;
                out.add(new Field(fn, wt, r[0], null));
                i = (int) r[1];
            } else if (wt == WT_BYTES) {
                long[] r = readVarint(buf, i);
                if (r == null) return out;
                int ln = (int) r[0];
                i = (int) r[1];
                if (i + ln > len || ln < 0) return out;
                byte[] v = new byte[ln];
                System.arraycopy(buf, i, v, 0, ln);
                i += ln;
                out.add(new Field(fn, wt, 0, v));
            } else if (wt == WT_FIXED32) {
                if (i + 4 > len) return out;
                byte[] v = new byte[4];
                System.arraycopy(buf, i, v, 0, 4);
                i += 4;
                out.add(new Field(fn, wt, 0, v));
            } else if (wt == WT_FIXED64) {
                if (i + 8 > len) return out;
                byte[] v = new byte[8];
                System.arraycopy(buf, i, v, 0, 8);
                i += 8;
                out.add(new Field(fn, wt, 0, v));
            } else {
                return out;
            }
        }
        return out;
    }

    /** Returns {value, nextIndex} or null if truncated/too long. */
    private static long[] readVarint(byte[] b, int i) {
        long r = 0;
        int s = 0;
        while (true) {
            if (i >= b.length) return null;
            int x = b[i] & 0xFF;
            i++;
            r |= ((long) (x & 0x7F)) << s;
            if ((x & 0x80) == 0) return new long[]{r, i};
            s += 7;
            if (s > 63) return null;
        }
    }

    /** First matching field's raw bytes (wiretype BYTES/FIXED32/FIXED64), or null. */
    public static byte[] pbGetBytes(byte[] buf, int field, int wireType) {
        for (Field f : pbRead(buf)) {
            if (f.number == field && f.wireType == wireType) return f.bytes;
        }
        return null;
    }

    /** First matching field's varint value, or null. */
    public static Long pbGetVarint(byte[] buf, int field) {
        for (Field f : pbRead(buf)) {
            if (f.number == field && f.wireType == WT_VARINT) return f.varint;
        }
        return null;
    }

    static byte[] concat(byte[]... parts) {
        int total = 0;
        for (byte[] p : parts) total += p.length;
        byte[] out = new byte[total];
        int off = 0;
        for (byte[] p : parts) {
            System.arraycopy(p, 0, out, off, p.length);
            off += p.length;
        }
        return out;
    }

    public static byte[] concatAll(byte[]... parts) {
        return concat(parts);
    }

    static byte[] utf8(String s) {
        try {
            return s.getBytes("UTF-8");
        } catch (java.io.UnsupportedEncodingException e) {
            throw new RuntimeException(e);
        }
    }
}
