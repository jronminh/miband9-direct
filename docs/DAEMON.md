# mibandd — single backend daemon

Goal: **one** long-lived process owns every backend job; the user-facing
commands become dumb clients. Today every `miband` invocation opens its own
session, re-authenticates (~1 s) and writes SQLite itself. That is fine for a
one-off, wrong for anything periodic.

## Why a daemon at all

The band allows **one login per connection** and auth is expensive, so the
protocol session must be kept warm and single-tenant. The same argument applies
to the other singletons:

- the authenticated session (one login per connection),
- the SQLite writer (no cross-process locking),
- reconnect / re-auth logic,
- event fan-out (incoming call / notification),
- the collection scheduler.

One owner for all of them ⇒ one daemon.

## Target shape

```
 mibandd CLI (client mode)        mibandd <domain> <op>
        │  JSON-lines → TCP 127.0.0.1:8478
        ▼
 mibandd                          long-lived (Termux UID)
   • owns ONE authenticated session
   • serialises ops, single SQLite writer
   • domains, events, scheduler, decode
        │  line protocol → TCP 127.0.0.1:8477
        ▼
 BleDaemon (app_process, shell UID)   already exists
        │  Android BluetoothGatt
        ▼
 Mi Band 9 Active
```

Two daemons, each with a distinct reason: `BleDaemon` because Termux cannot
touch BLE (needs `shell` UID); `mibandd` because the protocol session is
expensive and single-tenant.

## Layering rules

```
mibandd/
  rpc/         JSON-lines server :8478, router, request/response types
  transport/   link to BleDaemon :8477 (framing, reconnect)   [client/protocol]
  session/     SessionManager — ONE authed session, lock/queue, re-auth
  domains/     one module per field, self-registered via OPS
  store/       band.db, repositories, single writer            [store/]
  events/      band-initiated msgs → subscribers
  lifecycle/   spawn handshake, idle-exit, wake-lock, pid/log
  bin/         entry points
```

1. **Domains never touch `transport` or SQLite directly** — only `session` and
   `store`. Keeps every domain the same shape and testable without a band.
2. **Self-registration.** Each domain exports a name and
   `OPS = {"collect": fn, ...}`; the router builds its table from those.
   Adding a field (e.g. health decode) is one new module, no router edit.
3. **Session is a serialised shared resource** behind a lock/queue. Domains
   call `session.request(...)`; they never auth.

## Process model

- `mibandd` listens on `127.0.0.1:8478`, JSON-lines: one request per line, one
  response per line, optional async `event` lines.
- **Lazy auto-spawn**: a client that cannot connect spawns `mibandd` detached
  and polls for `ready`, so nothing is managed by hand.
- **Idle-exit** after N minutes with no clients (default on); `--stay` +
  `termux-wake-lock` keeps it warm for frequent sampling.
- PID file and log under `~/.miband/`; logs mask the auth key.

## RPC contract

```json
{"id": 1, "domain": "health", "op": "collect", "args": {"limit": 1}}
{"id": 1, "ok": true, "result": [ ... ]}
{"id": 1, "ok": false, "error": {"code": "band_unreachable", "msg": "..."}}
```

Built-in ops (no domain): `ping`, `version`, `state`, `shutdown`.

## Entry points

`mibandd` is both the backend and the CLI:

| command | role |
|---|---|
| `mibandd serve [--foreground\|--daemonize\|--idle-timeout N\|--stay]` | run the backend |
| `mibandd ping` / `version` / `state` / `shutdown` | daemon built-ins |
| `mibandd call <domain> <op> [--args JSON]` | raw RPC |
| `mibandd device …` / `notify …` / `health …` / `store …` | domain ops |
| `mibandd key` / `schedule` / `watch` / `commands` | local utilities |
| `mibandd completion bash\|zsh\|fish` | shell tab-completion |

The per-field clients and the `miband` compat frontend were folded into
`mibandd` so there is a single command to install and script.

Every client form forwards to a running `mibandd` (auto-starting it if down),
so the same command serves one-offs and scripts:

```sh
mibandd store stats --json
mibandd health collect
mibandd health summary
mibandd health trend --metric daily.hr_avg
mibandd device battery
```

## Migration map

| now | becomes |
|---|---|
| `client/` (protocol, session, activity, registry) | `transport/` + `session/` + protocol lib |
| `api/` (band, parse, events, registry) | `domains/` |
| `store/` | `store/` |
| `bin/miband` backend half | `session/` + `lifecycle/` + `domains/` |
| `bin/miband` verb half | the thin clients |

## Phases

### D1 — Daemon core (additive; existing code untouched) — DONE ✅

- `mibandd/` package with `rpc`, `session`, `lifecycle`.
- `SessionManager`: lazy connect + auth, serialise, reconnect/re-auth, exposes
  `request(domain, op, args)`.
- TCP server, `ping` / `version` / `state` / `shutdown`, idle-exit, pid/log.
- **Acceptance**: `mibandd` starts, `ping` answers, idle-exits; unit tests with
  a fake session; no changes to existing modules.

### D2 — Router + domains — DONE ✅

- `domains/registry.py`; move current verbs into `device`, `notify`, `health`
  (collect/blob/dump), `scheduler`.
- Domains use only `session` + `store`.
- **Acceptance**: `miband-device info` and `miband-notify` work through the
  daemon; the existing test suite still passes.

### D3 — Thin clients + compat shim — DONE ✅ (shim deferred to D6)

- `mibandd_client` lib (connect, lazy-spawn, send, print).
- `miband-health` / `-notify` / `-device` / `-store` executables; `miband`
  forwards.
- **Acceptance**: every command that works today works through the new entry
  points.

### D4 — Health decoder — DONE ✅

- v4 daily-summary decoder (`docs/ACTIVITY.md` layout) writing to `samples`.
- `miband-health decode` / `summary` / `trend`.
- **Acceptance**: decoded values match the manual decode; tests over the stored
  blobs.

### D5 — Scheduling + events

- JobScheduler wrapper calls `miband-health collect` (not the whole CLI).
- Event fan-out for incoming call/notification.
- **Acceptance**: a scheduled run hits the warm session (no re-auth in the log).

### D6 — Packaging + cleanup — DONE ✅

- `install.sh` installs the entry points; `RUNBOOK.md` updated; `bin/miband`
  demoted to a shim.
- **Acceptance**: fresh `install.sh` yields working commands.

## Risks / open questions

- **Android killing the daemon** when the screen locks — idle-exit + lazy spawn
  makes this survivable; `termux-wake-lock` for continuous sampling.
- **SQLite** — one writer (the daemon); readers use WAL. `miband-store` reads
  directly and therefore cannot trigger a fresh sync.
- **Single command** — `mibandd` is the only installed command (backend + CLI);
  the per-field clients and `miband` frontend were removed.
- **Security** — bind localhost only; never log the auth key.
