package android.bluetooth;

import java.util.UUID;

public final class BluetoothGattCharacteristic {
    public static final int PROPERTY_NOTIFY = 0x10;
    public static final int PROPERTY_INDICATE = 0x20;
    public static final int PROPERTY_WRITE_NO_RESPONSE = 0x08;
    public static final int WRITE_TYPE_DEFAULT = 2;
    public static final int WRITE_TYPE_NO_RESPONSE = 1;
    public UUID getUuid() { return null; }
    public int getProperties() { return 0; }
    public boolean setValue(byte[] value) { return false; }
    public byte[] getValue() { return null; }
    public BluetoothGattDescriptor getDescriptor(UUID uuid) { return null; }
    public void setWriteType(int writeType) {}
    public int getWriteType() { return 0; }
}
