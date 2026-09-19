#!/usr/bin/env python3
"""Phone-notification -> Mi Band forwarder (prototype).

Termux runs as `untrusted_app` and cannot read Android notifications; the
`shell` UID can. This script captures active notifications over the adb
bridge (`dsh -c 'dumpsys notification --noredact'`), parses the
NotificationRecord blocks, dedups/filters them, and pushes new ones to the
band through `mibandd notify notify`.

Prototype scope: capture + parse + dedup + forward. No loop supervisor yet.

Usage:
    python3 tools/notify-forward.py --once --dry-run
    python3 tools/notify-forward.py --loop --interval 4
    python3 tools/notify-forward.py --source dump.txt --once --dry-run
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

STATE_PATH = os.path.expanduser("~/.miband/notify-seen.json")
_STOP = threading.Event()

REC_START = re.compile(r"^    NotificationRecord\(", re.M)
FIELD = {
    "pkg": re.compile(r"pkg=(\S+)"),
    "id": re.compile(r" id=(-?\d+)"),
    "tag": re.compile(r" tag=(\S+)"),
    "importance": re.compile(r"importance=(\d+)"),
    "flags": re.compile(r"flags=(\S+)"),
    "category": re.compile(r"category=(\S+)"),
}

DEFAULT_DENY = {
    "com.android.systemui",
    "com.termux",
    "android",
}

APP_LABELS = {
    "com.facebook.orca": "Messenger",
    "com.zing.zalo": "Zalo",
    "net.thunderbird.android": "Thunderbird",
    "com.viettel.btl86": "Viettel",
    "com.viettel.appviettel": "Viettel",
    "com.mbmobile": "MB Bank",
    "com.sec.android.app.clockpackage": "Clock",
    "com.windyty.android": "Windy",
    "com.termux.api": "Termux:API",
    "com.google.android.apps.youtube.music": "YT Music",
}


def _value(chunk: str, name: str) -> str:
    """Extract an `android.*=Type (value)` field, balancing parens."""
    m = re.search(re.escape(name) + r"=\w+ \(", chunk)
    if not m:
        return ""
    start = m.end()
    depth = 1
    i = start
    while i < len(chunk) and depth:
        if chunk[i] == "(":
            depth += 1
        elif chunk[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return chunk[start:i].strip()


def parse(text: str) -> list[dict]:
    """Split a dumpsys notification dump into notification dicts."""
    starts = [m.start() for m in REC_START.finditer(text)]
    out = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(text)
        chunk = text[start:end]
        header = chunk.splitlines()[0]
        rec = {}
        for key, rx in FIELD.items():
            m = rx.search(header)
            rec[key] = m.group(1) if m else ""
        title = _value(chunk, "android.title") or _value(chunk, "android.title.big")
        body = _value(chunk, "android.text") or _value(chunk, "android.text.big")
        rec["title"] = title
        rec["text"] = body
        rec["key"] = f"{rec['pkg']}|{rec['id']}|{rec['tag']}"
        out.append(rec)
    return out


def label_for(pkg: str) -> str:
    """App label: known map first, else last package segment."""
    if pkg in APP_LABELS:
        return APP_LABELS[pkg]
    last = pkg.rsplit(".", 1)[-1]
    if last in ("android", "app"):
        parts = pkg.split(".")
        last = parts[-2] if len(parts) > 1 else last
    return last.replace("_", " ").title() or pkg


def should_forward(rec: dict, args, deny: set[str], allow: set[str]) -> tuple[bool, str]:
    pkg = rec["pkg"]
    if not pkg:
        return False, "no-pkg"
    if allow and pkg not in allow:
        return False, "not-allowlisted"
    if pkg in deny:
        return False, "denylisted"
    try:
        if int(rec.get("importance") or 0) < args.min_importance:
            return False, "low-importance"
    except ValueError:
        pass
    flags = rec.get("flags") or ""
    if "GROUP_SUMMARY" in flags:
        return False, "group-summary"
    if "ONGOING" in flags:
        return False, "ongoing"
    if rec.get("category") == "transport":
        return False, "media"
    if not rec["title"] and not rec["text"]:
        return False, "empty"
    return True, ""


def content_hash(rec: dict) -> str:
    blob = f"{rec['title']}\x00{rec['text']}".encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def load_state() -> dict:
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE_PATH)


def capture(args) -> str:
    if args.source:
        with open(args.source) as fh:
            return fh.read()
    # dsh has no shebang (bash falls back to running it as a script, but
    # execve does not), so run it through bash explicitly.
    dsh = shutil.which("dsh") or "dsh"
    proc = subprocess.run(
        ["bash", dsh, "-c", "dumpsys notification --noredact"],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"dsh failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def forward(rec: dict, args) -> None:
    cmd = [
        "mibandd", "notify", "notify",
        "--title", rec["title"] or label_for(rec["pkg"]),
        "--text", rec["text"],
        "--app", label_for(rec["pkg"]),
        "--pkg", rec["pkg"],
        "--id", rec["id"] or "1",
    ]
    if args.dry_run:
        print("DRY  " + " ".join(cmd[1:]))
        return
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    status = "OK " if proc.returncode == 0 else f"ERR({proc.returncode}) "
    print(status + rec["pkg"] + " :: " + (rec["title"] or rec["text"])[:60])
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)


def scan_once(args, state: dict, last_sent: dict, deny: set[str], allow: set[str]) -> int:
    text = capture(args)
    records = parse(text)
    live_keys = {r["key"] for r in records}

    # Drop vanished keys so a re-post after dismissal fires again.
    for stale in [k for k in state if k not in live_keys]:
        state.pop(stale, None)

    sent = 0
    now = time.time()
    for rec in records:
        key = rec["key"]
        h = content_hash(rec)
        if state.get(key) == h:
            continue
        ok, reason = should_forward(rec, args, deny, allow)
        state[key] = h
        if not ok:
            if args.verbose:
                print(f"skip {rec['pkg']} ({reason})")
            continue
        gap = now - last_sent.get(rec["pkg"], 0)
        if gap < args.rate:
            if args.verbose:
                print(f"skip {rec['pkg']} (rate {gap:.1f}s < {args.rate}s)")
            continue
        forward(rec, args)
        last_sent[rec["pkg"]] = now
        sent += 1
    return sent


def _claim_pidfile(path: str | None) -> None:
    """Refuse to start twice; write our pid and clean up on exit."""
    if not path:
        return
    path = os.path.expanduser(path)
    if os.path.exists(path):
        try:
            old = int(open(path).read().strip())
            os.kill(old, 0)
            if old != os.getpid():
                raise SystemExit(f"already running (pid {old})")
        except (OSError, ValueError):
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(str(os.getpid()))

    def _cleanup():
        try:
            if int(open(path).read().strip()) == os.getpid():
                os.remove(path)
        except (OSError, ValueError):
            pass

    atexit.register(_cleanup)


def _on_signal(signum, frame):
    _STOP.set()


def main() -> int:
    global STATE_PATH
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="single scan then exit")
    ap.add_argument("--loop", action="store_true", help="poll continuously")
    ap.add_argument("--interval", type=float, default=4.0, help="poll seconds")
    ap.add_argument("--dry-run", action="store_true", help="print, do not send")
    ap.add_argument("--source", help="read a saved dumpsys dump instead of dsh")
    ap.add_argument("--state", default=STATE_PATH, help="seen-state JSON path")
    ap.add_argument("--pidfile", help="single-instance lock file (for the loop)")
    ap.add_argument("--allow", default="", help="comma-separated pkg allowlist")
    ap.add_argument("--deny", default="", help="comma-separated extra denylist")
    ap.add_argument("--min-importance", type=int, default=3)
    ap.add_argument("--rate", type=float, default=20.0, help="per-pkg seconds")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not (args.once or args.loop or args.source):
        ap.error("choose --once, --loop or --source")
    if args.source:
        args.once = True

    STATE_PATH = os.path.expanduser(args.state)
    state = load_state()
    allow = {p.strip() for p in args.allow.split(",") if p.strip()}
    deny = DEFAULT_DENY | {p.strip() for p in args.deny.split(",") if p.strip()}
    last_sent: dict[str, float] = {}

    if args.once:
        try:
            n = scan_once(args, state, last_sent, deny, allow)
        except RuntimeError as exc:
            sys.stderr.write(str(exc) + "\n")
            return 1
        if not args.dry_run:
            save_state(state)
        print(f"forwarded {n}")
        return 0

    _claim_pidfile(args.pidfile)
    signal.signal(signal.SIGTERM, _on_signal)
    print(f"watching notifications every {args.interval}s (ctrl-c to stop)",
          flush=True)
    try:
        while not _STOP.is_set():
            try:
                scan_once(args, state, last_sent, deny, allow)
            except RuntimeError as exc:
                print(f"scan error: {exc}", flush=True)
            if not args.dry_run:
                save_state(state)
            if _STOP.wait(args.interval):
                break
    except KeyboardInterrupt:
        pass
    finally:
        if not args.dry_run:
            save_state(state)
        print("stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
