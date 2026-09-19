# Runbook — live command test (Mi Band 9 Active)

Division of labour for the next live test.

## Why this is needed

The band keeps a single login session. Mi Fitness auto-restarts and grabs it,
after which the band rejects/ignores our fresh login (`reg proc is ongoing,
reject login!`). Gadgetbridge's own guidance is to **remove the vendor app** —
we disable it. The band may still hold a stale session, so it needs a **reboot**
to get a clean slate.

## Agent (automated)

1. `pm disable-user --user 0 com.xiaomi.wearable`
2. start the shell-UID BLE daemon (`daemon/start.sh` over ADB)
3. after the band is back: authenticate and send `info`, `battery`, `findwatch`
4. `pm enable com.xiaomi.wearable` (restore)

## User (manual)

1. **Reboot the band** once Mi Fitness is disabled: band → Settings → System →
   Reboot. (This clears its session.)
2. **Watch the band** when `findwatch` runs — it should vibrate.
3. Nothing else.

## One-shot helper

From Termux:

```sh
bash notes/run-test.sh
```

It disables Mi Fitness, waits for you to reboot the band (Enter prompt), starts
the daemon, runs the commands, then re-enables Mi Fitness.

## Manual equivalent

```sh
adbwire 'pm disable-user --user 0 com.xiaomi.wearable'
# <reboot the band>
adbwire -p daemon/start.sh "sh -s -- <BAND_MAC> 8477"
python -m client.commands info --listen 8
python -m client.commands battery --listen 8
python -m client.commands findwatch --listen 8
adbwire 'pm enable com.xiaomi.wearable'
```

(`adbwire` is the vendored ADB client in `tools/adbwire/`; build with
`bash tools/adbwire/build.sh`.)

## Backend daemon (mibandd)

`mibandd` is the long-lived Termux-side backend: it owns the one
authenticated session (over the BLE daemon on `127.0.0.1:8477`), the SQLite
writer and request routing, and speaks JSON-lines on `127.0.0.1:8478`. The
same command is the CLI — `mibandd <domain> <op>` forwards to the running
backend and auto-starts it if it is not up.

```sh
mibandd serve --foreground --idle-timeout 600   # run the backend in the foreground
mibandd serve --daemonize                       # detach (~/.miband/mibandd.pid)
mibandd health collect                          # download + decode activity files
mibandd health summary                          # latest day's steps/HR/calories
mibandd store stats                             # what is in the database
```

The same `mibandd` command is the CLI (it forwards to the running backend and
auto-starts it if needed), so scripts just call `mibandd <domain> <op>`.
Tab-completion: `eval "$(mibandd completion bash)"` (bash/zsh/fish).

It exits after 600 s idle (override with `--idle-timeout`, or `--stay`).
Logs go to `~/.miband/mibandd.log`; the auth key is masked. See
[`DAEMON.md`](DAEMON.md) for the RPC contract and domains.

## BLE daemon notes

The daemon (v2) manages its own connection: it reconnects with exponential
backoff, rediscovers services, and re-subscribes after a drop — so a band
reboot no longer requires restarting it. Handy diagnostics before a test:

```sh
printf 'version\nstate\n' | python -c 'import sys;sys.path.insert(0,".");from client.protocol import Daemon;d=Daemon();[print(d.cmd(l.strip())) for l in sys.stdin]'
```

or just check its log: `adbwire 'tail -20 /data/local/tmp/bledaemon.log'`.
`state` should read `ready` with an MTU; if it says `disconnected`/`connecting`
the daemon is mid-reconnect.

## Auth flow notes

- `client/commands.py` uses the **no-session** flow by default (matches Mi
  Fitness: step 1 is the first packet).
- Add `--session` to use Gadgetbridge's V2 flow (session-config first). Try this
  if no-session fails on a clean band.
- The client retries the handshake and only reports success once session keys
  are derived.

## If it still fails

Per `AGENTS.md` (Rule 0): **consult the firmware before more trial-and-error.**

- `notes/FIRMWARE-DEEP.md` — auth/bind/login FSM, crypto, packet format.
- `notes/fw/reconstructed.bin` — grep for the failing subsystem's strings.
- Likely areas: session/registration state (`AUTH COMMON`), companion device
  (`miwear_companion_device_type`), or the login FSM (`MIWEAR_LOGIN_FSM_*`).
