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

## Risks / unknowns

1. **app_process + BluetoothGatt on Android 16** — unproven. Spike decides.
2. **SELinux / Binder** — shell is normally permitted; must verify.
3. **Hidden API** — not applicable to `app_process`, but verify at runtime.
4. **Xiaomi auth** — nontrivial; needs careful port from Gadgetbridge.
5. **Mi Fitness conflict** — it currently holds the GATT connection; must be
   stopped/disabled while the daemon runs.
6. **Auth key invalidation** — do not unpair from Mi Fitness; key stays valid.

## Fallbacks (in order)

1. Tiny custom bridge app exposing BLE to Termux (same protocol port).
2. Termux:API BLE fork.
3. Gadgetbridge + Intent API (already built in `../miband9-termux`).
