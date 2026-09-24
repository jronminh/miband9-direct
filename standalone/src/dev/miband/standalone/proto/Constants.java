package dev.miband.standalone.proto;

/** Xiaomi SPP v2 wire constants. Port of client/protocol/constants.py. */
public final class Constants {
    private Constants() {}

    public static final byte[] PREAMBLE = {(byte) 0xA5, (byte) 0xA5};

    public static final int PT_ACK = 1, PT_SESSION = 2, PT_DATA = 3;
    public static final int CH_PROTOBUF = 1, CH_DATA = 2, CH_ACTIVITY = 5;
    public static final int OP_PLAIN = 1, OP_ENC = 2;

    public static final String UUID_TX = "0000005f-0000-1000-8000-00805f9b34fb"; // write to band
    public static final String UUID_RX = "0000005e-0000-1000-8000-00805f9b34fb"; // notify from band
    public static final String UUID_SERVICE = "0000fe95-0000-1000-8000-00805f9b34fb";

    public static final int COMMAND_TYPE_AUTH = 1;
    public static final int CMD_NONCE = 26, CMD_AUTH = 27;
}
