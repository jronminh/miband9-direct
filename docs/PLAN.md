# Plan — direct BLE control from Termux

Goal: Termux owns the BLE connection to the Mi Band 9 Active and speaks the
Xiaomi protocol itself, with no Gadgetbridge and no companion app, using the
`shell` UID via `app_process`.

## Phase 0 — Spike (de-risk the unknown) — DONE ✅

Prove the core assumption before building anything big.

- [x] Write minimal Android stubs; `javac` → `stub.jar`.
- [x] Write `BleProbe.java` (bootstrap Context, get adapter, list devices,
      `connectGatt`).
- [x] Compile → `d8` → `classes.dex`.
- [x] `dsh` push to `/data/local/tmp`; run via `app_process`.
- [x] Confirm `GATT_CONNECTED` as the `shell` UID.

Result: **passed.** Key was calling `ActivityThread.initializeMainlineModules()`
before `systemMain()` (sets `BluetoothServiceManager`). Band is LE-only and not
bonded at the Android level; found via `getConnectedDevices(GATT=7)`. Details in
`docs/SPIKE.md` and `notes/FINDINGS.md`.

## Phase 1 — Transport daemon — DONE ✅

- [x] `BleDaemon.java`: long-lived, `Looper.loop()`, listens on `127.0.0.1:8477`.
- [x] Line protocol: `ping`, `services`, `read <uuid>`, `write <uuid> <hex>`,
      `write-nr`, `subscribe <uuid>`, `mtu <n>`; pushes `NOTIFY <uuid> <hex>`.
- [x] `dsh` launcher (`notes/start-daemon.sh`) starts it detached (`setsid`).
- [x] Python client (`notes/client.py`).

Verified: daemon connects to the band, discovers 25 characteristics, and from
Termux we read battery (`0x1a` = 26%), model (`"leopard"`), manufacturer, and
subscribed to the notify characteristic `005e`.

GATT confirmed: service `fe95`, notify `005e` (props 0x14), write `005f`
(props 0x04).

## Phase 2 — Xiaomi protocol — DONE ✅

- [x] UUIDs confirmed live (`fe95` / notify `005e` / write `005f`).
- [x] Frame codec (A5A5 + CRC-16/ARC) validated against captured traffic.
- [x] Auth handshake ported (HMAC-SHA256 `miwear-auth` derivation, AES-CCM
      AuthDeviceInfo, AES-128-CTR messages).
- [x] **Authenticated live from Termux** (`client/protocol/handshake.py`):
      step1 phoneNonce → watchNonce+hmac → step3 → `authStep4` success,
      session keys derived.
- [x] Key finding: send the type-2 **start request first**, then `step1`. The
      SESSION frame does **not** consume the DATA sequence number (both use
      seq 0) — the client resets `sess.seq` after it. Writes must use
      write-with-response and be serialized (`write_reliable`).

Exit criteria met: authenticated session established.

## Phase 3 — Commands

- [x] Notification send (`notify` command, type 7 subtype 0 — verified on band).
- [x] Find band (`findwatch`) — sent and ACKed.
- [ ] Activity sync (subset: steps, HR, sleep).
- [x] Device info / battery (`info`, `battery` return real data).
- [ ] Device settings (as supported).

## Phase 4 — Productise

Superseded in shape by [`DAEMON.md`](DAEMON.md): one `mibandd` backend owns the
session, store, decode and scheduler; per-field thin clients drive it.

- [ ] `mibandd` backend: one authed session, JSON-lines RPC, idle-exit.
- [ ] Per-field clients (`miband-health` / `-notify` / `-device` / `-store`).
- [ ] Daemon lifecycle: start/stop/status, restart on failure.
- [ ] `termux-opencode-job` recipe for periodic sync.
- [ ] Error handling, timeouts, reconnect.

## Phase 5 — Headless companion app (stability path)

Motivation: the shell-UID `app_process` route is inherently unstable — it needs
a live ADB / Wireless Debugging link (the `dsh` daemon dies independently), the
daemon does not survive a reboot, and it fights Mi Fitness for the single login.
A real app process owns the radio with normal permissions and a foreground
service, so it survives reboots and drops the ADB dependency entirely — while
staying Termux-compatible.

Design: **Termux keeps the intelligence, the app keeps the radio.** The app has
no launcher entry and no custom UI — **Termux is the launcher** (`am start`).
It exposes the *same* loopback line protocol, so `mibandd` and `client/` are
unchanged.

Implemented in `app/` — built and signed to `app/mibandbridge.apk`.

- [x] **Reuse the transport.** Moved into a `Service`: the GATT callbacks, write
      serialization and the `127.0.0.1:8477` server are unchanged
      (`app/src/dev/miband/bridge/BleService.java`).
- [x] **Swap the bootstrap.** `main()`'s shell-UID hack is gone;
      `Service.onCreate()` gets `BLUETOOTH_SERVICE` normally, starts the server
      and calls `startForeground`.
- [x] **Manifest:** legacy `BLUETOOTH` / `BLUETOOTH_ADMIN` (maxSdk 30) plus
      `BLUETOOTH_CONNECT` / `SCAN`, `FOREGROUND_SERVICE`, `RECEIVE_BOOT_COMPLETED`,
      `WAKE_LOCK`, `INTERNET` (loopback TCP needs it). No `LAUNCHER` category →
      never appears in the app drawer.
- [x] **One-time `pm grant`.** On this Android 16 device `targetSdk 30` does
      **not** exempt the modern permission — `connectGatt` threw
      `SecurityException: Need android.permission.BLUETOOTH_CONNECT`. So grant
      once over `dsh` after install:
      `pm grant dev.miband.bridge android.permission.BLUETOOTH_CONNECT` (and
      `...BLUETOOTH_SCAN`). Still no runtime dialog and no UI — but it is a
      setup step, not zero-config as first hoped.
- [x] **Package + sign** with `aapt2` / `d8` / `apksigner` / `zipalign` — no
      gradle, no Android SDK. Build: `bash app/build.sh`.
- [x] **Install + verify** — done. `pm install -r`, grant the two BT perms,
      launch `dev.miband.bridge/.PermitActivity --es mac <MAC>`. The service
      reports `state=ready` on `127.0.0.1:8477` and `mibandd device battery`
      returned live data (`{"level": 61, "state": 2}`) with the shell-UID BLE
      daemon stopped. **Reboot-survival confirmed**: after a device reboot the
      service is back at `state=ready` and `mibandd device battery` works with
      `dsh` down.
- [ ] **Optional / parked: patch termux-app for `termux-am`.** The release
      build (v0.119.0-beta.3) has the am socket server commented out, so
      `termux-am` cannot work and updating does not help (latest official =
      installed version; no nightly; other APKs are signed with a different key
      → uninstall → wipe). The only route is a master build with that block
      uncommented, self-signed, shipped with a `~` + `$PREFIX`
      backup/uninstall/restore procedure. Not now — `am` is used instead. See
      [`COMPANION-APP.md`](COMPANION-APP.md).

Known costs (accepted):

1. **Persistent notification** — a foreground service must post one (silent,
   low-priority, minimizable). Truly invisible is not possible on modern
   Android; this is the price of dropping ADB.
2. **Samsung battery management** — on this S23 FE the app must be exempted
   from battery optimization (or at least allowed to auto-start), or the
   service gets frozen.

Outcome: stable, reboot-surviving, Termux-compatible — no `dsh`, no shell UID.

## Risks / unknowns

1. **app_process + BluetoothGatt on Android 16** — unproven. Spike decides.
2. **SELinux / Binder** — shell is normally permitted; must verify.
3. **Hidden API** — not applicable to `app_process`, but verify at runtime.
4. **Xiaomi auth** — nontrivial; needs careful port from Gadgetbridge.
5. **Mi Fitness conflict** — it currently holds the GATT connection; must be
   stopped/disabled while the daemon runs.
6. **Auth key invalidation** — do not unpair from Mi Fitness; key stays valid.

## Fallbacks (in order)

1. Headless companion app exposing BLE to Termux (same protocol port) — now
   promoted to [Phase 5](#phase-5--headless-companion-app-stability-path).
2. Termux:API BLE fork.
3. Gadgetbridge + Intent API (already built in `../miband9-termux`).
