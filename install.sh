#!/data/data/com.termux/files/usr/bin/bash
#
# install.sh — set up miband9-direct from a fresh clone, from source.
#
# Uses adbwire (vendored under tools/adbwire) over Android Wireless Debugging
# to run shell commands as the `shell` UID. There is NO persistent shell daemon
# (the old termux-adb-bridge `dsh`/relaysh path is gone): each step is one
# on-demand ADB command.
#
# Does, in order:
#   1. Python deps (cryptography)
#   2. Build the vendored adbwire (clang + openssl)
#   3. Check Wireless Debugging / pairing (pair with --pair <code>)
#   4. Java toolchain (javac + d8) to build the daemon
#   5. Build + install the shell-UID BLE daemon
#   6. Resolve the band MAC (auto-detect, or --mac / $MIBAND_MAC)
#   7. Start the daemon
#   8. Recover the auth key from Mi Fitness logs (miband key)
#   9. Symlink the mibandd command into $PREFIX/bin
#  10. Optional: register the periodic collection job (--with-job)
#  11. Smoke test (miband battery)
#
# Usage: ./install.sh [--pair CODE] [--no-build] [--no-daemon] [--no-pkg]
#                     [--with-job] [--disable-mifit]
#                     [--mac AA:BB:CC:DD:EE:FF] [--port N]
#
# Env: MIBAND_ADB=<path to adbwire>   MIBAND_ADB_HOST=<host:port>
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO" || exit 1

DO_BUILD=1 DO_DAEMON=1 DO_PKG=1 DO_JOB=0 DISABLE_MIFIT=0
MAC="${MIBAND_MAC:-}"
PORT="${MIBAND_PORT:-8477}"
PAIR_CODE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --pair)          PAIR_CODE="${2:-}"; shift ;;
        --no-build)      DO_BUILD=0 ;;
        --no-daemon)     DO_DAEMON=0 ;;
        --no-pkg)        DO_PKG=0 ;;
        --with-job)      DO_JOB=1 ;;
        --disable-mifit) DISABLE_MIFIT=1 ;;
        --mac)           MAC="${2:-}"; shift ;;
        --port)          PORT="${2:-}"; shift ;;
        -h|--help)       sed -n '2,29p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   [ok] %s\n' "$*"; }
warn() { printf '   [!!] %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

[ -n "${PREFIX:-}" ] && [ -x "${PREFIX}/bin/pkg" ] \
    || die "this looks like it is not running in Termux (\$PREFIX unset)"

# ---------------------------------------------------------------- 1. python
step "Python dependencies"
have python3 || die "python3 not found (pkg install python)"
ok "python $(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
if ! python3 -c 'import cryptography' 2>/dev/null; then
    if [ "$DO_PKG" -eq 1 ]; then
        python3 -m pip install --quiet -r requirements.txt \
            || { have pkg && pkg install -y python-cryptography; }
    fi
fi
python3 -c 'import cryptography' 2>/dev/null \
    && ok "cryptography $(python3 -c 'import cryptography;print(cryptography.__version__)')" \
    || warn "cryptography missing: python3 -m pip install -r requirements.txt"

# --------------------------------------------------------------- 2. adbwire
step "Build adbwire (Wireless-Debugging ADB client)"
if have clang || { [ "$DO_PKG" -eq 1 ] && pkg install -y clang openssl; }; then
    bash tools/adbwire/build.sh && ok "tools/adbwire/out/adbwire"
else
    warn "clang/openssl missing (pkg install clang openssl)"
fi
ADB="${MIBAND_ADB:-}"
if [ -z "$ADB" ]; then
    if [ -x tools/adbwire/out/adbwire ]; then
        ADB="$REPO/tools/adbwire/out/adbwire"
    elif have adbwire; then
        ADB="$(command -v adbwire)"
    fi
fi
ADB_EXTRA=()
[ -n "${MIBAND_ADB_HOST:-}" ] && ADB_EXTRA=(-s "$MIBAND_ADB_HOST")
adbsh() { "$ADB" "${ADB_EXTRA[@]}" "$@"; }

# --------------------------------------------------- 3. wireless debugging
step "Wireless Debugging"
if [ -z "$ADB" ]; then
    warn "no adbwire binary; skipping ADB steps"
    DO_DAEMON=0
elif [ -n "$PAIR_CODE" ]; then
    adbsh --pair "$PAIR_CODE" && ok "paired"
elif adbsh id >/dev/null 2>&1; then
    ok "reachable as $(adbsh id 2>/dev/null | head -1)"
else
    warn "adbwire cannot reach the device. In Developer Options:"
    warn "  1) enable 'Wireless debugging'"
    warn "  2) tap 'Pair device with pairing code', then re-run:"
    warn "       ./install.sh --pair <6-digit-code>"
    warn "  (or pair once with stock adb: adb pair 127.0.0.1:<port> <code>)"
    DO_DAEMON=0
fi

# ----------------------------------------------------------------- 4. java
step "Java toolchain (to build the daemon)"
if have javac && have d8; then
    ok "javac + d8 present"
elif [ "$DO_PKG" -eq 1 ]; then
    warn "javac/d8 missing; installing openjdk-17 + d8"
    pkg install -y openjdk-17 d8 || warn "package install failed"
    have javac && have d8 && ok "javac + d8 installed" \
        || warn "still missing javac/d8; daemon build will be skipped"
else
    warn "javac/d8 missing and --no-pkg given"
fi

# ---------------------------------------------------------------- 5. build
step "Build + install the BLE daemon"
if [ "$DO_BUILD" -eq 1 ] && have javac && have d8; then
    if [ -n "$ADB" ] && [ "$DO_DAEMON" -eq 1 ]; then
        ADB="$ADB" MIBAND_ADB_HOST="${MIBAND_ADB_HOST:-}" \
            bash daemon/build.sh --install && ok "daemon built + pushed"
    else
        bash daemon/build.sh && ok "daemon built (not pushed: no ADB)"
    fi
else
    ok "skipped"
fi

# ------------------------------------------------------------------ 6. MAC
step "Band MAC"
if [ -z "$MAC" ] && [ -f config/miband.env ]; then
    # shellcheck source=/dev/null
    . config/miband.env 2>/dev/null || true
    MAC="${MIBAND_MAC:-$MAC}"
fi
if [ -z "$MAC" ] && [ -n "$ADB" ]; then
    # dumpsys masks all but the last two octets (XX:XX:XX:XX:44:76); use that
    # suffix to pick the full address out of the Mi Fitness logs.
    masked="$(adbsh "dumpsys bluetooth_manager 2>/dev/null \
        | grep -i 'Xiaomi Band' | head -1" 2>/dev/null | tr -d '\r')"
    suffix="$(printf '%s' "$masked" \
        | grep -oE '[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}' | tail -1)"
    logs="$(adbsh "grep -rEho '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}' \
        /sdcard/Android/data/com.xiaomi.wearable/files/log/*.log 2>/dev/null \
        | sort -u" 2>/dev/null | tr -d '\r')"
    if [ -n "$suffix" ]; then
        MAC="$(printf '%s\n' "$logs" | grep -i ":$suffix\$" | head -1)"
    fi
    [ -z "$MAC" ] && MAC="$(printf '%s\n' "$logs" | head -1)"
    [ -n "$MAC" ] && ok "detected $MAC"
fi
# Last resort: a MAC left in the local (gitignored) start script.
if [ -z "$MAC" ] && [ -f notes/start-daemon.sh ]; then
    MAC="$(grep -oE '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}' \
        notes/start-daemon.sh | head -1)"
    [ -n "$MAC" ] && ok "reused MAC from notes/start-daemon.sh"
fi
if [ -n "$MAC" ]; then
    umask 077
    printf 'MIBAND_MAC=%s\nMIBAND_PORT=%s\n' "$MAC" "$PORT" > config/miband.env
    ok "saved to config/miband.env"
else
    warn "could not determine the band MAC; set MIBAND_MAC or pass --mac"
    DO_DAEMON=0
fi

# --------------------------------------------------------------- 7. daemon
step "Start the BLE daemon"
if [ "$DO_DAEMON" -eq 1 ] && [ -n "$MAC" ] && [ -n "$ADB" ]; then
    adbsh -p daemon/start.sh "sh -s -- $MAC $PORT"
else
    warn "skipped (need working ADB + MAC)"
fi

# ------------------------------------------------------- 8. Mi Fitness off
if [ "$DISABLE_MIFIT" -eq 1 ] && [ -n "$ADB" ]; then
    step "Disable Mi Fitness (frees the GATT link)"
    adbsh 'pm disable-user --user 0 com.xiaomi.wearable' || warn "failed"
    ok "com.xiaomi.wearable disabled (re-enable: pm enable)"
else
    warn "Mi Fitness holds the GATT link while enabled; disable it if the"
    warn "daemon cannot connect (or re-run with --disable-mifit)."
fi

# ---------------------------------------------------------------- 9. key
step "Auth key"
if [ -s notes/.authkey ]; then
    ok "notes/.authkey already present"
else
    python3 "$REPO/bin/mibandd" key || \
        warn "could not extract the key (enable Mi Fitness once, then retry)"
fi

# -------------------------------------------------------------- 10. command
step "Install the mibandd command"
ln -sf "$REPO/bin/mibandd" "${PREFIX}/bin/mibandd"
have mibandd && ok "${PREFIX}/bin/mibandd -> $REPO/bin/mibandd"

# ----------------------------------------------------------------- 11. job
if [ "$DO_JOB" -eq 1 ]; then
    step "Register the periodic collection job"
    python3 "$REPO/bin/mibandd" schedule install --period-min 15 \
        && ok "job registered (mibandd schedule status)"
else
    printf '   [--] job not registered (add --with-job for periodic collection)\n'
fi

# --------------------------------------------------------------- 12. smoke
step "Smoke test"
if python3 "$REPO/bin/mibandd" device battery; then
    ok "band answered"
else
    warn "band did not answer yet — check the daemon log:"
    warn "  $ADB 'tail -20 /data/local/tmp/bledaemon.log'"
fi

step "Done"
cat <<EOF
Next:
  mibandd store stats --json   # one CLI for everything (backend + client)
  mibandd health collect       # download + decode recorded activity files
  mibandd health summary       # latest day's steps/HR/calories
  mibandd serve --foreground   # run the backend in the foreground
  mibandd commands             # list the command registry
  eval "$(mibandd completion bash)"   # tab-completion
  mibandd --help               # all commands

Notes:
  - The mibandd backend owns the one band session and starts on demand.
  - ADB runs on demand; keep Wireless Debugging on while using this repo.
  - The daemon does not survive reboot; re-run: ./install.sh --no-build
  - Mi Fitness must stay disabled while the daemon owns the link.
  - Auth key lives in notes/.authkey (never commit it).
EOF
