#!/usr/bin/env python3
"""Regression tests for the pure parts of the client/store packages.

No band and no daemon are needed: these cover the codecs, framing, parsers,
and DB transaction behaviour. Run with:

    python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import client as c
from client import commands as cmd
from client import shell
from store.db import Database
from store.data import parse_battery, parse_info, parse_activity_files


class TestCrc(unittest.TestCase):
    def test_check_value(self):
        self.assertEqual(c.crc16_arc(b"123456789"), 0xBB3D)

    def test_empty(self):
        self.assertEqual(c.crc16_arc(b""), 0)


class TestProtobuf(unittest.TestCase):
    def test_varint_round_trip(self):
        buf = c.pb_varint(1, 300) + c.pb_bytes(2, b"hi")
        self.assertEqual(c.pb_get(buf, 1, 0), 300)
        self.assertEqual(c.pb_get(buf, 2, 2), b"hi")

    def test_truncated_varint_does_not_raise(self):
        self.assertEqual(list(c.pb_read(b"\x08\x80")), [])

    def test_length_overrun_stops(self):
        self.assertEqual(list(c.pb_read(b"\x0a\x7f" + b"A" * 3)), [])

    def test_bad_wiretype_stops(self):
        self.assertEqual(list(c.pb_read(b"\x3f")), [])


class TestFraming(unittest.TestCase):
    # A real band->phone DATA frame captured from Mi Fitness logcat.
    CAPTURED = bytes.fromhex(
        "A5A503001100B73B01010801101B1A098A0206080110BCC211")

    def test_parses_captured_frame(self):
        ptype, seq, payload = c.parse_frame(self.CAPTURED)
        self.assertEqual(ptype, c.PT_DATA)
        self.assertEqual(seq, 0)
        self.assertEqual(len(payload), 0x11)

    def test_rejects_bad_crc(self):
        bad = self.CAPTURED[:6] + b"\x00\x00" + self.CAPTURED[8:]
        self.assertIsNone(c.parse_frame(bad))

    def test_rejects_length_overrun(self):
        bad = self.CAPTURED[:4] + (999).to_bytes(2, "little") + self.CAPTURED[6:]
        self.assertIsNone(c.parse_frame(bad))

    def test_rejects_short_and_bad_preamble(self):
        self.assertIsNone(c.parse_frame(b"A5A5"))
        self.assertIsNone(c.parse_frame(b"\x00\x00" + b"\x00" * 8))

    def test_ack_frame_validates(self):
        # ACK frames have an empty payload and CRC 0.
        ack = c.PREAMBLE + bytes([c.PT_ACK, 0]) + b"\x00\x00\x00\x00"
        self.assertIsNotNone(c.parse_frame(ack))


class TestParsers(unittest.TestCase):
    def test_parse_battery(self):
        battery = c.pb_varint(1, 85) + c.pb_varint(2, 2)
        body = c.pb_bytes(4, c.pb_bytes(2, c.pb_bytes(1, battery)))
        r = c.Response(2, 1, 1, False, body)
        self.assertEqual(parse_battery([r]), {"level": 85, "state": 2})

    def test_parse_info(self):
        di = (c.pb_bytes(1, b"SN-1") + c.pb_bytes(2, b"FW-2")
              + c.pb_bytes(4, b"MD-4"))
        body = c.pb_bytes(4, c.pb_bytes(3, di))
        r = c.Response(2, 2, 1, False, body)
        self.assertEqual(parse_info([r]),
                         {"serial": "SN-1", "firmware": "FW-2", "model": "MD-4"})

    def test_parse_activity_files(self):
        entry = (1700000000).to_bytes(4, "little") + bytes.fromhex("aabbcc")
        body = c.pb_bytes(10, c.pb_bytes(2, entry))
        r = c.Response(8, 1, 1, False, body)
        out = parse_activity_files([r])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["ts"], 1700000000)
        self.assertEqual(out[0]["suffix"], "aabbcc")

    def test_parse_battery_no_match(self):
        self.assertIsNone(parse_battery([]))


class TestSessionParseCommand(unittest.TestCase):
    def test_named(self):
        self.assertEqual(shell.parse_command("battery"), ("battery", 2, 1, b""))

    def test_typed(self):
        label, t, s, body = shell.parse_command("type:2:18:aabb")
        self.assertEqual((t, s, body), (2, 18, b"\xaa\xbb"))

    def test_blank_is_none(self):
        self.assertIsNone(shell.parse_command("   "))

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            shell.parse_command("nonsense")
        with self.assertRaises(ValueError):
            shell.parse_command("type:x:y")


class TestRegistry(unittest.TestCase):
    def test_unique_names(self):
        from client import registry
        names = [c.name for c in registry.COMMANDS]
        self.assertEqual(len(names), len(set(names)))

    def test_entries_well_formed(self):
        from client import registry
        for c in registry.COMMANDS:
            self.assertIn(c.status, ("live", "reply", "set", "known"))
            self.assertIn(c.type, registry.SERVICES)

    def test_markdown_renders(self):
        from client import registry
        md = registry.to_markdown()
        self.assertIn("battery", md)
        self.assertIn("| `notify` |", md)


class TestCapture(unittest.TestCase):
    def test_tx_recorded(self):
        s = c.Session(_FakeDaemon([]), b"k" * 16)
        s.frame(c.PT_DATA, b"\x01\x01hello")
        s.ack(0)
        frames = list(s.capture)
        self.assertEqual([f.direction for f in frames], ["tx", "tx"])
        self.assertEqual(frames[0].ptype, c.PT_DATA)
        self.assertEqual(frames[1].ptype, c.PT_ACK)

    def test_rx_recorded(self):
        builder = c.Session(_FakeDaemon([]), b"k" * 16)
        frame = builder.frame(c.PT_DATA, bytes([c.CH_PROTOBUF, c.OP_PLAIN])
                              + c.command(2, 1))
        d = _FakeDaemon(["NOTIFY " + c.UUID_RX + " " + frame.hex()])
        sess = c.Session(d, b"k" * 16)
        c.read_frames(d, sess, time.time() + 0.3, expect=(2, 1))
        rx = [f for f in sess.capture if f.direction == "rx"]
        self.assertTrue(rx)
        self.assertEqual((rx[0].type, rx[0].subtype), (2, 1))
        self.assertTrue(any(f.direction == "tx" and f.ptype == c.PT_ACK
                            for f in sess.capture))

    def test_capture_disabled(self):
        s = c.Session(_FakeDaemon([]), b"k" * 16, capture=False)
        s.frame(c.PT_DATA, b"x")
        self.assertEqual(len(s.capture), 0)

    def test_capture_maxlen(self):
        s = c.Session(_FakeDaemon([]), b"k" * 16, capture_maxlen=3)
        for _ in range(5):
            s.ack(0)
        self.assertEqual(len(s.capture), 3)


class TestLogging(unittest.TestCase):
    def test_configure_is_idempotent(self):
        import logging
        root = logging.getLogger("client")
        try:
            c.configure(logging.INFO)
            c.configure(logging.DEBUG)
            streams = [h for h in root.handlers
                       if isinstance(h, logging.StreamHandler)]
            self.assertEqual(len(streams), 1)
            self.assertEqual(root.level, logging.DEBUG)
        finally:
            for h in list(root.handlers):
                if isinstance(h, logging.StreamHandler):
                    root.removeHandler(h)
            root.setLevel(logging.NOTSET)

    def test_parse_frame_logs_reject_reason(self):
        with self.assertLogs("client.protocol.framing", level="DEBUG") as cm:
            self.assertIsNone(c.parse_frame(b"\x00\x00" + b"\x00" * 8))
        self.assertTrue(any("reject frame" in m for m in cm.output))


class _FakeDaemon:
    def __init__(self, lines):
        self.lines = list(lines)
        self.acks = []

    def poll(self, timeout=5):
        if self.lines:
            return self.lines.pop(0)
        raise TimeoutError("empty")

    def write_reliable(self, uuid, data, **kw):
        self.acks.append(data)
        return True


class TestReadFramesFilter(unittest.TestCase):
    def _frame_line(self, body):
        s = c.Session(_FakeDaemon([]), b"k" * 16)
        return ("NOTIFY " + c.UUID_RX + " "
                + s.frame(c.PT_DATA, bytes([c.CH_PROTOBUF, c.OP_PLAIN]) + body).hex())

    def test_filters_unrelated_frames(self):
        async_push = self._frame_line(c.command(7, 0))
        wanted = self._frame_line(c.command(2, 1))
        d = _FakeDaemon([async_push, wanted])
        sess = c.Session(d, b"k" * 16)
        out = c.read_frames(d, sess, time.time() + 0.3, expect=(2, 1))
        self.assertEqual([(r.type, r.subtype) for r in out], [(2, 1)])
        # Both frames must still be acked.
        self.assertEqual(len(d.acks), 2)

    def test_falls_back_when_nothing_matches(self):
        only_push = self._frame_line(c.command(7, 0))
        d = _FakeDaemon([only_push])
        sess = c.Session(d, b"k" * 16)
        out = c.read_frames(d, sess, time.time() + 0.2, expect=(2, 1))
        self.assertEqual([(r.type, r.subtype) for r in out], [(7, 0)])


class _BadResponse(c.Response):
    def to_dict(self):
        raise RuntimeError("decode blew up")


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "t.db")
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close()

    def test_record_rolls_back_on_failure(self):
        good = c.Response(2, 1, 1, False, c.pb_varint(1, 85))
        bad = _BadResponse(2, 1, 1, False, b"")
        with self.assertRaises(RuntimeError):
            self.db.record("battery", [good, bad], 2, 1)
        # The failed exchange must not survive, even after a later commit.
        self.db.sample("probe", value=1)
        self.assertEqual(self.db.stats()["exchanges"], 0)
        self.assertEqual(self.db.stats()["replies"], 0)

    def test_record_success(self):
        good = c.Response(2, 1, 1, False, c.pb_varint(1, 85))
        self.db.record("battery", [good], 2, 1)
        self.assertEqual(self.db.stats()["exchanges"], 1)
        self.assertEqual(self.db.stats()["replies"], 1)


class TestLoadKey(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(cmd.load_key("00" * 16), b"\x00" * 16)

    def test_bad_length(self):
        with self.assertRaises(ValueError):
            cmd.load_key("aabb")

    def test_bad_hex(self):
        with self.assertRaises(ValueError):
            cmd.load_key("zz" * 16)


if __name__ == "__main__":
    unittest.main()
