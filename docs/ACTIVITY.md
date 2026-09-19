# Activity collector

How `mibandd health collect` fetches recorded activity files from the band, what works,
and what does not (yet). Ported from Gadgetbridge's `XiaomiActivityFileFetcher`
/ `XiaomiActivityFileId` (AGPLv3); see `contrib/gadgetbridge-issue-miband9active.md`.

## Flow (verified live, fw 2.3.151)

1. **List** — `8,1` (today) / `8,2` (past). The band replies with
   `Health{activityRequestFileIds = <blob>}`: a run of **7-byte ids**:

   ```
   [uint32 LE unix ts][int8 timezone][uint8 version][flags]
   flags = type<<7 | subtype<<2 | detail
   ```

   `type` 0 = activity, 1 = sports. For activity: subtype 0 daily, 3 sleep
   stages, 6 manual samples, 8 sleep. `detail`: 0 details, 1 summary, 2 gps.

2. **Request** — `8,3` with `Health{activityRequestFileIds = <7-byte id>}`.
   The band streams the file on the **Activity channel (5)** as numbered
   chunks: `[uint16 total][uint16 num][data...]`.

3. **Reassemble** — concatenate `data` for `num = 1..total`:

   ```
   [7-byte id][1 pad byte][payload][uint32 LE crc32]
   ```

   Verify the CRC32 (zlib) over everything before the trailer.

4. **Ack** — `8,5` with `Health{activitySyncAckFileIds = <7-byte id>}`.

Implemented in `client/activity.py`; orchestration in
`store.BandData.collect_activity()`; CLI in `bin/mibandd` (`health collect`,
`store blobs`, `health blob`).

## What works

- Daily **summary** files (subtype 0, detail 1, suffix like `1c0401`) download
  and CRC-verify, are stored in `activity_blobs`, and are acked.
- The id list and all request/ack framing.
- The **v4 daily-summary layout is known** and decodes to real values (see
  [Decoding](#decoding-v4-daily-summary) below); `collect` still stores raw
  bytes only.

## What does not (yet)

- **Details / sleep files** (detail 0, e.g. `1c0300`, `1c0420`) are *listed*
  by the band but it never streams them in response to `8,3` — verified across
  several ids, both request subtypes, and fresh sessions; no Activity-channel
  frames arrive. This matches Gadgetbridge marking the 9 Active experimental
  ("activity fetching is broken").
- **Details/sleep decoding** is not implemented (the band never streams those
  files). Daily summaries *are* decoded now: `mibandd health collect` (via
  `mibandd`) writes `daily.*` samples, and `miband-health decode` backfills
  existing blobs — see `store/summary.py`.

## Decoding (v4 daily summary)

The band emits daily summaries as **version 4**. Upstream Gadgetbridge added
v4 = Mi Band 9 Active support (Codeberg PR #6108, commit `4cf2b29896`), treating
v4 like v3: after the 7-byte id and the pad byte comes a **3-byte MSB-first
validity bitmap**, then a fixed slot table. Each slot always consumes its byte
count; the value is only real when its bit is set
(`header[i / 8] & (1 << (7 - (i % 8)))`).

| slot | field | bytes |
|---|---|---|
| 0 | steps | 4 (LE) |
| 1 | active calories | 2 |
| 2 | reserved | 1 |
| 3 | resting HR | 1 |
| 4 | max HR | 1 |
| 5 | max HR timestamp | 4 |
| 6 | min HR | 1 |
| 7 | min HR timestamp | 4 |
| 8 | avg HR | 1 |
| 9–11 | avg / max / min stress | 1 each |
| 12 | 24h standing bitmap | 3 |
| 13 | calories | 2 |
| 14 | recovery hours | 2 |
| 15 | reserved | 1 |
| 16–20 | SpO2 max / ts / min / ts / avg | 1 / 4 / 1 / 4 / 1 |

Source of truth: Gadgetbridge `XiaomiActivityParser` (`validData`) and
`DailySummaryParser` (`SLOTS`).

On this band the bitmap is `fa 89 00`, so only slots 0,1,2,3,4,6,8,12,15 are
present: steps, active calories, resting/max/min/avg HR, standing. Decoding the
stored blobs yields a coherent profile (resting HR 54, avg 68→73, max 94→105,
active calories 58→102 over one morning). Steps and the standing bitmap stayed
static across the sampled files while HR/calories rose, so treat those two as
unreliable until the details files can be fetched.

## Storage

- `activity_files` — the id index from `8,1` / `8,2`.
- `activity_blobs` — downloaded bodies: `file_ts`, `suffix`, `size`, `crc32`,
  `kind`, `detail`, `data` (BLOB), `fetched_at`.

## Scheduling (Android JobScheduler)

`collect` is one-shot; to run it periodically use Android's real JobScheduler
(plain background loops are killed when the screen locks):

```sh
mibandd schedule install --period-min 15   # register job id 8801
mibandd schedule status                     # pending job + wrapper path
mibandd schedule remove                     # cancel it
```

`install` writes `~/.miband/collect.sh` and registers it with
`termux-job-scheduler`; output is appended to `~/.miband/collect.log`.

`mibandd automate install` wraps this: it registers the same collector **and** a
watchdog job (id 8802), holds the Termux wake lock, and keeps the backend warm
with `serve --stay` so a scheduled run hits an already-authenticated session.

Notes:

- Android's minimum period is **15 minutes** (clamped up automatically).
- The job is `--persisted` and `--battery-not-low`; `termux-job-scheduler`
  adds an INTERNET constraint by default, so it will not fire fully offline.
- The wrapper runs `collect --timeout 6 --max-misses 2`: it grabs the daily
  summary, then stops after two unserved files — a ~15 s run instead of
  grinding through every listed-but-unserved details file.
- The shell-UID BLE daemon must be running; the job runs as the Termux UID and
  talks to it on `127.0.0.1:8477`. If the daemon is down, the run just logs an
  error and exits.
