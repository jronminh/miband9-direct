#!/usr/bin/env python3
"""Catalogue of known Xiaomi commands (type, subtype) for the Mi Band 9 Active.

This is the single in-code source of truth for what we know how to say to the
band. `NAMED` in `commands.py` is the subset that can be sent with no payload;
everything here is still reachable via `--type/--subtype/--body`.

Status:
    live    verified live on the band (fw 2.3.151)
    reply   band replied to it and the reply was decoded
    set     verified state-changing write
    known   discovered (app / firmware / Gadgetbridge) but not tried here

Regenerate the docs with:  python -m client.registry > docs/COMMANDS.md
"""
import argparse
from dataclasses import dataclass

SERVICES = {
    1: "Auth",
    2: "System",
    4: "Watchface",
    5: "(unknown)",
    7: "Notification",
    8: "Health",
    10: "Weather",
    12: "Calendar",
    15: "Market",
    17: "Schedule",
    18: "Music",
    20: "Rpk (watch apps)",
    21: "Phonebook",
    22: "DataUpload",
}


@dataclass(frozen=True)
class CommandInfo:
    name: str
    type: int
    subtype: int
    description: str
    status: str = "known"       # live | reply | set | known
    payload: str = ""
    implemented: bool = False


COMMANDS = [
    # -- Auth (1) -----------------------------------------------------------
    CommandInfo("auth-common", 1, 1, "auth-related (app-internal)", "known"),
    CommandInfo("auth-user-id-v1", 1, 5, "send user id (legacy flow)", "known"),
    CommandInfo("auth-phone-nonce", 1, 26, "login step 1: phone nonce", "live",
                "PhoneNonce{nonce}", True),
    CommandInfo("auth-step3", 1, 27, "login step 3: confirm + devinfo", "live",
                "Auth.authStep3", True),

    # -- System (2) ---------------------------------------------------------
    CommandInfo("battery", 2, 1, "battery level + charging state", "live",
                "none", True),
    CommandInfo("info", 2, 2, "device info: serial, firmware, model", "live",
                "none", True),
    CommandInfo("clock", 2, 3, "set date/time/timezone/24h", "live",
                "system{clock{...}}", True),
    CommandInfo("firmware-install", 2, 5, "firmware install", "known"),
    CommandInfo("language", 2, 6, "band UI language", "live",
                'system{language{field1="en_us"}}', True),
    CommandInfo("camera-get", 2, 7, "camera remote state", "reply"),
    CommandInfo("camera-set", 2, 8, "camera remote control", "known"),
    CommandInfo("password-get", 2, 9, "lock password state", "reply"),
    CommandInfo("misc-setting-get", 2, 14, "misc settings (field 35)", "reply"),
    CommandInfo("misc-setting-set", 2, 15, "set misc setting", "known"),
    CommandInfo("find-phone", 2, 17, "ring the phone", "known", implemented=True),
    CommandInfo("findwatch", 2, 18, "vibrate the band", "live",
                "system{field4{field5: 0=start,1=stop}}", True),
    CommandInfo("password-set", 2, 21, "set lock password", "known"),
    CommandInfo("dnd", 2, 23, "do-not-disturb", "live",
                "system{dndStatus{status: 0=on,2=off}}", True),
    CommandInfo("display-items-get", 2, 29, "menu/display items list", "reply"),
    CommandInfo("display-items-set", 2, 30, "set display items", "known"),
    CommandInfo("workout-types-get", 2, 39, "workout types", "known"),
    CommandInfo("misc-setting-from-band", 2, 42, "misc setting pushed by band",
                "known"),
    CommandInfo("silent-mode-get", 2, 43, "silent mode state", "known"),
    CommandInfo("silent-mode-set-phone", 2, 44, "silent mode set from phone",
                "known"),
    CommandInfo("silent-mode-set-watch", 2, 45, "silent mode set from watch",
                "known"),
    CommandInfo("widget-screens-get", 2, 51, "widget screens", "known"),
    CommandInfo("widget-screens-set", 2, 52, "set widget screens", "known"),
    CommandInfo("widget-parts-get", 2, 53, "widget parts", "known"),
    CommandInfo("low-latency", 2, 67, "watchface low-latency mode", "known"),
    CommandInfo("state", 2, 78, "device state", "live", "none", True),
    CommandInfo("device-state", 2, 79, "device state (set/push)", "known"),
    CommandInfo("system-92", 2, 92, "system setting (unknown)", "known"),
    CommandInfo("accessibility", 2, 105, "accessibility data", "known"),

    # -- Watchface (4) ------------------------------------------------------
    CommandInfo("face-sync", 4, 0, "sync local watchface", "known"),
    CommandInfo("face-set-id", 4, 1, "set watchface id", "known"),
    CommandInfo("face-delete", 4, 2, "delete watchface", "known"),
    CommandInfo("face-remove-photo", 4, 3, "remove face photo", "known"),
    CommandInfo("face-preinstall", 4, 4, "pre-install watchface", "known"),
    CommandInfo("face-current", 4, 7, "get current watchface", "known"),
    CommandInfo("face-list", 4, 10, "list watchfaces", "known"),
    CommandInfo("face-request-edit", 4, 11, "request watchface edit", "known"),
    CommandInfo("face-get", 4, 14, "get a specified watchface", "known"),

    # -- Notification (7) ---------------------------------------------------
    CommandInfo("notify", 7, 0, "send a notification", "live",
                "notification{notification2{notification3{...}}}", True),
    CommandInfo("dismiss", 7, 1, "dismiss a notification", "live",
                "NotificationDismiss{NotificationId{id,package}}", True),
    CommandInfo("call-reject", 7, 2, "reject incoming call", "known"),
    CommandInfo("call-ignore", 7, 5, "ignore incoming call", "known"),
    CommandInfo("screen-on-get", 7, 6, "screen-on-on-notification state",
                "reply"),
    CommandInfo("screen-on-set", 7, 7, "screen-on-on-notification toggle",
                "set", "notification{screenOnOnNotifications=bool}", True),
    CommandInfo("open-on-phone", 7, 8, "open on phone", "known"),
    CommandInfo("canned-messages-get", 7, 9, "quick SMS replies", "reply"),
    CommandInfo("canned-messages-set", 7, 12, "set quick SMS replies", "known"),
    CommandInfo("call-reply-send", 7, 13, "call reply send", "known"),
    CommandInfo("call-reply-ack", 7, 14, "call reply ack", "known"),
    CommandInfo("notif-icon-request", 7, 15, "notification icon (reply)", "known"),
    CommandInfo("notif-icon-query", 7, 16, "band requests notif icon",
                "reply"),

    # -- Health (8) ---------------------------------------------------------
    CommandInfo("activity-files-today", 8, 1, "activity file ids (today)",
                "live", "Health{field5{field1:0}}", True),
    CommandInfo("activity-files-past", 8, 2, "activity file ids (past)", "live",
                "none", True),
    CommandInfo("activity-request", 8, 3, "request one activity file by id",
                "live", "Health{field2: file-id}", True),
    CommandInfo("activity-ack", 8, 5, "ack one activity file by id", "live",
                "Health{field3: file-id}", True),
    CommandInfo("spo2-config", 8, 8, "SpO2 config", "known", implemented=True),
    CommandInfo("heart-rate-config", 8, 10, "heart-rate config", "known", implemented=True),
    CommandInfo("stress-config", 8, 14, "stress config", "known", implemented=True),
    CommandInfo("vitality-reminder-get", 8, 21, "get vitality reminder", "known"),
    CommandInfo("vitality-reminder-set", 8, 22, "set vitality reminder", "known"),
    CommandInfo("vitality-score", 8, 35, "vitality score", "known", implemented=True),
    CommandInfo("goal-support-target", 8, 42, "update goal support target",
                "known"),
    CommandInfo("goal-current-target", 8, 43, "set current goal target", "known"),
    CommandInfo("health-52", 8, 52, "health (unknown)", "known"),
    CommandInfo("training-sync", 8, 87, "sync training plan", "known"),
    CommandInfo("training-stop", 8, 88, "stop training plan", "known"),
    CommandInfo("temperature-get", 8, 101, "get temperature unit", "known"),
    CommandInfo("temperature-set", 8, 102, "set temperature unit", "known"),

    # -- Weather (10) -------------------------------------------------------
    CommandInfo("weather-0", 10, 0, "weather request", "known"),
    CommandInfo("weather-1", 10, 1, "weather request", "known"),
    CommandInfo("weather-2", 10, 2, "weather request", "known"),
    CommandInfo("weather-3", 10, 3, "weather response", "known"),
    CommandInfo("weather-5", 10, 5, "weather response", "known"),
    CommandInfo("weather-6", 10, 6, "weather with AccuWeather location",
                "known", 'weather{#4{#1{#1 "accu:<id>"}}}'),

    # -- Calendar (12) / Schedule (17) -------------------------------------
    CommandInfo("calendar", 12, 0, "calendar event", "known"),
    CommandInfo("schedule-8", 17, 8, "schedule sync", "known"),

    # -- Music (18) ---------------------------------------------------------
    CommandInfo("music", 18, 1, "now-playing media info", "known",
                "music{#1{...}}", True),

    # -- Market (15) --------------------------------------------------------
    CommandInfo("market-send", 15, 5, "send market item to watch", "known"),

    # -- Rpk / watch apps (20) ---------------------------------------------
    CommandInfo("rpk-list", 20, 0, "list installed watch apps", "reply"),
    CommandInfo("rpk-prepare-install", 20, 1, "prepare app install", "known"),
    CommandInfo("rpk-uninstall", 20, 3, "uninstall watch app", "known"),
    CommandInfo("rpk-launch", 20, 4, "launch watch app", "known"),
    CommandInfo("rpk-sync-status", 20, 7, "sync phone-app status", "known"),
    CommandInfo("rpk-send-message", 20, 8, "send phone message to app", "known"),
    CommandInfo("rpk-wechat-license", 20, 11, "send WeChat license", "known"),
    CommandInfo("rpk-wear-app-status", 20, 21, "get wear-app status", "known"),

    # -- Phonebook (21) / DataUpload (22) ----------------------------------
    CommandInfo("phonebook", 21, 0, "phonebook", "known"),
    CommandInfo("data-upload", 22, 0, "file upload (watchface/icon/RPK)",
                "known", "DataUploadRequest{type,md5,size}"),

    # -- Unknown service 5 --------------------------------------------------
    CommandInfo("type5-10", 5, 10, "unknown (type 5)", "known"),
]

_ORDER = list(SERVICES)


def by_service():
    """Return {service_name: [CommandInfo, ...]} in catalogue order."""
    out = {}
    for c in COMMANDS:
        out.setdefault(SERVICES.get(c.type, str(c.type)), []).append(c)
    return out


def to_markdown():
    lines = [
        "# Mi Band 9 command catalogue",
        "",
        "Generated from `client/registry.py` (`python -m client.registry`).",
        "",
        "Status: **live** verified on the band (fw 2.3.151) · **set** verified "
        "state-changing write · **reply** band replied and it was decoded · "
        "**known** discovered (app / firmware / Gadgetbridge), not tried here. "
        "`in code` marks commands reachable by name from `client/commands.py`.",
        "",
    ]
    grouped = by_service()
    for type_id in _ORDER:
        name = SERVICES[type_id]
        items = grouped.get(name)
        if not items:
            continue
        lines += [f"## {name} (type {type_id})", "",
                  "| name | T,S | description | payload | status | in code |",
                  "|---|---|---|---|---|---|"]
        for c in items:
            lines.append(
                f"| `{c.name}` | {c.type},{c.subtype} | {c.description} | "
                f"{c.payload or ''} | {c.status} | "
                f"{'yes' if c.implemented else ''} |")
        lines.append("")
    return "\n".join(lines)


def _main():
    ap = argparse.ArgumentParser(description="Mi Band command catalogue")
    ap.add_argument("--markdown", action="store_true",
                    help="emit docs/COMMANDS.md content")
    args = ap.parse_args()
    if args.markdown:
        print(to_markdown())
        return
    for c in COMMANDS:
        print(f"{c.type:>2},{c.subtype:<4} {c.status:<6} {c.name:<24} "
              f"{c.description}")


if __name__ == "__main__":
    _main()
