# standalone — a fully self-contained Mi Band 9 companion app

Unlike [`app/`](../app) (a headless BLE-to-TCP bridge that still needs
Termux/`mibandd` to speak the Xiaomi protocol), this is a normal, standalone
personal app: it owns the BLE connection, runs the full Xiaomi auth
handshake, forwards phone notifications to the band, and logs band data to
disk — all on-device, with **no Termux dependency at runtime**. It has a
launcher icon and one plain settings/status screen.

Package: `dev.miband.standalone`. minSdk 26, targetSdk 33.

## What it does

1. **BLE + auth**: connects to the band's GATT service (`fe95`), runs the
   SPP v2 session handshake and the Xiaomi encrypted auth exchange, exactly
   like `client/protocol/handshake.py` — ported to Java in
   [`src/dev/miband/standalone/proto/`](src/dev/miband/standalone/proto/).
2. **Notification forwarding (phone → band)**: a `NotificationListenerService`
   catches Android notifications and sends them to the band as a `Command{7,0}`
   notify packet (title/text/app), after you grant notification access once.
3. **Data logging**: every 10 minutes, polls battery (`Command{2,1}`) and
   appends one line to `/sdcard/MiBandLogs/YYYY-MM-DD.txt`:
   ```
   2026-09-24T14:32:01	battery	61	2
   ```
   (timestamp, metric, level, charging-state). Deliberately raw/greppable,
   no schema — this is prep data for a feature to be designed later.

## What's stubbed / not implemented

- **Steps and heart-rate logging**: not implemented. Unlike battery, these
  aren't simple query/reply commands in this protocol — they come through the
  `activity-files` sync flow (`Command{8,1..5}`, file-transfer style, see
  `docs/COMMANDS.md`), which is substantially more protocol work than a
  single read. Battery-only logging ships now; steps/HR are a follow-up.
- **Notification dismiss / call-forwarding**: `Commands.buildDismiss()` exists
  (ported) but nothing calls it yet — only the plain `notify` path is wired
  into `NotifyListenerService`.
- **Notification filtering**: only skips the app's own notifications and
  ongoing/foreground-service ones. No allow/deny list, no rate limiting
  (mirrors what `docs/USAGE.md` calls "future work" for the existing
  `forward` feature).
- **Verification against a real band**: this environment has no BLE hardware
  and no device to `adb`/`dsh` install onto, so **nothing here has been
  exercised against an actual Mi Band 9**. What *is* verified:
  - the app compiles and produces a signed, `apksigner`-verified APK;
  - the crypto core (`HMAC-SHA256`, `AES-CTR`, and a hand-rolled `AES-CCM`)
    was checked byte-for-byte against this repo's Python implementation
    (`client/protocol/crypto.py`) using known input/output vectors — see
    [`test/CryptoTest.java`](test/CryptoTest.java), run with `javac
    CryptoTest.java && java CryptoTest`;
  - the protobuf/varint/CRC16 encode paths were spot-checked against the
    Python encoder's output the same way.

  The GATT plumbing itself reuses the exact patterns from `app/`'s
  `BleService.java`, which *is* verified working on this band — but the new
  code layered on top (the handshake state machine wired to GATT callbacks)
  is unverified in the field. Treat the first real connection attempt as a
  debugging session, and check `adb logcat` / `dsh -c logcat` (tag
  `BleService`) if auth doesn't complete.

## Why AES-CCM is hand-rolled

Android's `"AES/CCM/NoPadding"` transformation is only guaranteed present via
Conscrypt from API 28. Rather than raise minSdk, `Crypto.aesCcmEncrypt()`
builds CCM manually (CTR encryption + CBC-MAC, RFC 3610) on top of plain
`AES/ECB/NoPadding`, which every Android version has supported since API 1.
This keeps minSdk 26 (matching `app/`) and was the piece most worth testing
statically (see above) since there's no on-device way to check it here.

## Why this app doesn't die (keep-alive design)

Three independent layers, because a bare foreground service is not enough —
Doze and OEM battery managers (Samsung especially) can still freeze it:

1. **Foreground service correctness**: `BleService.startForeground()` fires
   in `onCreate()`, *before* any BLE work — not after a successful connect —
   so the service is never briefly backgrounded while it does I/O.
   `onStartCommand()` returns `START_STICKY`, so if Android kills the
   process anyway, it gets restarted (with a null intent — the service
   re-reads the last-saved MAC from `SharedPreferences`). A partial
   `WakeLock` is held only for the few seconds around each actual BLE
   operation (`connect()`, GATT writes, subscribe) via a short auto-release
   timeout (`wakeLock.acquire(10_000)`), not continuously — this is meant to
   be a light personal daemon, not something that pins the CPU awake.
2. **`BleWatchdog`** ([`BleWatchdog.java`](src/dev/miband/standalone/BleWatchdog.java)):
   a `JobScheduler` job (framework-only — no WorkManager/Gradle dependency
   resolution available in this build), `setPeriodic(15 min)` (the
   platform's minimum) and `setPersisted(true)` so it's re-registered after a
   reboot. Its only job is calling `startForegroundService(BleService)`
   again — a second line of defense if the OS kills the service outright
   despite layer 1. Starting an already-running service is a harmless no-op.
3. **Battery-optimization exemption**: MainActivity has a button that fires
   `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` for this app's own package —
   the single biggest real-world cause of background-service kills on stock
   Android.

**Manual step required on Samsung**: the devinfo the auth handshake sends
(`phoneName="SM-S7110"`) confirms this is a Samsung device, and Samsung's
battery manager is more aggressive than stock Doze — it can still kill
exempted apps. The `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` intent does
**not** cover this; you must separately go to **Settings → Battery →
Background usage limits** (or "Put unused apps to sleep" / "Sleeping apps"
depending on One UI version) and exclude MiBand Standalone there. There is no
public Intent/API to request this automatically.

**Honest limit**: even with all three layers plus the manual OEM step,
no third-party background app has an absolute guarantee against being killed
on Android. This gets close to what's achievable without a system app / device
owner profile.

## Build

No gradle, no Android SDK install — same toolchain as `app/` (`aapt2`,
`javac`, `d8`, `zipalign`, `apksigner`, all from Termux packages):

```sh
bash standalone/build.sh   # -> standalone/mibandstandalone.apk (signed)
```

Uses the platform jar at `$HOME/termux-adb-bridge/build/adbwifi-helper/android.jar`
(override with `$ANDROID_JAR`). A new self-signed keystore
(`standalone/keystore.jks`) is generated on first build if none exists — this
app is signed separately from `app/`'s `mibandbridge.apk` (different package,
different key), so the two can be installed side by side.

## Install (one-time, needs `dsh`/adb for the install step only — nothing at
runtime does)

```sh
dsh -p standalone/mibandstandalone.apk 'cat > /data/local/tmp/standalone.apk'
dsh 'pm install -r /data/local/tmp/standalone.apk'
```

Everything else is done from the app's own UI after that — no more `dsh`
needed:

1. Launch **MiBand Standalone** from the app drawer.
2. Enter the band's MAC address and tap **Save MAC + (re)connect**.
3. Enter the 16-byte (32 hex chars) auth key — the same one this repo already
   extracted into `notes/.authkey` — and tap **Save auth key**.
4. Under **One-time setup**, in order:
   - **Grant Bluetooth + notification permissions** (runtime prompt).
   - **Open notification-listener settings** → enable MiBand Standalone.
   - **Open all-files-access settings** → allow all-files access (needed for
     plain `File` I/O to the shared `/sdcard/MiBandLogs/` path).
   - **Ignore battery optimizations** → allow, then also do the manual
     Samsung step described above.
5. Tap **Start service**. The status line should move
   `disconnected → connecting → connected → authenticating → ready`. If it
   doesn't, see the logcat note above.

## Files

| Path | Role |
|---|---|
| `src/.../proto/Protobuf.java`, `Crc16.java`, `Constants.java` | wire codec + constants (port of `protobuf.py`/`crc.py`/`constants.py`) |
| `src/.../proto/Crypto.java` | HMAC-SHA256, AES-CTR, hand-rolled AES-CCM (port of `crypto.py`) |
| `src/.../proto/Frame.java` | L1 frame parse (port of `framing.py`'s `parse_frame`) |
| `src/.../proto/XiaoSession.java` | handshake state machine, GATT-callback-driven (port of `handshake.py`) |
| `src/.../proto/Commands.java` | notify/dismiss/battery command builders + battery reply parser |
| `src/.../BleService.java` | foreground service: GATT + auth + battery poll + keep-alive |
| `src/.../BleWatchdog.java` | JobScheduler watchdog (keep-alive layer 2) |
| `src/.../NotifyListenerService.java` | phone → band notification forwarding |
| `src/.../DataLogger.java` | raw-text append to `/sdcard/MiBandLogs/` |
| `src/.../MainActivity.java` | plain-views status/setup screen |
| `src/.../BootReceiver.java` | restarts service + re-schedules watchdog on boot |
| `test/CryptoTest.java` | standalone crypto verification vs. the Python implementation |
