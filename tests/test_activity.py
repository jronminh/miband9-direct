#!/usr/bin/env python3
"""Offline tests for the activity file transfer codec (client/activity.py).

No band or daemon: covers the 7-byte file-id codec, chunk reassembly, and CRC
verification against hand-built frames. Run with:

    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from client.activity import (ActivityFileId, ChunkAssembler, verify,
                             SUBTYPE_NAMES)


def _file_id(ts, tz, version, type_, subtype, detail):
    flags = (type_ << 7) | (subtype << 2) | detail
    return ts.to_bytes(4, "little") + bytes([tz & 0xFF, version, flags])


class TestActivityFileId(unittest.TestCase):
    def test_round_trip_daily_details(self):
        raw = _file_id(1789689600, 0x1C, 0x03, 0, 0x00, 0)
        fid = ActivityFileId.from_bytes(raw)
        self.assertEqual(fid.timestamp, 1789689600)
        self.assertEqual(fid.timezone, 0x1C)
        self.assertEqual(fid.version, 3)
        self.assertEqual((fid.type, fid.subtype, fid.detail_type), (0, 0, 0))
        self.assertEqual(fid.to_bytes(), raw)

    def test_round_trip_daily_summary(self):
        raw = _file_id(1789689600, 0x1C, 0x04, 0, 0x00, 1)
        fid = ActivityFileId.from_bytes(raw)
        self.assertEqual(fid.kind, "activity-daily")
        self.assertEqual(fid.detail, "summary")
        self.assertEqual(fid.to_bytes(), raw)

    def test_sports_type_and_subtype(self):
        raw = _file_id(1700000000, 0x1C, 1, 1, 0x01, 2)
        fid = ActivityFileId.from_bytes(raw)
        self.assertEqual(fid.type, 1)
        self.assertEqual(fid.subtype, 0x01)
        self.assertEqual(fid.detail, "gps")
        self.assertEqual(fid.to_bytes(), raw)

    def test_sleep_stages_known_name(self):
        raw = _file_id(1700000000, 0, 1, 0, 0x03, 0)
        self.assertEqual(ActivityFileId.from_bytes(raw).kind, "sleep-stages")

    def test_negative_timezone_round_trips(self):
        raw = _file_id(1700000000, 0xF4, 1, 0, 0, 0)  # -12 in 15-min blocks
        fid = ActivityFileId.from_bytes(raw)
        self.assertEqual(fid.timezone, -12)
        self.assertEqual(fid.to_bytes(), raw)

    def test_wrong_length_rejected(self):
        with self.assertRaises(ValueError):
            ActivityFileId.from_bytes(b"\x00" * 6)

    def test_suffix_is_last_three_bytes(self):
        raw = _file_id(1700000000, 0x1C, 0x03, 0, 0, 0)
        self.assertEqual(ActivityFileId.from_bytes(raw).suffix, "1c0300")


class TestChunkAssembler(unittest.TestCase):
    @staticmethod
    def _chunk(total, num, data):
        return total.to_bytes(2, "little") + num.to_bytes(2, "little") + data

    def test_two_chunks(self):
        a = ChunkAssembler()
        self.assertIsNone(a.feed(self._chunk(2, 1, b"AAA")))
        self.assertEqual(a.feed(self._chunk(2, 2, b"BBB")), b"AAABBB")

    def test_single_chunk(self):
        a = ChunkAssembler()
        self.assertEqual(a.feed(self._chunk(1, 1, b"xyz")), b"xyz")

    def test_num_one_resets_buffer(self):
        a = ChunkAssembler()
        a.feed(self._chunk(2, 1, b"old"))
        self.assertEqual(a.feed(self._chunk(2, 1, b"new")), None)
        self.assertEqual(a.feed(self._chunk(2, 2, b"!")), b"new!")

    def test_short_chunk_ignored(self):
        self.assertIsNone(ChunkAssembler().feed(b"\x00\x01"))


class TestVerify(unittest.TestCase):
    def _file(self, payload, crc=None):
        body = payload + (crc if crc is not None
                          else (zlib.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "little"))
        return body

    def test_valid_file(self):
        payload = _file_id(1700000000, 0x1C, 3, 0, 0, 0) + b"\x00" + b"PAYLOAD"
        data = self._file(payload)
        out = verify(data)
        self.assertEqual(out["payload"], b"PAYLOAD")
        self.assertEqual(out["file_id"].timestamp, 1700000000)
        self.assertEqual(out["raw"], data)

    def test_bad_crc_raises(self):
        payload = _file_id(1700000000, 0x1C, 3, 0, 0, 0) + b"\x00" + b"PAYLOAD"
        data = self._file(payload, crc=b"\x00\x00\x00\x00")
        with self.assertRaises(ValueError):
            verify(data)

    def test_too_short_raises(self):
        with self.assertRaises(ValueError):
            verify(b"\x00" * 8)

    def test_known_subtype_names(self):
        self.assertIn((0, 0x00), SUBTYPE_NAMES)


if __name__ == "__main__":
    unittest.main()
