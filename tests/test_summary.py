#!/usr/bin/env python3
"""Tests for the daily-summary decoder and the samples date column.

No band and no daemon. Run with: python -m unittest discover -s tests -v
"""
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from store.db import Database
from store.summary import SLOT_SIZES, daily_metrics, parse_daily_summary


def daily_payload(values, version=4, bitmap=None):
    """Build a minimal v3/v4 daily-summary body for the given slot values."""
    if bitmap is None:
        header = bytearray(3)
        for index in values:
            header[index // 8] |= 1 << (7 - (index % 8))
    else:
        header = bytearray(bitmap)
    body = bytearray()
    for index, size in enumerate(SLOT_SIZES):
        body += int(values.get(index, 0)).to_bytes(size, "little")
    file_id = (1789784085).to_bytes(4, "little") + bytes([28, version, 0x01])
    return bytes(file_id) + b"\x00" + bytes(header) + bytes(body) + b"\x00" * 4


SAMPLE_VALUES = {0: 528, 1: 58, 3: 54, 4: 94, 6: 55, 8: 68, 12: 32}


class TestParseDailySummary(unittest.TestCase):
    def test_decodes_present_fields(self):
        fields = parse_daily_summary(daily_payload(SAMPLE_VALUES))
        self.assertEqual(fields, {
            "steps": 528, "active_calories": 58, "hr_resting": 54,
            "hr_max": 94, "hr_min": 55, "hr_avg": 68, "standing": 32})

    def test_bitmap_gates_fields(self):
        fields = parse_daily_summary(
            daily_payload({0: 123, 3: 99}, bitmap=(0x80, 0x00, 0x00)))
        self.assertEqual(fields, {"steps": 123})

    def test_unsupported_version(self):
        self.assertIsNone(
            parse_daily_summary(daily_payload(SAMPLE_VALUES, version=5)))

    def test_short_buffer(self):
        self.assertIsNone(parse_daily_summary(b"\x00\x01"))

    def test_daily_metrics_prefix(self):
        self.assertEqual(daily_metrics({"steps": 1, "hr_avg": 70}),
                         {"daily.steps": 1, "daily.hr_avg": 70})


class TestSamplesDate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "t.db"))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_sample_sets_date(self):
        self.db.sample("battery.level", value=82, ts=1789784085)
        row = self.db.latest("battery.level")
        self.assertIsNotNone(row["date"])
        self.assertEqual(len(row["date"]), 19)

    def test_clear_and_samples_at(self):
        ts = 1789784085
        self.db.sample("daily.steps", value=1, ts=ts)
        self.db.sample("daily.hr_avg", value=70, ts=ts)
        self.db.sample("daily.steps", value=2, ts=ts + 86400)
        self.assertEqual(len(self.db.samples_at(ts, prefix="daily.")), 2)
        self.db.clear_samples(ts, prefix="daily.")
        self.assertEqual(len(self.db.samples_at(ts, prefix="daily.")), 0)
        self.assertEqual(len(self.db.samples(prefix="daily.")), 1)


class TestMigration(unittest.TestCase):
    def test_date_column_added_and_backfilled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            old = sqlite3.connect(path)
            old.execute(
                "CREATE TABLE samples (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts REAL NOT NULL, metric TEXT NOT NULL, value REAL, text TEXT, "
                "raw TEXT)")
            old.execute("INSERT INTO samples(ts, metric, value) VALUES(?,?,?)",
                        (1789784085.0, "battery.level", 82))
            old.commit()
            old.close()

            db = Database(path)
            row = db.latest("battery.level")
            self.assertEqual(row["value"], 82)
            self.assertIsNotNone(row["date"])
            db.close()


if __name__ == "__main__":
    unittest.main()
