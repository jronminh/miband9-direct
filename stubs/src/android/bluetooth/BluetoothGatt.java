package android.bluetooth;

import java.util.List;
import java.util.UUID;

public final class BluetoothGatt {
    public static final int GATT_SUCCESS = 0;
    public boolean discoverServices() { return false; }
    public List<BluetoothGattService> getServices() { return null; }
    public BluetoothGattService getService(UUID uuid) { return null; }
    public boolean readCharacteristic(BluetoothGattCharacteristic c) { return false; }
    public boolean writeCharacteristic(BluetoothGattCharacteristic c) { return false; }
    public boolean writeCharacteristic(BluetoothGattCharacteristic c, byte[] value, int writeType) { return false; }
    public boolean writeDescriptor(BluetoothGattDescriptor d) { return false; }
    public boolean writeDescriptor(BluetoothGattDescriptor d, byte[] value) { return false; }
    public boolean setCharacteristicNotification(BluetoothGattCharacteristic c, boolean enable) { return false; }
    public boolean requestMtu(int mtu) { return false; }
    public BluetoothDevice getDevice() { return null; }
    public void disconnect() {}
    public void close() {}
}
