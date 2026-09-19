package android.bluetooth;

import java.util.Set;

public final class BluetoothAdapter {
    public boolean isEnabled() { return false; }
    public Set<BluetoothDevice> getBondedDevices() { return null; }
    public BluetoothDevice getRemoteDevice(String address) { return null; }
}
