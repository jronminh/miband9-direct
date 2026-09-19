import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.content.Context;
import android.os.Looper;

import java.lang.reflect.Method;
import java.util.Set;

public class BleProbe {
    public static void main(String[] args) {
        try {
            Class.forName("android.os.Environment")
                 .getMethod("initForCurrentUser").invoke(null);
            System.out.println("PROBE Environment.initForCurrentUser ok");
        } catch (Throwable t) {
            System.out.println("PROBE Environment.initForCurrentUser threw: " + t);
        }
        try {
            Class.forName("android.app.ActivityThread")
                 .getMethod("initializeMainlineModules").invoke(null);
            System.out.println("PROBE initializeMainlineModules ok");
        } catch (Throwable t) {
            System.out.println("PROBE initializeMainlineModules threw: " + t);
            if (t.getCause() != null)
                System.out.println("PROBE   cause: " + t.getCause());
        }
        try {
            Looper.prepareMainLooper();
        } catch (Throwable t) {
            System.out.println("PROBE prepareMainLooper: " + t);
        }
        try {
            Context ctx = systemContext();
            System.out.println("PROBE context=" + ctx);

            // 1) raw service manager access
            Object binder = null;
            try {
                Class<?> sm = Class.forName("android.os.ServiceManager");
                binder = sm.getMethod("getService", String.class)
                           .invoke(null, "bluetooth_manager");
                System.out.println("PROBE ServiceManager bluetooth_manager=" + binder);
            } catch (Throwable t) {
                System.out.println("PROBE ServiceManager threw: " + t);
            }

            // 1b) interrogate IBluetoothManager directly
            if (binder != null) {
                try {
                    Class<?> stub = Class.forName("android.bluetooth.IBluetoothManager$Stub");
                    Object mgr = stub.getMethod("asInterface",
                            Class.forName("android.os.IBinder")).invoke(null, binder);
                    System.out.println("PROBE IBluetoothManager=" + mgr);
                    for (Method m : mgr.getClass().getMethods()) {
                        if (m.getDeclaringClass() == Object.class) continue;
                        System.out.println("PROBE   IBM." + m.getName()
                            + java.util.Arrays.toString(m.getParameterTypes()));
                    }
                    try {
                        Object bt = mgr.getClass().getMethod("getBluetooth").invoke(mgr);
                        System.out.println("PROBE getBluetooth()=" + bt);
                    } catch (Throwable t) {
                        System.out.println("PROBE getBluetooth() threw: " + t);
                        if (t.getCause() != null)
                            System.out.println("PROBE   cause: " + t.getCause());
                    }
                } catch (Throwable t) {
                    System.out.println("PROBE IBluetoothManager threw: " + t);
                }
            }

            // 2) static getDefaultAdapter()
            try {
                Method m = BluetoothAdapter.class.getMethod("getDefaultAdapter");
                Object def = m.invoke(null);
                System.out.println("PROBE getDefaultAdapter()=" + def);
            } catch (Throwable t) {
                System.out.println("PROBE getDefaultAdapter() threw: " + t);
                if (t.getCause() != null) System.out.println("PROBE   cause: " + t.getCause());
            }

            // 3) hidden getDefaultAdapter(Context)
            try {
                Method m = BluetoothAdapter.class.getMethod("getDefaultAdapter", Context.class);
                Object def = m.invoke(null, ctx);
                System.out.println("PROBE getDefaultAdapter(ctx)=" + def);
            } catch (Throwable t) {
                System.out.println("PROBE getDefaultAdapter(ctx) threw: " + t);
            }

            // 4) via BluetoothManager
            BluetoothManager bm =
                (BluetoothManager) ctx.getSystemService(Context.BLUETOOTH_SERVICE);
            System.out.println("PROBE bm=" + bm);
            for (Method m : bm.getClass().getMethods()) {
                if (m.getDeclaringClass() == Object.class) continue;
                System.out.println("PROBE   BM." + m.getName()
                    + java.util.Arrays.toString(m.getParameterTypes()));
            }
            BluetoothAdapter a = bm.getAdapter();
            System.out.println("PROBE bm.getAdapter()=" + a);

            if (a == null) {
                System.out.println("PROBE adapter is null; stopping");
                Looper.loop();
                return;
            }

            System.out.println("PROBE enabled=" + a.isEnabled());
            BluetoothDevice target = null;
            Set<BluetoothDevice> bonded = a.getBondedDevices();
            if (bonded != null) {
                for (BluetoothDevice d : bonded) {
                    String n = d.getName();
                    System.out.println("PROBE bonded " + d.getAddress() + " " + n);
                }
            }

            int[] profiles = {7, 8, 1, 2, 3, 4, 5, 6, 9, 10, 11, 12,
                              13, 14, 15, 16, 17, 18, 19, 20, 21, 22};
            for (int p : profiles) {
                try {
                    java.util.List<BluetoothDevice> cds = bm.getConnectedDevices(p);
                    if (cds == null || cds.isEmpty()) continue;
                    for (BluetoothDevice d : cds) {
                        String n = d.getName();
                        System.out.println("PROBE connected profile=" + p + " "
                            + d.getAddress() + " " + n);
                        if (n != null && n.toLowerCase().contains("band")) target = d;
                    }
                } catch (Throwable t) {
                    System.out.println("PROBE profile " + p + " threw: " + t);
                }
            }
            if (args.length > 0) target = a.getRemoteDevice(args[0]);

            if (target != null) {
                System.out.println("PROBE connecting to " + target.getAddress()
                    + " " + target.getName());
                BluetoothGatt g = target.connectGatt(ctx, false,
                    new BluetoothGattCallback() {
                        @Override
                        public void onConnectionStateChange(
                                BluetoothGatt gatt, int status, int newState) {
                            System.out.println("PROBE state status=" + status
                                + " new=" + newState);
                            if (newState == BluetoothProfile.STATE_CONNECTED) {
                                System.out.println("PROBE GATT_CONNECTED");
                                boolean ok = gatt.discoverServices();
                                System.out.println("PROBE discoverServices=" + ok);
                            }
                        }

                        @Override
                        public void onServicesDiscovered(BluetoothGatt gatt, int status) {
                            System.out.println("PROBE onServicesDiscovered status=" + status);
                            java.util.List<BluetoothGattService> svcs = gatt.getServices();
                            if (svcs == null) return;
                            for (BluetoothGattService s : svcs) {
                                System.out.println("PROBE SERVICE " + s.getUuid());
                                java.util.List<BluetoothGattCharacteristic> chars =
                                    s.getCharacteristics();
                                if (chars == null) continue;
                                for (BluetoothGattCharacteristic c : chars) {
                                    System.out.println("PROBE   CHAR " + c.getUuid()
                                        + " props=0x"
                                        + Integer.toHexString(c.getProperties()));
                                }
                            }
                        }
                    }, BluetoothDevice.TRANSPORT_LE);
                System.out.println("PROBE connectGatt=" + g);
            } else {
                System.out.println("PROBE no target band found");
            }
        } catch (Throwable t) {
            System.out.println("PROBE EXCEPTION:");
            t.printStackTrace(System.out);
        }
        Looper.loop();
    }

    static Context systemContext() throws Exception {
        Class<?> at = Class.forName("android.app.ActivityThread");
        Object thread = at.getMethod("systemMain").invoke(null);
        return (Context) at.getMethod("getSystemContext").invoke(thread);
    }
}
