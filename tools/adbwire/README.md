# adbwire (vendored)

`adbwire` is a minimal ADB client for Android **Wireless Debugging**, vendored
from [termux-adb-bridge](https://github.com/jronminh/termux-adb-bridge) so this
repo does not depend on that project's persistent shell daemon
(`relaysh` / `dsh`).

It connects over TLS to an already-paired device and runs **one** shell command
(optionally streaming a file into its stdin) — no adb server, no long-lived
daemon. That is the safety win over `dsh`: nothing keeps listening as the
`shell` UID between runs.

## Build

```sh
bash tools/adbwire/build.sh      # -> tools/adbwire/out/adbwire
```

Requires `clang` and `openssl` (`pkg install clang openssl`).

## Prerequisites

- Developer Options → **Wireless debugging** enabled.
- The device paired with your `~/.android/adbkey`. Pair once with the stock
  client (which creates the key), then `adbwire` reuses it:

  ```sh
  pkg install android-tools
  adb pair 127.0.0.1:<pairing-port> <6-digit code>   # once
  ```

  Or, if `~/.android/adbkey` already exists:
  `tools/adbwire/out/adbwire --pair <6-digit code>`.

## Usage

```sh
adbwire 'id'                         # discover port via mDNS, run as shell UID
adbwire -p file.bin 'cat > /path'    # stream a local file into the command
adbwire --discover                   # print the wireless-debugging port
adbwire --pair <code>                # pair, then exit
```

Exit status is the remote command's exit status.

## License

GPL-3.0-only — see [`LICENSE`](LICENSE) (copied from termux-adb-bridge).
`ed25519/` carries its own [`NOTICE`](ed25519/NOTICE).
