package dev.miband.standalone.proto;

import static dev.miband.standalone.proto.Constants.*;
import static dev.miband.standalone.proto.Protobuf.*;

import java.security.SecureRandom;
import java.util.Locale;

/**
 * SPP v2 session state and the encrypted auth handshake, driven by GATT
 * callbacks instead of a blocking poll loop. Port of
 * client/protocol/handshake.py (Session + authenticate()).
 */
public final class XiaoSession {

    public interface Transport {
        /** Write bytes to the band's write characteristic (UUID_TX), reliably. */
        void writeToBand(byte[] data);
    }

    public interface Listener {
        void onAuthResult(boolean success, String reason);
        /** A decoded, already-ack'd Command{type,subtype} reply/push, post-auth. */
        void onResponse(int type, int subtype, byte[] body);
        void onLog(String msg);
    }

    private static final byte[] SESSION_CONFIG_PAYLOAD = {
            1,                              // opcode START_SESSION_REQUEST
            1, 3, 0, 1, 0, 0,               // VERSION = 01.00.00
            2, 2, 0, (byte) 0x00, (byte) 0xfc, // MAX_FRAME_SIZE = 0xfc00
            3, 2, 0, (byte) 0x20, 0x00,     // TX_WIN = 0x20
            4, 2, 0, (byte) 0x10, 0x27,     // SEND_TIMEOUT = 0x2710
    };

    private enum State { IDLE, AWAIT_SESSION_RESP, AWAIT_NONCE_REPLY, AWAIT_AUTH_CONFIRM, READY, FAILED }

    private final byte[] secret;
    private final SecureRandom rnd = new SecureRandom();
    private int seq = 0;

    private byte[] encKey, decKey;
    private byte[] phoneNonce;
    private State state = State.IDLE;
    private boolean useSession = true;

    public XiaoSession(byte[] secret16) {
        if (secret16 == null || secret16.length != 16) {
            throw new IllegalArgumentException("auth key must be 16 bytes");
        }
        this.secret = secret16;
    }

    public boolean isReady() {
        return state == State.READY;
    }

    // -- low-level framing (mirrors Session.frame / data_packet / ack) --

    public byte[] frame(int ptype, byte[] payload) {
        int s = seq & 0xFF;
        seq++;
        byte[] len = u16le(payload.length);
        byte[] crc = u16le(Crc16.arc(payload));
        return concatAll(PREAMBLE, new byte[]{(byte) ptype, (byte) s}, len, crc, payload);
    }

    public byte[] dataPacket(int channel, byte[] body, boolean encrypted) {
        int op = encrypted ? OP_ENC : OP_PLAIN;
        byte[] b = body;
        if (encrypted) {
            b = Crypto.aesCtr(encKey, encKey, body); // IV == key, per protocol
        }
        return frame(PT_DATA, concatAll(new byte[]{(byte) channel, (byte) op}, b));
    }

    public byte[] ack(int seqToAck) {
        return concatAll(PREAMBLE, new byte[]{(byte) PT_ACK, (byte) (seqToAck & 0xFF)},
                new byte[]{0, 0, 0, 0});
    }

    /** Build an encrypted post-auth Command{type,subtype,body} data packet. Call only when isReady(). */
    public byte[] buildCommand(int ctype, int csub, byte[] body) {
        byte[] cmd = concatAll(pbVarint(1, ctype), pbVarint(2, csub), body);
        return dataPacket(CH_PROTOBUF, cmd, true);
    }

    // -- handshake --

    /** Kick off the handshake; writes the first packet(s) via transport. */
    public void startAuth(Transport t, boolean useSessionConfig, Listener l) {
        this.useSession = useSessionConfig;
        if (useSessionConfig) {
            byte[] cfg = frame(PT_SESSION, SESSION_CONFIG_PAYLOAD);
            seq = 0; // SESSION frame does not consume the DATA sequence number
            state = State.AWAIT_SESSION_RESP;
            l.onLog("auth: session config sent");
            t.writeToBand(cfg);
        } else {
            sendPhoneNonce(t, l);
        }
    }

    private void sendPhoneNonce(Transport t, Listener l) {
        phoneNonce = new byte[16];
        rnd.nextBytes(phoneNonce);
        byte[] phoneNonceMsg = pbBytes(1, phoneNonce);
        byte[] auth = pbBytes(30, phoneNonceMsg);
        byte[] body = concatAll(pbVarint(1, COMMAND_TYPE_AUTH), pbVarint(2, CMD_NONCE), pbBytes(3, auth));
        byte[] step1 = dataPacketPlainAuth(body);
        state = State.AWAIT_NONCE_REPLY;
        l.onLog("auth: step1 (phone nonce) sent");
        t.writeToBand(step1);
    }

    // step1/auth frames are sent unencrypted (no key yet) but still as PT_DATA/OP_PLAIN
    private byte[] dataPacketPlainAuth(byte[] body) {
        return frame(PT_DATA, concatAll(new byte[]{(byte) CH_PROTOBUF, (byte) OP_PLAIN}, body));
    }

    /** Feed one raw notification payload (already the full L1 frame bytes) from UUID_RX. */
    public void onNotify(byte[] raw, Transport t, Listener l) {
        Frame fr = Frame.parse(raw);
        if (fr == null) return;

        if (fr.ptype == PT_SESSION) {
            if (state == State.AWAIT_SESSION_RESP) {
                l.onLog("auth: session config response received");
                sendPhoneNonce(t, l);
            }
            return;
        }
        if (fr.ptype != PT_DATA) return;

        // ack every DATA frame we see, per protocol
        t.writeToBand(ack(fr.seq));

        if (fr.payload.length < 2) return;
        int ch = fr.payload[0] & 0xFF;
        int op = fr.payload[1] & 0xFF;
        byte[] body = new byte[fr.payload.length - 2];
        System.arraycopy(fr.payload, 2, body, 0, body.length);
        if (op == OP_ENC && decKey != null) {
            body = Crypto.aesCtr(decKey, decKey, body);
        }
        Long ctypeL = pbGetVarint(body, 1);
        Long csubL = pbGetVarint(body, 2);
        if (ctypeL == null || csubL == null) return;
        int ctype = ctypeL.intValue();
        int csub = csubL.intValue();

        if (ch != CH_PROTOBUF) return;

        if (ctype == COMMAND_TYPE_AUTH && csub == CMD_NONCE && state == State.AWAIT_NONCE_REPLY) {
            byte[] auth = pbGetBytes(body, 3, WT_BYTES);
            if (auth == null) return;
            byte[] wn = pbGetBytes(auth, 31, WT_BYTES);
            if (wn == null) return;
            byte[] watchNonce = pbGetBytes(wn, 1, WT_BYTES);
            byte[] watchHmac = pbGetBytes(wn, 2, WT_BYTES);
            if (watchNonce == null || watchHmac == null) return;
            try {
                sendAuthStep3(t, l, watchNonce, watchHmac);
            } catch (IllegalStateException e) {
                state = State.FAILED;
                l.onAuthResult(false, e.getMessage());
            }
        } else if (ctype == COMMAND_TYPE_AUTH && csub == CMD_AUTH && state == State.AWAIT_AUTH_CONFIRM
                && encKey != null) {
            state = State.READY;
            l.onLog("AUTHENTICATED");
            l.onAuthResult(true, null);
        } else if (state == State.READY) {
            l.onResponse(ctype, csub, body);
        }
    }

    private void sendAuthStep3(Transport t, Listener l, byte[] watchNonce, byte[] watchHmac) {
        byte[] step = Crypto.computeAuthStep3(secret, phoneNonce, watchNonce);
        decKey = java.util.Arrays.copyOfRange(step, 0, 16);
        encKey = java.util.Arrays.copyOfRange(step, 16, 32);
        byte[] encNonce = java.util.Arrays.copyOfRange(step, 36, 40);

        byte[] confirm = Crypto.hmacSha256(decKey, concatAll(watchNonce, phoneNonce));
        if (!java.util.Arrays.equals(confirm, watchHmac)) {
            throw new IllegalStateException("watch HMAC mismatch - wrong auth key");
        }

        byte[] encryptedNonces = Crypto.hmacSha256(encKey, concatAll(phoneNonce, watchNonce));
        byte[] devinfo = concatAll(
                pbVarint(1, 0),
                pbFloat(2, 36.0f),
                pbBytes(3, "SM-S7110"),
                pbVarint(4, 224),
                pbBytes(5, "VN"));
        byte[] ccmNonce = concatAll(encNonce, new byte[]{0, 0, 0, 0}, new byte[]{0, 0, 0, 0});
        byte[] encryptedDevinfo = Crypto.aesCcmEncrypt(encKey, ccmNonce, devinfo);

        byte[] step3 = concatAll(pbBytes(1, encryptedNonces), pbBytes(2, encryptedDevinfo));
        byte[] auth = pbBytes(32, step3);
        byte[] body = concatAll(pbVarint(1, COMMAND_TYPE_AUTH), pbVarint(2, CMD_AUTH), pbBytes(3, auth));
        byte[] pkt = dataPacketPlainAuth(body);
        state = State.AWAIT_AUTH_CONFIRM;
        l.onLog("auth: step3 sent");
        t.writeToBand(pkt);
    }

    private static byte[] u16le(int v) {
        return new byte[]{(byte) (v & 0xFF), (byte) ((v >>> 8) & 0xFF)};
    }
}
