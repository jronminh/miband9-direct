package android.bluetooth;

import java.util.UUID;

public final class BluetoothGattDescriptor {
    public static final byte[] ENABLE_NOTIFICATION_VALUE = {0x01, 0x00};
    public static final byte[] ENABLE_INDICATION_VALUE = {0x02, 0x00};
    public UUID getUuid() { return null; }
    public boolean setValue(byte[] value) { return false; }
    public byte[] getValue() { return null; }
}
