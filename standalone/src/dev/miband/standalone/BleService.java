package dev.miband.standalone;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

import dev.miband.standalone.proto.Commands;
import dev.miband.standalone.proto.Constants;
import dev.miband.standalone.proto.XiaoSession;

/**
 * Foreground service owning the BLE link + full Xiaomi auth handshake +
 * periodic battery polling. Fully self-contained: no Termux/mibandd
 * dependency at runtime.
 *
 * Keep-alive design (see README "why this app doesn't die"):
 *  - startForeground() fires immediately in onCreate, before BLE connect;
 *  - onStartCommand returns START_STICKY so Android restarts a killed service;
 *  - a partial WakeLock is taken only around each BLE operation (short,
 *    auto-release timeout), never held continuously;
 *  - BleWatchdog (JobScheduler, persisted) periodically re-starts this
 *    service as a second line of defense if the OS kills it outright.
 */
public class BleService extends Service {
    static final UUID CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    static final UUID UUID_TX = UUID.fromString(Constants.UUID_TX);
    static final UUID UUID_RX = UUID.fromString(Constants.UUID_RX);

    static final int ST_DISCONNECTED = 0, ST_CONNECTING = 1, ST_CONNECTED = 2, ST_READY = 3, ST_AUTHENTICATING = 4;
    static final int MAX_BACKOFF_MS = 30000;
    static final long BATTERY_POLL_MS = 10 * 60 * 1000; // 10 min
    static final long WAKELOCK_MS = 10_000;

    private static volatile BleService instance;

    private Context ctx;
    private Handler handler;
    private PowerManager.WakeLock wakeLock;
    private BluetoothAdapter adapter;
    private BluetoothDevice device;
    private BluetoothGatt gatt;
    private XiaoSession session;

    private volatile int connState = ST_DISCONNECTED;
    private int backoffMs = 2000;
    private final Map<String, BluetoothGattCharacteristic> chars = new LinkedHashMap<>();
    private volatile Method write3;
    private boolean write3Checked = false;
    private volatile Method writeDesc2;
    private boolean writeDesc2Checked = false;

    private final Runnable batteryPoll = new Runnable() {
        @Override public void run() {
            pollBattery();
            handler.postDelayed(this, BATTERY_POLL_MS);
        }
    };

    static String stateName(int s) {
        switch (s) {
            case ST_CONNECTING: return "connecting";
            case ST_CONNECTED: return "connected";
            case ST_AUTHENTICATING: return "authenticating";
            case ST_READY: return "ready";
            default: return "disconnected";
        }
    }

    static int currentState() {
        BleService s = instance;
        return s == null ? ST_DISCONNECTED : s.connState;
    }

    /** Called by NotifyListenerService when a phone notification should be forwarded. */
    static void forwardNotification(String pkg, String app, String title, String text) {
        BleService s = instance;
        if (s == null || s.session == null || !s.session.isReady()) return;
        byte[] body = Commands.buildNotification((int) (System.currentTimeMillis() % 100000), pkg, app, title, text);
        s.sendCommand(Commands.TYPE_NOTIFICATION, Commands.SUB_NOTIFY, body);
    }

    @Override
    public void onCreate() {
        ctx = this;
        handler = new Handler(Looper.getMainLooper());
        PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "miband:ble-io");
        wakeLock.setReferenceCounted(false);

        // Foreground status first, before anything that could fail or block.
        startForegroundCompat();
        instance = this;

        BluetoothManager bm = (BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
        adapter = bm.getAdapter();

        String mac = prefs().getString("mac", "");
        if (adapter != null && !mac.isEmpty()) {
            try {
                device = adapter.getRemoteDevice(mac);
                connect();
            } catch (Throwable t) {
                log("bad mac: " + t);
            }
        } else {
            log("no band MAC configured yet");
        }

        BleWatchdog.schedule(this);
    }

    private SharedPreferences prefs() {
        return getSharedPreferences("standalone", 0);
    }

    private void startForegroundCompat() {
        Notification n;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel("ble", "MiBand link",
                    NotificationManager.IMPORTANCE_LOW);
            NotificationManager nm = getSystemService(NotificationManager.class);
            nm.createNotificationChannel(ch);
            n = new Notification.Builder(this, "ble")
                    .setSmallIcon(R.drawable.ic_notify)
                    .setContentTitle("MiBand Standalone")
                    .setContentText("starting…")
                    .setOngoing(true)
                    .build();
        } else {
            n = new Notification.Builder(this)
                    .setSmallIcon(R.drawable.ic_notify)
                    .setContentTitle("MiBand Standalone")
                    .setContentText("starting…")
                    .setOngoing(true)
                    .build();
        }
        startForeground(1, n);
    }

    private void updateNotification(String text) {
        if (Build.VERSION.SDK_INT < 26) return;
        Notification n = new Notification.Builder(this, "ble")
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle("MiBand Standalone")
                .setContentText(text)
                .setOngoing(true)
                .build();
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.notify(1, n);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null) {
            String mac = intent.getStringExtra("mac");
            if (mac != null && !mac.isEmpty()) {
                prefs().edit().putString("mac", mac).apply();
                if (adapter != null) {
                    try {
                        device = adapter.getRemoteDevice(mac);
                        connect();
                    } catch (Throwable t) {
                        log("bad mac: " + t);
                    }
                }
            }
        }
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent i) {
        return null;
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacks(batteryPoll);
        try {
            if (gatt != null) gatt.close();
        } catch (Throwable ignored) {}
        instance = null;
        super.onDestroy();
    }

    private void withWakeLock(Runnable r) {
        try {
            wakeLock.acquire(WAKELOCK_MS);
            r.run();
        } finally {
            if (wakeLock.isHeld()) wakeLock.release();
        }
    }

    private void connect() {
        if (device == null) return;
        withWakeLock(new Runnable() {
            @Override public void run() {
                if (gatt != null) {
                    try { gatt.close(); } catch (Throwable ignored) {}
                    gatt = null;
                }
                setState(ST_CONNECTING);
                try {
                    gatt = device.connectGatt(ctx, false, new Callback(), BluetoothDevice.TRANSPORT_LE);
                } catch (Throwable t) {
                    log("connectGatt failed: " + t);
                    scheduleReconnect();
                }
            }
        });
    }

    private void scheduleReconnect() {
        int delay = backoffMs;
        backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
        handler.postDelayed(new Runnable() {
            @Override public void run() { connect(); }
        }, delay);
    }

    private void setState(int s) {
        connState = s;
        updateNotification(stateName(s));
    }

    private String authKeyHex() {
        return prefs().getString("authkey", "");
    }

    private void startAuth() {
        String hex = authKeyHex();
        if (hex.isEmpty()) {
            log("no auth key configured; cannot authenticate");
            return;
        }
        byte[] secret = hexToBytes(hex);
        session = new XiaoSession(secret);
        setState(ST_AUTHENTICATING);
        session.startAuth(transport, true, sessionListener);
    }

    private final XiaoSession.Transport transport = new XiaoSession.Transport() {
        @Override public void writeToBand(byte[] data) { writeReliable(data); }
    };

    private final XiaoSession.Listener sessionListener = new XiaoSession.Listener() {
        @Override public void onAuthResult(boolean success, String reason) {
            if (success) {
                setState(ST_READY);
                backoffMs = 2000;
                handler.removeCallbacks(batteryPoll);
                handler.post(batteryPoll);
            } else {
                log("auth failed: " + reason);
            }
        }
        @Override public void onResponse(int type, int subtype, byte[] body) {
            Commands.Battery b = Commands.parseBattery(type, subtype, body);
            if (b != null) {
                DataLogger.append("battery", b.level + "\t" + b.state);
                updateNotification("ready, battery=" + b.level + "%");
            }
        }
        @Override public void onLog(String msg) { log(msg); }
    };

    private void pollBattery() {
        if (session == null || !session.isReady()) return;
        sendCommand(Commands.TYPE_DEVICE, Commands.SUB_BATTERY, new byte[0]);
    }

    private void sendCommand(int ctype, int csub, byte[] body) {
        if (session == null || !session.isReady()) return;
        byte[] pkt = session.buildCommand(ctype, csub, body);
        writeReliable(pkt);
    }

    private void writeReliable(final byte[] data) {
        final BluetoothGattCharacteristic c = chars.get(Constants.UUID_TX);
        if (c == null || gatt == null) return;
        withWakeLock(new Runnable() {
            @Override public void run() {
                writeCharacteristicCompat(gatt, c, data, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
            }
        });
    }

    // ------------------------------------------------------------ gatt callback
    private class Callback extends BluetoothGattCallback {
        @Override
        public void onConnectionStateChange(BluetoothGatt g, int status, int newState) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                setState(ST_CONNECTED);
                try { g.discoverServices(); } catch (Throwable ignored) {}
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                setState(ST_DISCONNECTED);
                session = null;
                scheduleReconnect();
            }
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt g, int status) {
            chars.clear();
            List<BluetoothGattService> svcs = g.getServices();
            if (svcs != null) {
                for (BluetoothGattService s : svcs) {
                    List<BluetoothGattCharacteristic> cs = s.getCharacteristics();
                    if (cs == null) continue;
                    for (BluetoothGattCharacteristic c : cs) {
                        chars.put(c.getUuid().toString().toLowerCase(Locale.ROOT), c);
                    }
                }
            }
            if (status == BluetoothGatt.GATT_SUCCESS) {
                final BluetoothGattCharacteristic rx = chars.get(Constants.UUID_RX);
                if (rx != null) {
                    withWakeLock(new Runnable() {
                        @Override public void run() { doSubscribe(rx); }
                    });
                }
                startAuth();
            } else {
                scheduleReconnect();
            }
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value) {
            if (session == null) return;
            session.onNotify(value, transport, sessionListener);
        }
    }

    private void doSubscribe(BluetoothGattCharacteristic c) {
        try {
            gatt.setCharacteristicNotification(c, true);
            BluetoothGattDescriptor d = c.getDescriptor(CCCD);
            if (d != null) {
                writeDescriptorCompat(gatt, d, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
            }
        } catch (Throwable t) {
            log("subscribe error: " + t);
        }
    }

    // -- compat GATT write helpers (API 33+ overloads via reflection, legacy fallback) --
    private static boolean statusOk(Object r) {
        if (r instanceof Boolean) return (Boolean) r;
        if (r instanceof Integer) return ((Integer) r) == 0;
        return false;
    }

    private boolean writeCharacteristicCompat(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] v, int type) {
        if (!write3Checked) {
            write3Checked = true;
            try {
                write3 = BluetoothGatt.class.getMethod("writeCharacteristic",
                        BluetoothGattCharacteristic.class, byte[].class, int.class);
            } catch (NoSuchMethodException e) {
                write3 = null;
            }
        }
        if (write3 != null) {
            try {
                return statusOk(write3.invoke(g, c, v, type));
            } catch (Throwable t) {
                log("write3 failed: " + t);
            }
        }
        try {
            c.setWriteType(type);
            c.setValue(v);
            return g.writeCharacteristic(c);
        } catch (Throwable t) {
            log("legacy write failed: " + t);
            return false;
        }
    }

    private boolean writeDescriptorCompat(BluetoothGatt g, BluetoothGattDescriptor d, byte[] v) {
        if (!writeDesc2Checked) {
            writeDesc2Checked = true;
            try {
                writeDesc2 = BluetoothGatt.class.getMethod("writeDescriptor",
                        BluetoothGattDescriptor.class, byte[].class);
            } catch (NoSuchMethodException e) {
                writeDesc2 = null;
            }
        }
        if (writeDesc2 != null) {
            try {
                return statusOk(writeDesc2.invoke(g, d, v));
            } catch (Throwable t) {
                log("writeDesc2 failed: " + t);
            }
        }
        try {
            d.setValue(v);
            return g.writeDescriptor(d);
        } catch (Throwable t) {
            log("legacy descriptor failed: " + t);
            return false;
        }
    }

    private static byte[] hexToBytes(String s) {
        s = s.trim();
        if (s.startsWith("0x") || s.startsWith("0X")) s = s.substring(2);
        int n = s.length() / 2;
        byte[] b = new byte[n];
        for (int i = 0; i < n; i++) b[i] = (byte) Integer.parseInt(s.substring(2 * i, 2 * i + 2), 16);
        return b;
    }

    private static void log(String s) {
        android.util.Log.i("BleService", s);
    }
}
