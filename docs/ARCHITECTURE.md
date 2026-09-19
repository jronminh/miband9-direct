# Architecture — direct BLE from Termux

## Constraint

Android grants access to the Bluetooth stack only to app UIDs with the
Bluetooth permissions, through the framework (`BluetoothGatt`). Termux is
`untrusted_app` and has none of that. The `shell` UID (uid=2000) *does* have
`BLUETOOTH_CONNECT`/`BLUETOOTH_SCAN`/`BLUETOOTH_PRIVILEGED` granted, and
`app_process` lets us run our own dex in that UID.

So the design is: **run the BLE code as the shell UID, keep the intelligence in
Termux.**

## Components

```
┌─────────────────────────────────────────────┐
│ Termux (uid 10663)                           │
│  • Python: Xiaomi protobuf + auth protocol   │
│  • mibandctl: user commands                  │
│  • TCP client → 127.0.0.1:PORT               │
└───────────────┬─────────────────────────────┘
                │ localhost TCP (no permission issues)
┌───────────────▼─────────────────────────────┐
│ BLE daemon (app_process, uid 2000 shell)     │
│  • BluetoothAdapter / BluetoothGatt          │
│  • line protocol (multi-client, broadcast)   │
│  • auto-reconnect + re-subscribe             │
│  • compiled: stubs → javac → d8 → classes.dex│
└───────────────┬─────────────────────────────┘
                │ Android BluetoothGatt
┌───────────────▼─────────────────────────────┐
│ Mi Band 9 Active (BLE, Xiaomi protobuf)      │
└─────────────────────────────────────────────┘
```

Launched from Termux over ADB (`adbwire`, Wireless Debugging); the daemon
detaches (`setsid`) and listens on
`127.0.0.1`. Termux connects and speaks a small line protocol.

A third tier — **`mibandd`**, a long-lived Termux-side process that owns the
authenticated session, SQLite and the scheduler so clients do not re-auth per
call — is planned in [`DAEMON.md`](DAEMON.md).

## Daemon line protocol

Each TCP client sends newline commands; the daemon replies `OK ...` / `ERR ...`
and pushes async `EVENT ...` / `NOTIFY <uuid> <hex>` lines to **every** client.

| Command | Effect |
|---|---|
| `ping` / `version` | liveness / daemon version |
| `state` | `OK state <disconnected\|connecting\|connected\|ready> mtu=<n>` |
| `services` | list discovered characteristic UUIDs + properties |
| `mtu <n>` | request MTU |
| `read <uuid>` | read a characteristic |
| `write <uuid> <hex>` / `write-nr ...` | write (with / without response) |
| `subscribe <uuid>` / `unsubscribe <uuid>` | enable/disable notifications |
| `reconnect` | force a disconnect; the manager reconnects with backoff |
| `quit` | close this client |

The connection manager reconnects on its own with exponential backoff
(2 s → 30 s), rediscovers services, and re-subscribes to previously requested
characteristics — so a band reboot no longer requires restarting the daemon.
Writes are serialised (one outstanding GATT op, 5 s timeout) and use the
Android 13+ `writeCharacteristic(c, value, type)` API via reflection, falling
back to the legacy `setWriteType` path on older stacks.

## Compile strategy (no Android SDK on device)

There is no `android.jar` on the device and no dex→jar tool in Termux.

Approach:
1. Write minimal **stub** Java sources for only the classes/methods used
   (`Context`, `BluetoothManager`, `BluetoothAdapter`, `BluetoothDevice`,
   `BluetoothGatt`, `BluetoothGattCallback`, `BluetoothGattCharacteristic`,
   `Looper`, ...). Bodies empty.
2. `javac` stubs → `stub.jar`.
3. `javac -cp stub.jar` the daemon.
4. `d8` → `classes.dex`.
5. `adbwire -p` push to `/data/local/tmp`, run
   `app_process -Djava.class.path=... /data/local/tmp <Main>`.

Bootstrapping a usable `Context` in `app_process` is done reflectively
(`ActivityThread.systemMain().getSystemContext()`), so the stub surface stays
small. Hidden-API restrictions do not apply to `app_process`.

Unknowns to prove in the spike:
- Does SELinux (`u:r:shell:s0`) allow the Bluetooth Binder calls from a
  non-app process? (Shell is normally allowed.)
- Does `getSystemContext()` yield a working `BluetoothManager`?
- Does `connectGatt` actually work from this context on Android 16?

## Protocol (the long pole)

Reimplement, in Python, from Gadgetbridge (AGPLv3):

1. **Service/characteristic UUIDs** for Xiaomi protobuf devices.
2. **Auth handshake** using the extracted 32-hex key.
3. **Message framing** (protobuf over the Xiaomi BLE characteristics).
4. **Command set** for what you actually want (notify, find, sync, settings).

Reuse Gadgetbridge's `.proto` files to generate Python classes (`protobuf` /
`betterproto`). Port the auth algorithm by reading
`app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/xiaomi/...`.

## Why not alternatives

| Option | Why not |
|---|---|
| Pure Termux (bluez / bleak) | No HCI device, no D-Bus BlueZ; OS wall |
| Root + raw HCI | Device not rooted |
| USB BT dongle via `termux-usb` | BlueZ needs kernel `btusb`, can't load modules; Termux can't drive it |
| Termux:API BLE fork | Requires building + installing a modified APK (an app); same protocol effort |
| Tiny custom bridge app | An app; but valid fallback if the spike fails |
| Gadgetbridge | Works today, but that's the dependency being rejected here |

## Security notes

- The daemon runs as `shell`; it is a BLE transport only — no file access
  beyond its own dex, no network beyond localhost.
- The auth key is read from Mi Fitness logs; keep it out of the repo.
- Binding the daemon to `127.0.0.1` only; no external listeners.
