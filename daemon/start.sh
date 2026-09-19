#!/system/bin/sh
# Start the shell-UID BLE daemon detached. Run it over ADB (adbwire; it must
# run as the `shell` UID), streaming this file to `sh`:
#
#   adbwire -p daemon/start.sh "sh -s -- <BAND_MAC> [PORT]"
#
# The MAC may also come from $MIBAND_MAC. Requires bledaemon.jar in
# /data/local/tmp (see daemon/build.sh --install).
MAC="${1:-$MIBAND_MAC}"
PORT="${2:-8477}"

if [ -z "$MAC" ]; then
    echo "error: no band MAC (pass as \$1 or set MIBAND_MAC)" >&2
    exit 1
fi

cd /data/local/tmp || exit 1

# stop any previous instance
for pid in $(ps -A 2>/dev/null | grep -i bledaemon | awk '{print $2}'); do
    kill "$pid" 2>/dev/null
done
rm -f bledaemon.log

ANDROID_DATA=/data/local/tmp ANDROID_ROOT=/system \
CLASSPATH=/data/local/tmp/bledaemon.jar \
setsid app_process /system/bin --nice-name=bledaemon BleDaemon "$MAC" "$PORT" \
    > bledaemon.log 2>&1 < /dev/null &

sleep 5
echo "--- log ---"
cat bledaemon.log
echo "--- ps ---"
ps -A 2>/dev/null | grep -i bledaemon | grep -v grep
echo "--- port $PORT ---"
netstat -ltn 2>/dev/null | grep "$PORT" || ss -ltn 2>/dev/null | grep "$PORT" \
    || echo "(no netstat/ss)"
