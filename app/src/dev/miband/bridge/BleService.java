package dev.miband.bridge;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.lang.reflect.Method;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * BLE GATT daemon. Runs as the shell UID via app_process; exposes a line
 * protocol on 127.0.0.1:<port> so Termux can drive the Mi Band.
 *
 * Design:
 *  - one connection manager with auto-reconnect (exponential backoff) and
 *    automatic re-subscription to the RX characteristic after rediscovery;
 *  - any number of TCP clients, each with its own writer; notifications are
 *    broadcast to all of them;
 *  - all GATT state is guarded (chars map, write serialisation with timeout);
 *  - Android 13+ (API 33) write API is used via reflection with a legacy
 *    fallback, so it works on both old and new Bluetooth stacks.
 *
 * Usage: BleDaemon <mac|auto> [port] [--debug]
 */
public class BleService extends Service {
    static final String VERSION = "2.0";
    static final UUID CCCD =
        UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    static final UUID UUID_RX =
        UUID.fromString("0000005e-0000-1000-8000-00805f9b34fb");

    static final int ST_DISCONNECTED = 0, ST_CONNECTING = 1,
                     ST_CONNECTED = 2, ST_READY = 3;
    static final int WRITE_TIMEOUT_MS = 5000;
    static final int MAX_BACKOFF_MS = 30000;

    static int port = 8477;
    static boolean debug = false;

    static Context ctx;
    static BluetoothAdapter adapter;
    static BluetoothDevice device;
    static BluetoothGatt gatt;
    static Handler handler;

    static volatile int connState = ST_DISCONNECTED;
    static volatile int mtu = 0;
    static volatile boolean writeBusy = false;
    static volatile long writeGen = 0;
    static int backoffMs = 2000;
    static int clientSeq = 0;

    static final Map<String, BluetoothGattCharacteristic> chars =
        new LinkedHashMap<>();
    static final Object gattLock = new Object();
    static final Set<String> desiredSubs = new LinkedHashSet<>();
    static final CopyOnWriteArrayList<Client> clients = new CopyOnWriteArrayList<>();

    static volatile Method WRITE3;          // writeCharacteristic(c, byte[], int)
    static volatile boolean write3Checked = false;
    static volatile Method WRITE_DESC2;     // writeDescriptor(desc, byte[])
    static volatile boolean writeDesc2Checked = false;

    // ------------------------------------------------------------- lifecycle
    @Override
    public void onCreate() {
        try {
            ctx = this;
            handler = new Handler(Looper.getMainLooper());
            BluetoothManager bm =
                (BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
            adapter = bm.getAdapter();
            device = resolveTarget(bm,
                getSharedPreferences("bridge", 0).getString("mac", ""));
            startServer();
            connect();
            startForegroundCompat();
        } catch (Throwable t) {
            log("onCreate error: " + t);
        }
    }

    private void startForegroundCompat() {
        Notification n;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel("bridge",
                "MiBand Bridge", NotificationManager.IMPORTANCE_LOW);
            NotificationManager nm = getSystemService(NotificationManager.class);
            nm.createNotificationChannel(ch);
            n = new Notification.Builder(this, "bridge")
                .setSmallIcon(dev.miband.bridge.R.drawable.ic_notify)
                .setContentTitle("MiBand Bridge")
                .setContentText("BLE link active")
                .setOngoing(true)
                .build();
        } else {
            n = new Notification.Builder(this)
                .setSmallIcon(dev.miband.bridge.R.drawable.ic_notify)
                .setContentTitle("MiBand Bridge")
                .setContentText("BLE link active")
                .setOngoing(true)
                .build();
        }
        startForeground(1, n);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null) {
            String mac = intent.getStringExtra("mac");
            if (mac != null) {
                getSharedPreferences("bridge", 0).edit()
                    .putString("mac", mac).apply();
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
        try {
            if (gatt != null) gatt.close();
        } catch (Throwable t) {
            log("onDestroy: " + t);
        }
        super.onDestroy();
    }

    static BluetoothDevice resolveTarget(BluetoothManager bm, String mac) {
        if (mac != null && !mac.isEmpty() && !"auto".equals(mac)) {
            return adapter.getRemoteDevice(mac);
        }
        for (int p : new int[]{BluetoothProfile.GATT, BluetoothProfile.GATT_SERVER}) {
            List<BluetoothDevice> ds = bm.getConnectedDevices(p);
            if (ds == null) continue;
            for (BluetoothDevice d : ds) {
                String n = safeName(d);
                if (n != null && n.toLowerCase(Locale.ROOT).contains("band")) return d;
            }
        }
        Set<BluetoothDevice> bonded = adapter.getBondedDevices();
        if (bonded != null) {
            for (BluetoothDevice d : bonded) {
                String n = safeName(d);
                if (n != null && n.toLowerCase(Locale.ROOT).contains("band")) return d;
            }
        }
        return null;
    }

    static String safeName(BluetoothDevice d) {
        try { return d.getName(); } catch (Throwable t) { return null; }
    }

    static void connect() {
        synchronized (gattLock) {
            if (device == null) return;
            if (gatt != null) {
                try { gatt.close(); } catch (Throwable ignored) {}
                gatt = null;
            }
            setState(ST_CONNECTING);
            try {
                gatt = device.connectGatt(ctx, false, new Callback(),
                                          BluetoothDevice.TRANSPORT_LE);
                log("connectGatt=" + gatt);
            } catch (Throwable t) {
                log("connectGatt failed: " + t);
                scheduleReconnect();
            }
        }
    }

    static void scheduleReconnect() {
        final int delay = backoffMs;
        backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
        log("reconnect in " + delay + "ms");
        if (handler != null) {
            handler.postDelayed(new Runnable() {
                public void run() { connect(); }
            }, delay);
        }
    }

    static void setState(int s) {
        if (connState == s) return;
        connState = s;
        broadcast("EVENT state " + stateName());
    }

    static String stateName() {
        switch (connState) {
            case ST_CONNECTING: return "connecting";
            case ST_CONNECTED:  return "connected";
            case ST_READY:      return "ready";
            default:            return "disconnected";
        }
    }

    // ------------------------------------------------------------ gatt callback
    static class Callback extends BluetoothGattCallback {
        @Override
        public void onConnectionStateChange(BluetoothGatt g, int status, int newState) {
            log("state status=" + status + " new=" + newState);
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                backoffMs = 2000;
                writeBusy = false;
                setState(ST_CONNECTED);
                try { g.discoverServices(); }
                catch (Throwable t) { log("discoverServices: " + t); }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                writeBusy = false;
                setState(ST_DISCONNECTED);
                broadcast("EVENT DISCONNECTED");
                scheduleReconnect();
            }
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt g, int status) {
            synchronized (chars) {
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
            }
            log("services=" + chars.size() + " status=" + status);
            if (status == BluetoothGatt.GATT_SUCCESS) {
                setState(ST_READY);
                broadcast("EVENT READY");
                resubscribeAll();
            } else {
                scheduleReconnect();
            }
        }

        @Override
        public void onCharacteristicRead(BluetoothGatt g, BluetoothGattCharacteristic c,
                                         byte[] value, int status) {
            broadcast("EVENT read " + (value == null ? "" : hex(value)));
        }

        @Override
        public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c,
                                          int status) {
            writeBusy = false;
            writeGen++;
            dbg("onCharacteristicWrite status=" + status);
            broadcast("EVENT write-done " + status);
        }

        @Override
        public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int status) {
            broadcast("EVENT subscribed " + status);
        }

        @Override
        public void onMtuChanged(BluetoothGatt g, int newMtu, int status) {
            mtu = newMtu;
            broadcast("EVENT mtu " + newMtu);
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c,
                                            byte[] value) {
            String s = "NOTIFY " + c.getUuid().toString().toLowerCase(Locale.ROOT)
                     + " " + hex(value);
            dbg("<- " + s);
            for (Client cl : clients) cl.send(s);
        }
    }

    static void resubscribeAll() {
        List<String> subs;
        synchronized (desiredSubs) { subs = new ArrayList<>(desiredSubs); }
        for (String u : subs) {
            BluetoothGattCharacteristic c = findChar(u);
            if (c != null) doSubscribe(c);
        }
    }

    static BluetoothGattCharacteristic findChar(String uuid) {
        synchronized (chars) { return chars.get(uuid.toLowerCase(Locale.ROOT)); }
    }

    static void doSubscribe(final BluetoothGattCharacteristic c) {
        post(new Runnable() {
            public void run() {
                try {
                    gatt.setCharacteristicNotification(c, true);
                    BluetoothGattDescriptor d = c.getDescriptor(CCCD);
                    if (d != null) {
                        writeDescriptorCompat(gatt, d,
                            BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
                    } else {
                        log("no CCCD on " + c.getUuid());
                    }
                } catch (Throwable t) {
                    log("subscribe error: " + t);
                }
            }
        });
    }

    // --------------------------------------------------------------- server
    static void startServer() {
        new Thread(new Runnable() {
            public void run() {
                try {
                    ServerSocket ss = new ServerSocket(port, 8,
                                                       InetAddress.getByName("127.0.0.1"));
                    log("listening on 127.0.0.1:" + port);
                    while (true) {
                        Socket s = ss.accept();
                        Client cl;
                        try {
                            cl = new Client(++clientSeq, s);
                        } catch (Throwable t) {
                            try { s.close(); } catch (Throwable ignored) {}
                            continue;
                        }
                        clients.add(cl);
                        log("client " + cl.id + " connected");
                        cl.send("OK hello " + VERSION + " state=" + stateName());
                        final Client fcl = cl;
                        new Thread(new Runnable() {
                            public void run() { clientLoop(fcl); }
                        }).start();
                    }
                } catch (Throwable t) {
                    log("server error: " + t);
                }
            }
        }).start();
    }

    static void clientLoop(Client cl) {
        try {
            String line;
            while ((line = cl.in.readLine()) != null) {
                dbg("client " + cl.id + " -> " + line);
                if ("quit".equals(line.trim().toLowerCase(Locale.ROOT))) break;
                dispatch(cl, line.trim());
            }
        } catch (Throwable t) {
            dbg("client " + cl.id + " error: " + t);
        } finally {
            clients.remove(cl);
            cl.close();
            log("client " + cl.id + " disconnected");
        }
    }

    static void dispatch(Client cl, String line) {
        if (line.isEmpty()) return;
        String[] p = line.split("\\s+");
        String cmd = p[0].toLowerCase(Locale.ROOT);
        try {
            if ("ping".equals(cmd)) { cl.send("OK pong"); return; }
            if ("version".equals(cmd)) { cl.send("OK version " + VERSION); return; }
            if ("state".equals(cmd)) {
                cl.send("OK state " + stateName() + " mtu=" + mtu);
                return;
            }
            if ("reconnect".equals(cmd)) {
                cl.send("OK reconnect-requested");
                if (gatt != null) {
                    try { gatt.disconnect(); } catch (Throwable ignored) {}
                }
                return;
            }
            if ("services".equals(cmd)) {
                StringBuilder sb = new StringBuilder("OK");
                synchronized (chars) {
                    for (Map.Entry<String, BluetoothGattCharacteristic> e : chars.entrySet()) {
                        sb.append(' ').append(e.getKey()).append(":0x")
                          .append(Integer.toHexString(e.getValue().getProperties()));
                    }
                }
                cl.send(sb.toString());
                return;
            }
            if ("mtu".equals(cmd)) {
                final int n = p.length > 1 ? Integer.parseInt(p[1]) : 512;
                if (!requireReady(cl)) return;
                post(new Runnable() { public void run() { gatt.requestMtu(n); } });
                cl.send("OK mtu-requested");
                return;
            }
            if (p.length < 2) { cl.send("ERR missing characteristic"); return; }
            final BluetoothGattCharacteristic c = findChar(p[1]);
            if (c == null) { cl.send("ERR unknown characteristic"); return; }

            if ("read".equals(cmd)) {
                if (!requireReady(cl)) return;
                post(new Runnable() { public void run() { gatt.readCharacteristic(c); } });
                cl.send("OK read-requested");
            } else if ("write".equals(cmd) || "write-nr".equals(cmd)) {
                if (!requireReady(cl)) return;
                if (p.length < 3) { cl.send("ERR missing value"); return; }
                gattWrite(cl, c, hex2bytes(p[2]), "write-nr".equals(cmd));
            } else if ("subscribe".equals(cmd)) {
                synchronized (desiredSubs) {
                    desiredSubs.add(c.getUuid().toString().toLowerCase(Locale.ROOT));
                }
                doSubscribe(c);
                cl.send("OK subscribe-requested");
            } else if ("unsubscribe".equals(cmd)) {
                synchronized (desiredSubs) {
                    desiredSubs.remove(c.getUuid().toString().toLowerCase(Locale.ROOT));
                }
                post(new Runnable() {
                    public void run() {
                        try { gatt.setCharacteristicNotification(c, false); }
                        catch (Throwable ignored) {}
                    }
                });
                cl.send("OK unsubscribe-requested");
            } else {
                cl.send("ERR unknown command");
            }
        } catch (Throwable t) {
            cl.send("ERR " + t);
        }
    }

    static boolean requireReady(Client cl) {
        if (connState != ST_READY || gatt == null) {
            cl.send("ERR not-ready state=" + stateName());
            return false;
        }
        return true;
    }

    // --------------------------------------------------------------- gatt ops
    static void gattWrite(Client cl, final BluetoothGattCharacteristic c,
                          final byte[] v, final boolean noResponse) {
        synchronized (gattLock) {
            if (writeBusy) { cl.send("ERR busy"); return; }
            writeBusy = true;
        }
        cl.send("OK write-requested");
        post(new Runnable() {
            public void run() {
                boolean supportsNr = (c.getProperties()
                    & BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0;
                int type = (noResponse && supportsNr)
                    ? BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
                    : BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT;
                boolean ok = writeCharacteristicCompat(gatt, c, v, type);
                log("write len=" + v.length + " -> " + ok);
                if (!ok) {
                    synchronized (gattLock) { writeBusy = false; }
                    writeGen++;
                    broadcast("EVENT write-done 1");
                } else {
                    armWriteTimeout();
                }
            }
        });
    }

    static void armWriteTimeout() {
        final long gen = ++writeGen;
        handler.postDelayed(new Runnable() {
            public void run() {
                if (gen == writeGen && writeBusy) {
                    writeBusy = false;
                    log("write timeout");
                    broadcast("EVENT write-done 2");
                }
            }
        }, WRITE_TIMEOUT_MS);
    }

    /**
     * Normalise a GATT op result: the API 33+ overloads return an int
     * BluetoothStatusCodes value (0 = SUCCESS); older ones return boolean.
     */
    static boolean statusOk(Object r) {
        if (r instanceof Boolean) return (Boolean) r;
        if (r instanceof Integer) return ((Integer) r) == 0;
        return false;
    }

    /** API 33+ writeCharacteristic(c, value, type); legacy fallback. */
    static boolean writeCharacteristicCompat(BluetoothGatt g, BluetoothGattCharacteristic c,
                                             byte[] v, int type) {
        if (!write3Checked) {
            write3Checked = true;
            try {
                WRITE3 = BluetoothGatt.class.getMethod("writeCharacteristic",
                    BluetoothGattCharacteristic.class, byte[].class, int.class);
            } catch (NoSuchMethodException e) {
                WRITE3 = null;
            }
        }
        if (WRITE3 != null) {
            try {
                return statusOk(WRITE3.invoke(g, c, v, type));
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

    /** API 33+ writeDescriptor(desc, value); legacy fallback. */
    static boolean writeDescriptorCompat(BluetoothGatt g, BluetoothGattDescriptor d,
                                         byte[] v) {
        if (!writeDesc2Checked) {
            writeDesc2Checked = true;
            try {
                WRITE_DESC2 = BluetoothGatt.class.getMethod("writeDescriptor",
                    BluetoothGattDescriptor.class, byte[].class);
            } catch (NoSuchMethodException e) {
                WRITE_DESC2 = null;
            }
        }
        if (WRITE_DESC2 != null) {
            try {
                return statusOk(WRITE_DESC2.invoke(g, d, v));
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

    // --------------------------------------------------------------- client
    static class Client {
        final int id;
        final Socket sock;
        final BufferedReader in;
        final PrintWriter out;

        Client(int id, Socket sock) throws Exception {
            this.id = id;
            this.sock = sock;
            this.in = new BufferedReader(
                new InputStreamReader(sock.getInputStream(), "UTF-8"));
            this.out = new PrintWriter(
                new OutputStreamWriter(sock.getOutputStream(), "UTF-8"), true);
        }

        void send(String s) {
            synchronized (this) {
                try {
                    out.println(s);
                    if (out.checkError()) {
                        log("client " + id + " write error");
                        close();
                    }
                } catch (Throwable t) {
                    close();
                }
            }
        }

        void close() {
            synchronized (this) {
                try { sock.close(); } catch (Throwable ignored) {}
            }
        }
    }

    static void broadcast(String s) {
        dbg("-> " + s);
        for (Client c : clients) c.send(s);
    }

    static void post(final Runnable r) {
        handler.post(new Runnable() {
            public void run() {
                try {
                    r.run();
                } catch (Throwable t) {
                    log("op error: " + t);
                    t.printStackTrace(System.out);
                    System.out.flush();
                }
            }
        });
    }

    static String hex(byte[] b) {
        if (b == null) return "";
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    static byte[] hex2bytes(String s) {
        int n = s.length() / 2;
        byte[] b = new byte[n];
        for (int i = 0; i < n; i++) {
            b[i] = (byte) Integer.parseInt(s.substring(2 * i, 2 * i + 2), 16);
        }
        return b;
    }

    static final SimpleDateFormat TS = new SimpleDateFormat("HH:mm:ss.SSS", Locale.US);

    static void log(String s) {
        String t;
        synchronized (TS) { t = TS.format(new Date()); }
        System.out.println(t + " " + s);
        System.out.flush();
        Log.i("BleService", s);
    }

    static void dbg(String s) {
        if (debug) log(s);
    }
}
