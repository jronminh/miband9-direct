# Companion app — headless BLE bridge

How `miband9-direct` gets a **stable** BLE link without the shell-UID daemon:
a tiny headless Android app owns the radio, Termux keeps the intelligence.
Build + source live in [`app/`](../app); the design rationale is in
[`PLAN.md`](PLAN.md) Phase 5.

## Why

The original route (`daemon/BleDaemon.java` run as the `shell` UID via
`app_process` over `dsh`) works, but is unstable by construction:

- it needs a live ADB / Wireless Debugging link — the `dsh` daemon dies on its
  own, and then BLE is gone;
- it does not survive a reboot (re-run `install.sh --no-build`);
- it fights Mi Fitness for the band's single login.

A normal app process owns the radio with ordinary permissions and a foreground
service, so it survives reboots and needs **no ADB at all** after install —
while staying Termux-compatible.

## What it is

- **Headless**: no launcher activity, no UI, no custom screens. It never appears
  in the app drawer.
- **Same transport**: `BleDaemon.java` moved into a `Service`
  (`BleService.java`) with the GATT callbacks, write serialisation and the
  `127.0.0.1:8477` line protocol byte-for-byte unchanged.
- **Same interface**: `client/` and `mibandd` talk to `127.0.0.1:8477` exactly
  as before — nothing on the Python side changed.

```
Termux (logic)                     companion app (radio)
mibandd / client  ── 127.0.0.1:8477 ──►  BleService (foreground service)
                                              └── BluetoothGatt ──► Mi Band 9
```

## Files

| Path | Role |
|---|---|
| `app/AndroidManifest.xml` | permissions, `<service>`, boot receiver, no `LAUNCHER` |
| `app/src/dev/miband/bridge/BleService.java` | the transport (from `BleDaemon.java`) |
| `app/src/dev/miband/bridge/PermitActivity.java` | exported, UI-less entry point |
| `app/src/dev/miband/bridge/BootReceiver.java` | auto-start on `BOOT_COMPLETED` |
| `app/res/…` | app name + notification icon |
| `app/build.sh` | one-shot build + sign |

Package `dev.miband.bridge`, `minSdk 26`, `targetSdk 30`.

## Build (no gradle, no Android SDK)

```sh
bash app/build.sh        # -> app/mibandbridge.apk (signed)
```

The script uses only Termux tools: `aapt2` (compile + link), `javac` against a
real platform jar, `d8` (dex), `zipalign`, `apksigner`. The platform jar is the
one vendored by the ADB bridge:
`$HOME/termux-adb-bridge/build/adbwifi-helper/android.jar` (override with
`$ANDROID_JAR`).

## Install + run

Installing needs shell (`dsh` is the only remaining ADB dependency, and only for
the one-time install + permission grant):

```sh
dsh -p app/mibandbridge.apk 'cat > /data/local/tmp/bridge.apk'
dsh 'pm install -r /data/local/tmp/bridge.apk'
dsh 'pm grant dev.miband.bridge android.permission.BLUETOOTH_CONNECT'
dsh 'pm grant dev.miband.bridge android.permission.BLUETOOTH_SCAN'
```

Then Termux is the launcher — pass the band MAC once, it is persisted:

```sh
am start -n dev.miband.bridge/.PermitActivity --es mac <BAND_MAC>
```

Use `am` (the classic `termux-am` 0.8.0 wrapper at `$PREFIX/bin/am`), **not**
`termux-am`.

`termux-am` is only a forwarder to `termux-am-socket`, which connects to a UNIX
socket that termux-app itself must be serving (`…/termux-am/am.sock`). On this
device that server never starts, and the reason is in the app, not the config:
in termux-app **v0.119.0-beta.3** the startup call is **commented out** in
`TermuxApplication.onCreate()`:

```java
Logger.logInfo(LOG_TAG, "Termux files directory is accessible");
/*
error = TermuxFileUtils.isAppsTermuxAppDirectoryAccessible(true, true);
...
TermuxAmSocketServer.setupTermuxAmSocketServer(context);
 */
```

So no property, permission, or directory change can enable it — verified with
verbose logging on: `run-termux-am-socket-server` reads `true`, but no
`TermuxAmSocketServer` log line is ever emitted.

Updating Termux does not help either: the latest official release is
**v0.119.0-beta.3** (the version already installed), there is no nightly, and
its GitHub APKs are signed with a *different* key than the F-Droid build, so
installing one forces an uninstall and **wipes `~` and `$PREFIX`**. Only a
build from current master (where the block is uncommented) would enable it, and
no such official APK exists. The classic `am` runs
`com.termux.termuxam.Am` through `app_process` as the Termux UID and needs no
socket; verified working. (Caveat: it is subject to background-activity-start
rules, so launch while Termux is in the foreground. After the first launch the
`BootReceiver` handles restarts, so this is a one-time step.)

`PermitActivity` stores the MAC, starts the foreground service and finishes.
After that the `BootReceiver` re-starts the service on every boot, and the
Python client just connects to `127.0.0.1:8477`.

## Permissions model

`targetSdk 30` was chosen hoping the legacy `BLUETOOTH` / `BLUETOOTH_ADMIN`
permissions (install-time, auto-granted) would cover the modern stack. **On
Android 16 that does not hold** — `connectGatt` throws
`SecurityException: Need android.permission.BLUETOOTH_CONNECT`, so the two
runtime permissions must be granted once after install (`pm grant`, above).
`INTERNET` is also required: without it, binding the loopback TCP socket fails
with `EPERM`. The app still has no UI and shows no dialog; the grants are a
one-time `dsh` setup step, not a runtime interaction.

## Accepted costs

1. **Persistent notification** — a foreground service must post one (silent,
   low-priority, minimizable). Truly invisible is not possible on modern Android.
2. **Samsung battery management** — on this device the app must be exempted from
   battery optimisation (or at least allowed to auto-start), or the service gets
   frozen.

## Relation to `dsh`

`dsh` is still used for the one-time `pm install` and for anything else that
needs the `shell` UID. It is no longer on the BLE path, so a dead ADB bridge no
longer means a dead band link.

## Status

Built, signed, installed and **verified end-to-end** on this device: the service
reports `state=ready` on `127.0.0.1:8477`, and `mibandd device battery` returned
live data (`{"level": 61, "state": 2}`) with the shell-UID BLE daemon stopped.
**Reboot-survival confirmed**: after a device reboot the service is back at
`state=ready` and `mibandd device battery` works with `dsh` down — the app does
not depend on the ADB bridge.

## Future (parked): patch termux-app

If `termux-am` is ever wanted, the only route is a **patched termux-app**: build
from master with the `setupTermuxAmSocketServer` block uncommented (or apply
that one-line change to the release branch) and self-sign it. That needs a full
Android toolchain (gradle + Android SDK + NDK) — it is **not** buildable with
the `aapt2`/`d8`/`apksigner` setup used for `app/`.

Because the signature differs from the installed F-Droid build, it forces an
**uninstall**, which wipes `~` and `$PREFIX`. So the patch must ship with a
backup → uninstall → install → restore procedure. Not started; parked as a plan.
Meanwhile `am start` covers the one thing we need.
