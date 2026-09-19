# Usage — miband9-direct

Drive a Xiaomi Smart Band 9 Active from Termux with no root and no vendor
app. Two processes:

```
mibandd  (backend + CLI, Termux UID)  ──JSON-lines :8478──►  clients/scripts
   │
   └── line protocol :8477 ──►  BleDaemon (app_process, shell UID) ──► band
```

See [`DAEMON.md`](DAEMON.md) for the backend design and [`ARCHITECTURE.md`](ARCHITECTURE.md)
for the BLE transport.

## 1. One-time setup

```sh
cd ~/miband9-direct
./install.sh
```

`install.sh` runs, in order: Python deps (`cryptography`), builds the vendored
`adbwire` (clang/openssl), checks Wireless Debugging (pair with
`./install.sh --pair <code>`), builds the shell-UID BLE daemon (javac + d8),
detects the band MAC, starts the daemon, extracts the auth key to
`notes/.authkey`, symlinks `mibandd` into `$PREFIX/bin`, and smoke-tests.

What you must provide:

- Developer Options → **Wireless debugging** enabled.
- **Mi Fitness disabled** while this owns the band's single login:
  `./install.sh --disable-mifit` (re-enable later with `pm enable`).

The BLE daemon does **not** survive a reboot; re-run `./install.sh --no-build`.

## 2. Backend lifecycle

The CLI auto-starts the backend on first use, so this is usually optional.

```sh
mibandd serve --daemonize      # detach; exits after 600s idle
mibandd serve --foreground     # watch it in the terminal
mibandd serve --stay           # never idle-exit
mibandd shutdown               # stop it now
```

State: pid + log under `~/.miband/` (`mibandd.pid`, `mibandd.log`; the auth
key is masked in logs).

## 3. CLI

`mibandd <domain> <op> [flags]`. Common flags: `--json` (compact), `--host`,
`--port` (default `127.0.0.1:8478`), `--no-spawn`.

### device
```sh
mibandd device battery
mibandd device info
mibandd device state
mibandd device clock --h12
mibandd device find              # --stop to stop
mibandd device cmd --command face-list
mibandd device raw --type 2 --subtype 1 --body ''
```

### notify
```sh
mibandd notify notify --title "Build done" --text "tests passed"
mibandd notify call --name "Alice" --number "123"
mibandd notify callend
mibandd notify dismiss --id 1
```

### health
```sh
mibandd health list              # recorded file ids on the band
mibandd health collect           # download daily summaries + decode
mibandd health collect --raw     # store raw bytes only, no decode
mibandd health decode            # backfill existing blobs into samples
mibandd health summary           # latest day's decoded fields
mibandd health trend --metric daily.hr_avg --limit 30
mibandd health blob --file-ts 1789784085 --suffix 1c0401 --out out.bin
```

### store (read-only)
```sh
mibandd store stats
mibandd store samples --metric daily.hr_resting --limit 10
mibandd store history --name battery
mibandd store blobs              # downloaded file metadata
mibandd store files              # id index from the band
```

### built-ins and raw RPC
```sh
mibandd ping | version | state | shutdown
mibandd call <domain> <op> --args '{"limit":1}'
```

## 4. Health data

`collect` lists the band's file ids, requests each, reassembles the
Activity-channel chunks, CRC-verifies, stores the body in `activity_blobs`,
and (unless `--raw`) decodes the daily **summary** into `daily.*` samples
(`store/summary.py`). Decoding is idempotent, so `decode` can be re-run.

Metrics: `daily.steps`, `daily.active_calories`, `daily.hr_resting`,
`daily.hr_max`, `daily.hr_min`, `daily.hr_avg`, `daily.standing`.

Details/sleep files are listed by the band but never streamed — see
[`ACTIVITY.md`](ACTIVITY.md).

## 5. Local utilities (no daemon)

```sh
mibandd key [--show]             # extract/save the auth key (ADB)
mibandd schedule install --period-min 15   # Android JobScheduler collection
mibandd schedule status | remove
mibandd watch --interval 60      # sample battery
mibandd commands                 # list the command registry
mibandd completion bash|zsh|fish # shell tab-completion
```

## 6. Automation

```sh
eval "$(mibandd completion bash)"              # tab-completion
mibandd health summary --json | jq .fields.hr_resting
mibandd store stats --json                     # one line, exit 0/1
mibandd health collect --no-spawn              # fail if the daemon is down
```

Any script/language can speak the raw JSON-lines RPC on `127.0.0.1:8478`:

```
{"id":1,"domain":"health","op":"summary","args":{}}
{"id":1,"ok":true,"result":{...}}
```

## 7. Working on the repo

- `mibandd/` — backend (`session`, `rpc`, `lifecycle`, `main`, `cli`,
  `complete`, `setup`) and `domains/` (device, notify, health, store).
- `client/` — Xiaomi protocol/auth; `store/` — SQLite + `summary.py` decoder;
  `api/` — high-level facade; `daemon/` — Java BLE transport.
- Tests: `python3 -m unittest discover -s tests -v`.
- Rules: [`AGENTS.md`](../AGENTS.md) (firmware-first before protocol guessing).

## 8. Troubleshooting

- **Band won't answer** → Mi Fitness re-enabled or the BLE daemon is down:
  `./install.sh --no-build`, then check
  `adbwire 'tail -20 /data/local/tmp/bledaemon.log'`.
- **Login rejected** → reboot the band after disabling Mi Fitness; see
  [`RUNBOOK.md`](RUNBOOK.md).
- **Key invalid** → never unpair from Mi Fitness; re-extract with
  `mibandd key --show`.
