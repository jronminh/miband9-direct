package android.bluetooth;

public interface BluetoothProfile {
    int STATE_DISCONNECTED = 0;
    int STATE_CONNECTING = 1;
    int STATE_CONNECTED = 2;
    int STATE_DISCONNECTING = 3;
    int GATT = 7;
    int GATT_SERVER = 8;
}
