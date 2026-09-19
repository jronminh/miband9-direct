#!/system/bin/sh
# Stop the shell-UID BLE daemon. Run over ADB (adbwire):
#
#   adbwire -p daemon/stop.sh sh
for pid in $(ps -A 2>/dev/null | grep -i bledaemon | awk '{print $2}'); do
    kill "$pid" 2>/dev/null && echo "killed bledaemon pid $pid"
done
echo "done"
