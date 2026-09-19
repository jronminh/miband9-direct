package android.bluetooth;

public abstract class BluetoothGattCallback {
    public void onConnectionStateChange(BluetoothGatt gatt, int status, int newState) {}
    public void onServicesDiscovered(BluetoothGatt gatt, int status) {}
    public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic c, byte[] value, int status) {}
    public void onCharacteristicWrite(BluetoothGatt gatt, BluetoothGattCharacteristic c, int status) {}
    public void onCharacteristicChanged(BluetoothGatt gatt, BluetoothGattCharacteristic c, byte[] value) {}
    public void onDescriptorWrite(BluetoothGatt gatt, BluetoothGattDescriptor d, int status) {}
    public void onMtuChanged(BluetoothGatt gatt, int mtu, int status) {}
}
