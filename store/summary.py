#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Derived from Gadgetbridge (https://gadgetbridge.org), AGPL-3.0-or-later:
# a Python translation of DailySummaryParser.
# See CONTRIBUTORS.md.
"""Daily-summary decoder for Xiaomi activity files (versions 3 and 4).

Ported from Gadgetbridge's `DailySummaryParser` (AGPLv3). The file body is

    [7-byte file id][1 pad byte][3-byte MSB-first validity bitmap][slots...]

Each slot always consumes its byte count; its value is only meaningful when
the matching bitmap bit is set, so absent fields are omitted rather than
stored as 0. Version 4 (Mi Band 9 Active) shares the version-3 slot table;
see `docs/ACTIVITY.md`.

Pure and band-free:
    from store.summary import parse_daily_summary, daily_metrics
"""
SUPPORTED_VERSIONS = (3, 4)

SLOT_NAMES = (
    "steps", "active_calories", None, "hr_resting", "hr_max", "hr_max_ts",
    "hr_min", "hr_min_ts", "hr_avg", "stress_avg", "stress_max", "stress_min",
    "standing", "calories", "recovery", None, "spo2_max", "spo2_max_ts",
    "spo2_min", "spo2_min_ts", "spo2_avg",
)
SLOT_SIZES = (4, 2, 1, 1, 1, 4, 1, 4, 1, 1, 1, 1, 3, 2, 2, 1, 1, 4, 1, 4, 1)

SUMMARY_KIND = "activity-daily"
SUMMARY_DETAIL = "summary"
DEFAULT_PREFIX = "daily."


def _valid(header, index):
    return (header[index // 8] & (1 << (7 - (index % 8)))) != 0


def parse_daily_summary(data):
    """Decode a v3/v4 daily-summary body into `{name: value}`, or None.

    `data` is the reassembled activity file (file id + pad + bitmap + slots +
    crc32). Only fields whose bitmap bit is set are returned; an unsupported
    version or a short buffer yields None.
    """
    if not data or len(data) < 11:
        return None
    if data[5] not in SUPPORTED_VERSIONS:
        return None
    payload = data[8:]                      # skip 7-byte id + 1 pad byte
    header = payload[:3]
    offset = 3
    fields = {}
    for index, size in enumerate(SLOT_SIZES):
        chunk = payload[offset:offset + size]
        offset += size
        name = SLOT_NAMES[index]
        if name is None or not _valid(header, index):
            continue
        fields[name] = int.from_bytes(chunk, "little")
    return fields


def daily_metrics(fields, prefix=DEFAULT_PREFIX):
    """Flatten a decoded summary into `{metric: value}` sample rows."""
    return {f"{prefix}{name}": value for name, value in fields.items()}
