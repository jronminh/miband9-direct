#!/data/data/com.termux/files/usr/bin/bash
# Build the BLE daemon dex. With --install, push it to /data/local/tmp over ADB.
set -e
cd "$(dirname "$0")/.." || exit 1

rm -rf stubs/build daemon/build
mkdir -p stubs/build daemon/build

javac -d stubs/build $(find stubs/src -name '*.java')
(cd stubs/build && jar cf ../stub.jar .)

javac -cp stubs/stub.jar -d daemon/build daemon/src/BleDaemon.java
d8 --min-api 23 --lib stubs/stub.jar \
    --output daemon/build/bledaemon.jar daemon/build/BleDaemon*.class

echo "built daemon/build/bledaemon.jar"

if [ "${1:-}" = "--install" ]; then
    # Push over ADB (adbwire). Override the client with $ADB (path or name).
    ADB="${ADB:-adbwire}"
    ADB_EXTRA=()
    [ -n "${MIBAND_ADB_HOST:-}" ] && ADB_EXTRA=(-s "$MIBAND_ADB_HOST")
    command -v "$ADB" >/dev/null 2>&1 || [ -x "$ADB" ] \
        || { echo "no ADB client '$ADB' (build tools/adbwire, or set \$ADB)" >&2; exit 1; }
    "$ADB" "${ADB_EXTRA[@]}" -p daemon/build/bledaemon.jar \
        'cat > /data/local/tmp/bledaemon.jar'
    echo "installed to /data/local/tmp/bledaemon.jar"
fi
