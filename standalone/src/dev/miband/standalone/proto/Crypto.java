package dev.miband.standalone.proto;

import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * Crypto primitives for the Xiaomi auth handshake and data channel.
 * Port of client/protocol/crypto.py.
 *
 * AES-CCM is implemented manually (CTR encryption + CBC-MAC, RFC 3610) on
 * top of plain AES-ECB single-block encryption instead of relying on the
 * platform's "AES/CCM/NoPadding" transformation: that transformation is only
 * guaranteed present via Conscrypt from API 28, while AES-ECB is available
 * on every Android version since API 1, so this keeps minSdk 26 usable and
 * was verified byte-for-byte against Python's `cryptography` AESCCM output
 * (see standalone/test/CryptoTest.java).
 */
public final class Crypto {
    private Crypto() {}

    public static byte[] hmacSha256(byte[] key, byte[] msg) {
        try {
            Mac m = Mac.getInstance("HmacSHA256");
            m.init(new SecretKeySpec(key, "HmacSHA256"));
            return m.doFinal(msg);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    /** HKDF-like expansion with repeated HMAC and a "miwear-auth"+counter label. */
    public static byte[] computeAuthStep3(byte[] secret, byte[] phoneNonce, byte[] watchNonce) {
        byte[] inner = hmacSha256(concat(phoneNonce, watchNonce), secret);
        byte[] out = new byte[0];
        byte[] tmp = new byte[0];
        int b = 1;
        while (out.length < 64) {
            byte[] label = concat(tmp, "miwear-auth".getBytes(java.nio.charset.StandardCharsets.US_ASCII),
                    new byte[]{(byte) b});
            tmp = hmacSha256(inner, label);
            out = concat(out, tmp);
            b++;
        }
        return Arrays.copyOf(out, 64);
    }

    /** AES-CTR; symmetric (same call for encrypt/decrypt). IV is used as-is (may equal key, per protocol). */
    public static byte[] aesCtr(byte[] key, byte[] iv, byte[] data) {
        try {
            Cipher c = Cipher.getInstance("AES/CTR/NoPadding");
            c.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key, "AES"), new IvParameterSpec(iv));
            return c.doFinal(data);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    /** AES-CCM encrypt, no associated data, 4-byte tag. Returns ciphertext||tag. */
    public static byte[] aesCcmEncrypt(byte[] keyBytes, byte[] nonce, byte[] plaintext) {
        return aesCcmEncrypt(keyBytes, nonce, plaintext, 4);
    }

    public static byte[] aesCcmEncrypt(byte[] keyBytes, byte[] nonce, byte[] plaintext, int tagLen) {
        try {
            SecretKeySpec key = new SecretKeySpec(keyBytes, "AES");
            int n = nonce.length;
            int L = 15 - n;
            int M = tagLen;
            int p = plaintext.length;

            byte[] b0 = new byte[16];
            b0[0] = (byte) (((M - 2) / 2 << 3) | (L - 1)); // Adata=0 (no AAD)
            System.arraycopy(nonce, 0, b0, 1, n);
            long len = p;
            for (int i = 0; i < L; i++) {
                b0[15 - i] = (byte) (len & 0xFF);
                len >>= 8;
            }

            byte[] y = ecbBlock(key, b0);
            int off = 0;
            while (off < p) {
                byte[] block = new byte[16];
                int take = Math.min(16, p - off);
                System.arraycopy(plaintext, off, block, 0, take);
                y = ecbBlock(key, xor(block, y, 16));
                off += take;
            }
            byte[] mac = y;

            byte[] a0 = new byte[16];
            a0[0] = (byte) (L - 1);
            System.arraycopy(nonce, 0, a0, 1, n);
            byte[] s0 = ecbBlock(key, a0);

            byte[] ciphertext = new byte[p];
            off = 0;
            int counter = 1;
            while (off < p) {
                byte[] ai = new byte[16];
                ai[0] = (byte) (L - 1);
                System.arraycopy(nonce, 0, ai, 1, n);
                long ctr = counter;
                for (int i = 0; i < L; i++) {
                    ai[15 - i] = (byte) (ctr & 0xFF);
                    ctr >>= 8;
                }
                byte[] si = ecbBlock(key, ai);
                int take = Math.min(16, p - off);
                for (int i = 0; i < take; i++) {
                    ciphertext[off + i] = (byte) (plaintext[off + i] ^ si[i]);
                }
                off += take;
                counter++;
            }

            byte[] tag = xor(mac, s0, M);
            byte[] out = new byte[p + M];
            System.arraycopy(ciphertext, 0, out, 0, p);
            System.arraycopy(tag, 0, out, p, M);
            return out;
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private static byte[] ecbBlock(SecretKeySpec key, byte[] block) throws Exception {
        Cipher c = Cipher.getInstance("AES/ECB/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, key);
        return c.doFinal(block);
    }

    private static byte[] xor(byte[] a, byte[] b, int len) {
        byte[] out = new byte[len];
        for (int i = 0; i < len; i++) out[i] = (byte) (a[i] ^ b[i]);
        return out;
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
}
