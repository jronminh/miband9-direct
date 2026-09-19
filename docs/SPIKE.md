# Spike — prove shell-UID `app_process` can do BLE

Purpose: answer one question before any real building.

> Can a process started with `app_process` under the `shell` UID get a
> `BluetoothAdapter`, list bonded devices, and open a GATT connection to the
> Mi Band 9 Active?

If yes, the whole `miband9-direct` design is viable. If no, we fall back.

## Steps

### 1. Write minimal Android stubs (compile-time only)

Only the classes/methods the probe touches. Empty bodies; never shipped in the
runtime dex.

```
stubs/src/android/content/Context.java          // getSystemService, BLUETOOTH_SERVICE
stubs/src/android/os/Looper.java                // getMainLooper, loop
stubs/src/android/bluetooth/BluetoothManager.java
stubs/src/android/bluetooth/BluetoothAdapter.java
stubs/src/android/bluetooth/BluetoothDevice.java // connectGatt, TRANSPORT_LE
stubs/src/android/bluetooth/BluetoothGatt.java
stubs/src/android/bluetooth/BluetoothGattCallback.java
stubs/src/android/bluetooth/BluetoothProfile.java
```

Compile them to `stubs/build`, then jar to `stubs/stub.jar`.

**Critical:** the stubs are *only* a compile-time classpath. They are **not**
included in the dex we push. At runtime ART loads the real `android.*` classes
from the boot classpath. (Boot classpath wins, but we exclude stubs anyway.)

### 2. The probe

`spike/src/BleProbe.java`:

```java
import android.bluetooth.*;
import android.content.Context;
import android.os.Looper;
import java.util.Set;

public class BleProbe {
    public static void main(String[] args) throws Exception {
        // systemMain() prepares the main looper and gives a system Context.
        Context ctx = systemContext();
        System.out.println("context=" + ctx);

        BluetoothManager bm =
            (BluetoothManager) ctx.getSystemService(Context.BLUETOOTH_SERVICE);
        BluetoothAdapter a = bm.getAdapter();
        System.out.println("adapter=" + a + " enabled=" + a.isEnabled());

        Set<BluetoothDevice> bonded = a.getBondedDevices();
        for (BluetoothDevice d : bonded)
            System.out.println("bonded " + d.getAddress() + " " + d.getName());

        if (args.length > 0) {
            BluetoothDevice dev = a.getRemoteDevice(args[0]);
            BluetoothGatt g = dev.connectGatt(ctx, false,
                new BluetoothGattCallback() {
                    @Override
                    public void onConnectionStateChange(
                            BluetoothGatt gatt, int status, int newState) {
                        System.out.println("state status=" + status
                            + " new=" + newState);
                        if (newState == BluetoothProfile.STATE_CONNECTED)
                            System.out.println("GATT_CONNECTED");
                    }
                }, BluetoothDevice.TRANSPORT_LE);
            System.out.println("connectGatt -> " + g);
        }
        Looper.loop(); // keep callbacks alive
    }

    static Context systemContext() throws Exception {
        Class<?> at = Class.forName("android.app.ActivityThread");
        Object thread = at.getMethod("systemMain").invoke(null);
        return (Context) at.getMethod("getSystemContext").invoke(thread);
    }
}
```

Note: do **not** call `Looper.prepareMainLooper()` — `systemMain()` already does.

### 3. Compile

```sh
# stubs -> stub.jar
javac -d stubs/build $(find stubs/src -name '*.java')
(cd stubs/build && jar cf ../stub.jar .)

# probe against stubs -> class files
javac -cp stubs/stub.jar -d spike/build spike/src/BleProbe.java

# class files -> dex (ONLY our class, not the stubs)
d8 --min-api 23 --output spike/build/dex spike/build/BleProbe.class
# -> spike/build/dex/classes.dex
```

### 4. Push and run (via dsh)

```sh
dsh -p spike/build/dex/classes.dex \
    'cat > /data/local/tmp/bleprobe.jar'

dsh -c 'ANDROID_DATA=/data/local/tmp ANDROID_ROOT=/system \
        CLASSPATH=/data/local/tmp/bleprobe.jar \
        app_process /system/bin --nice-name=bleprobe BleProbe'
```

Optionally pass the band MAC as the last arg to test `connectGatt`.
(`ANDROID_DATA=/data/local/tmp` gives a writable dalvik-cache; the earlier
`app_process` run complained about `/data/dalvik-cache` ownership.)

## Success criteria

- `adapter=... enabled=true`
- `bonded ... Xiaomi Band 9 Activ`
- with a MAC: `connectGatt -> ...` then `GATT_CONNECTED`

Any of these missing → read the failure mode below.

## RESULT: PASSED ✅ (2026-09-18)

Shell-UID `app_process` opened a real GATT connection to the band:

```
PROBE connected profile=7  XX:XX:XX:XX:XX:XX Xiaomi Band 9 Activ   (MAC redacted)
PROBE connectGatt=android.bluetooth.BluetoothGatt@fe5b386
PROBE state status=0 new=2
PROBE GATT_CONNECTED
```

The key was the process bootstrap that `systemMain()` skips:

```
Environment.initForCurrentUser()
ActivityThread.initializeMainlineModules()   // sets BluetoothServiceManager
Looper.prepareMainLooper()
ActivityThread.systemMain().getSystemContext()
context.getSystemService(BLUETOOTH_SERVICE)
```

The band is LE-only and is **not** in `getBondedDevices()`; it is found via
`BluetoothManager.getConnectedDevices(BluetoothProfile.GATT=7)`. Full details in
`notes/FINDINGS.md`. Proceed to Phase 1.

## Failure modes and what they mean

| Symptom | Meaning | Next move |
|---|---|---|
| `ClassNotFoundException: android.app.ActivityThread` | bootstrap/reflection issue | adjust bootstrap; try `ActivityThread.currentActivityThread()` |
| `getSystemContext()` returns null / `bm.getAdapter()` null | app_process can't reach the BT service | likely dead end for this route |
| `SecurityException ... BLUETOOTH_CONNECT` | permission not effective for this process | try `--nice-name=com.android.shell`; or give up |
| `avc: denied` (check `logcat`/`dmesg` via dsh) | SELinux blocks the binder call | dead end without root |
| `connectGatt -> null` | adapter rejects the call | check Mi Fitness isn't holding the link |
| `connectGatt` non-null but no callback | BLE connect silently blocked | retry with Mi Fitness stopped; check logcat |
| `Error changing dalvik-cache ownership` | cache path not writable | already addressed via `ANDROID_DATA` |
| dex load error | bad d8 output / classpath | verify jar layout, `--min-api` |

## Cost / risk

- Effort: ~1 hour of iteration; all local, reversible.
- Risk: the BLE-from-`app_process` step is genuinely unproven on Android 16.
  The spike exists to fail fast if it's blocked.

## Decision after the spike

- **Pass** → proceed to Phase 1 (transport daemon) in `docs/PLAN.md`.
- **Fail** → fall back to a tiny bridge app, or keep the Gadgetbridge-based
  `../miband9-termux` (which already works).
