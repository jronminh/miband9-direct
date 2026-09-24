import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

public class CryptoTest {
    static byte[] hex(String s) {
        int n = s.length() / 2;
        byte[] b = new byte[n];
        for (int i = 0; i < n; i++) b[i] = (byte) Integer.parseInt(s.substring(2*i, 2*i+2), 16);
        return b;
    }
    static String toHex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    static byte[] hmacSha256(byte[] key, byte[] msg) throws Exception {
        Mac m = Mac.getInstance("HmacSHA256");
        m.init(new SecretKeySpec(key, "HmacSHA256"));
        return m.doFinal(msg);
    }

    static byte[] aesCtr(byte[] key, byte[] iv, byte[] data) throws Exception {
        Cipher c = Cipher.getInstance("AES/CTR/NoPadding");
        c.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key, "AES"), new IvParameterSpec(iv));
        return c.doFinal(data);
    }

    // -- manual AES-CCM (RFC 3610 / NIST SP800-38C), no associated data --
    static byte[] ecbBlock(SecretKeySpec key, byte[] block) throws Exception {
        Cipher c = Cipher.getInstance("AES/ECB/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, key);
        return c.doFinal(block);
    }

    static byte[] xor(byte[] a, byte[] b, int len) {
        byte[] out = new byte[len];
        for (int i = 0; i < len; i++) out[i] = (byte) (a[i] ^ b[i]);
        return out;
    }

    static byte[] aesCcmEncrypt(byte[] keyBytes, byte[] nonce, byte[] plaintext, int tagLen) throws Exception {
        SecretKeySpec key = new SecretKeySpec(keyBytes, "AES");
        int n = nonce.length;      // 12
        int L = 15 - n;            // 3
        int M = tagLen;            // 4
        int p = plaintext.length;

        // B0
        byte[] b0 = new byte[16];
        b0[0] = (byte) (((M - 2) / 2 << 3) | (L - 1)); // Adata=0
        System.arraycopy(nonce, 0, b0, 1, n);
        long len = p;
        for (int i = 0; i < L; i++) {
            b0[15 - i] = (byte) (len & 0xFF);
            len >>= 8;
        }

        // CBC-MAC over B0 then padded plaintext blocks
        byte[] y = ecbBlock(key, b0);
        int off = 0;
        while (off < p) {
            byte[] block = new byte[16];
            int take = Math.min(16, p - off);
            System.arraycopy(plaintext, off, block, 0, take);
            byte[] xored = xor(block, y, 16);
            y = ecbBlock(key, xored);
            off += take;
        }
        byte[] T = y; // full 16-byte MAC, truncate to M later after XOR with S0

        // CTR keystream + A0 for S0
        byte[] a0 = new byte[16];
        a0[0] = (byte) (L - 1); // Adata=0, M field=0 for counter blocks
        System.arraycopy(nonce, 0, a0, 1, n);
        // counter = 0 in a0 (already zero)
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

        byte[] tag = xor(T, s0, M);
        byte[] out = new byte[p + M];
        System.arraycopy(ciphertext, 0, out, 0, p);
        System.arraycopy(tag, 0, out, p, M);
        return out;
    }

    public static void main(String[] args) throws Exception {
        byte[] key = hex("000102030405060708090a0b0c0d0e0f");
        byte[] msg = "hello world".getBytes("UTF-8");
        System.out.println("hmac=" + toHex(hmacSha256(key, msg)));

        byte[] ctrKey = hex("101112131415161718191a1b1c1d1e1f");
        byte[] data = hex("00112233445566778899aabbccddeeff0011223344");
        System.out.println("ctr=" + toHex(aesCtr(ctrKey, ctrKey, data)));

        byte[] ccmKey = hex("202122232425262728292a2b2c2d2e2f");
        byte[] nonce = new byte[12];
        byte[] noncePrefix = hex("aabbccdd0000000000000000");
        System.arraycopy(noncePrefix, 0, nonce, 0, 12);
        byte[] plain = "devinfo-test-payload".getBytes("UTF-8");
        byte[] ct = aesCcmEncrypt(ccmKey, nonce, plain, 4);
        System.out.println("ccm=" + toHex(ct));
        System.out.println("expect=8f8654da856fadb3375eb11f3d2e8fed70cbf909b147630c");
        System.out.println("MATCH=" + toHex(ct).equals("8f8654da856fadb3375eb11f3d2e8fed70cbf909b147630c"));
    }
}
