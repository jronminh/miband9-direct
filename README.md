# miband9-direct

[![License](https://img.shields.io/github/license/jronminh/miband9-direct)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Termux%20%7C%20Android-informational)

Control a **Xiaomi Smart Band 9 Active** from **Termux** — no root, no vendor
app, no Gadgetbridge. It speaks the Xiaomi BLE protocol itself and exposes a
backend daemon plus a single `mibandd` CLI.

## Docs

- [`docs/USAGE.md`](docs/USAGE.md) — command reference and workflows
- [`docs/DAEMON.md`](docs/DAEMON.md) — backend design, RPC contract, phases
- [`docs/ACTIVITY.md`](docs/ACTIVITY.md) — activity transfer + decoder
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — BLE transport, line protocol
- [`docs/COMMANDS.md`](docs/COMMANDS.md) — command catalogue
- [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — live-test procedure
- [`docs/PLAN.md`](docs/PLAN.md) — roadmap

## Quick start

```sh
git clone https://github.com/jronminh/miband9-direct
cd miband9-direct
./install.sh                       # build, start, extract the auth key, link mibandd
mibandd device battery
mibandd health collect             # download + decode recorded activity
mibandd health summary             # latest day's steps / HR / calories
```

Full command reference: [`docs/USAGE.md`](docs/USAGE.md).

## How it works

Termux runs as `untrusted_app` and **cannot open the BLE radio** (no `/dev` HCI
node, no BlueZ, no GATT over `cmd bluetooth_manager`). The `shell` UID can — so
the intelligence lives in Termux and the radio lives in a thin shell-UID
transport:

```
mibandd  (Termux UID)   backend + CLI   ── JSON-lines :8478 ──► scripts
   │  one authenticated Xiaomi session
   │  SQLite store, domain router, decoder
   ▼  line protocol :8477
BleDaemon (shell UID, app_process)   ── Android BluetoothGatt ──► Mi Band 9 Active
```

- **`daemon/`** — the BLE transport (`BleDaemon.java` → dex → `app_process`),
  launched on demand over **ADB / Wireless Debugging** with the vendored
  `adbwire`. It auto-reconnects with backoff and re-subscribes after a drop.
- **`mibandd/`** — the Termux backend *and* CLI. One long-lived process owns the
  single authenticated session (the band allows one login per connection), the
  SQLite writer and the domain router; the same command is the CLI.

More: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
[`docs/DAEMON.md`](docs/DAEMON.md).

### Verified on this device

Root **none** (no `su`/Magisk) · Termux UID `10663` (`untrusted_app`) ·
`shell` UID `2000` with `BLUETOOTH_CONNECT`/`SCAN`/`PRIVILEGED` granted ·
`app_process` present · Android 16 / SDK 36 / arm64-v8a · band bonded LE
("Xiaomi Band 9 Activ") · auth key extractable from Mi Fitness logs over ADB.

## Requirements

- Android with **Wireless Debugging** enabled; pair once with
  `./install.sh --pair <code>`.
- `clang` + `openssl` (build `adbwire`), `javac` + `d8` (build the daemon),
  `python3` + `cryptography`.
- **Mi Fitness disabled** while this owns the band's single login
  (`./install.sh --disable-mifit`).

The BLE daemon does not survive a reboot — re-run `./install.sh --no-build`.

## CLI

`mibandd <domain> <op>`; it auto-starts the backend and is script-friendly
(`--json`, exit codes). Domains: `device`, `notify`, `health`, `store`, plus the
local `key`, `schedule`, `watch`, `commands`, `completion`.

```sh
mibandd device battery
mibandd notify notify --title "Build done" --text "tests passed"
mibandd health collect            # download + decode daily summaries
mibandd health summary
mibandd health trend --metric daily.hr_avg
mibandd store stats --json
eval "$(mibandd completion bash)" # bash / zsh / fish
```

Details: [`docs/USAGE.md`](docs/USAGE.md).

## Health data

`collect` lists the band's recorded file ids, requests each one, reassembles the
Activity-channel chunks, CRC-verifies, stores the body, and decodes the daily
**summary** into `daily.*` samples (`store/summary.py`). Metrics include steps,
active calories, and resting/max/min/avg heart rate. The band streams daily
summaries but not details/sleep — see [`docs/ACTIVITY.md`](docs/ACTIVITY.md).

## Python API

```python
from api import MiBand
with MiBand() as band:
    band.battery_status()   # {'level': 85, 'state': 2}
    band.device_info()      # {'serial': ..., 'firmware': ..., 'model': ...}
    band.notify("Hi", "from Termux")
    band.command("face-list")   # any registry command, by name
```

```python
from store import BandData
with BandData() as band:
    band.battery()
    band.activity_files()
    band.db.latest("battery.level")
```

Every known command (type/subtype, status) is catalogued in
[`docs/COMMANDS.md`](docs/COMMANDS.md); `client/registry.py` is the source of
truth (`mibandd commands`, or `python -m client.registry --markdown`).

## Layout

```
daemon/    shell-UID BLE transport (Java → dex → app_process)
client/    Xiaomi protocol: framing, auth handshake, command registry
store/     SQLite persistence + daily-summary decoder
mibandd/   backend daemon + CLI (session, rpc, domains, completion)
api/       high-level facade over client/
bin/       mibandd entry point
docs/      architecture, daemon, activity, usage, runbook, commands
install.sh one-shot setup over ADB (adbwire)
tests/     unit tests (no band needed)
```

## Development

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Working rules are in [`AGENTS.md`](AGENTS.md): **analyze the reconstructed
firmware before trial-and-error on protocol behaviour.**

## Status

- [x] Shell-UID `app_process` opens a GATT connection to the band
- [x] BLE daemon: localhost transport, auto-reconnect, multi-client
- [x] Xiaomi auth handshake + read/notify commands verified live
- [x] Activity collector: list, fetch, reassemble, CRC-verify, ack
- [x] v4 daily-summary decoder → `daily.*` samples
      (`collect` / `decode` / `summary` / `trend`)
- [x] `mibandd` backend + CLI, domains, shell completion
- [ ] Decode details/sleep files (listed by the band but never streamed)

## License

**AGPL-3.0-or-later** — see [`LICENSE`](LICENSE). Contributors:
[`CONTRIBUTORS.md`](CONTRIBUTORS.md).

The protocol client (`client/protocol/`, `client/activity.py`) and the
daily-summary decoder (`store/summary.py`) are Python translations of
[Gadgetbridge](https://gadgetbridge.org) (AGPL-3.0) and carry SPDX +
attribution headers; `tools/adbwire/` is a vendored GPL-3.0 project.
