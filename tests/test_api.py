#!/usr/bin/env python3
"""Offline tests for the `api` package.

No band and no daemon: `open_session` / `send_command` are monkeypatched so the
lifecycle, error mapping, and command building can be exercised directly. Run
with:

    python -m unittest discover -s tests -v
"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import api
from api import (MiBand, BandError, DaemonError, AuthError, CommandError,
                 ConnectionLost, first, to_dicts, registry, read_events)
from client import (Session, UUID_RX, PT_DATA, CH_PROTOBUF, OP_PLAIN, command)
from client.protocol import Response, pb_bytes, pb_varint


class _FakeDaemon:
    def __init__(self, lines=()):
        self.lines = list(lines)
        self.closed = False

    def close(self):
        self.closed = True

    def poll(self, timeout=5):
        if self.lines:
            return self.lines.pop(0)
        raise TimeoutError("empty")

    def write_reliable(self, uuid, data, **kw):
        return True


class TestErrors(unittest.TestCase):
    def test_every_error_subclasses_band_error(self):
        for exc in (DaemonError, AuthError, api.NotConnectedError,
                    ConnectionLost, CommandError):
            self.assertTrue(issubclass(exc, BandError))


class TestParseHelpers(unittest.TestCase):
    def test_first_matches_type_and_subtype(self):
        r = Response(2, 1, 1, False, b"")
        self.assertIs(first([r], 2, 1), r)
        self.assertIsNone(first([r], 2, 2))
        self.assertIsNone(first([], 2, 1))

    def test_to_dicts(self):
        r = Response(2, 1, 1, False, pb_varint(1, 85))
        out = to_dicts([r])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], 2)

    def test_reexports_store_parsers(self):
        self.assertIs(api.parse_battery, __import__(
            "store.data", fromlist=["parse_battery"]).parse_battery)


class TestMiBandLifecycle(unittest.TestCase):
    def test_connect_maps_oserror_to_daemon_error(self):
        band = MiBand()
        with mock.patch("api.band.open_session", side_effect=OSError("refused")):
            with self.assertRaises(DaemonError):
                band.connect()
        self.assertFalse(band.connected)

    def test_connect_maps_connection_error_to_auth_error(self):
        band = MiBand()
        with mock.patch("api.band.open_session",
                        side_effect=ConnectionError("rejected")):
            with self.assertRaises(AuthError):
                band.connect()
        self.assertFalse(band.connected)

    def test_context_manager_closes(self):
        band = MiBand()
        d = _FakeDaemon()
        with mock.patch("api.band.open_session", return_value=(d, object())):
            with band as entered:
                self.assertIs(entered, band)
                self.assertTrue(band.connected)
        self.assertFalse(band.connected)
        self.assertTrue(d.closed)

    def test_connect_is_idempotent(self):
        band = MiBand()
        with mock.patch("api.band.open_session",
                        return_value=(_FakeDaemon(), object())) as op:
            band.connect()
            band.connect()
        self.assertEqual(op.call_count, 1)


class TestMiBandTransport(unittest.TestCase):
    def _connected(self):
        band = MiBand()
        band.d, band.sess = _FakeDaemon(), object()
        return band

    def test_send_maps_ioerror_to_command_error(self):
        band = self._connected()
        with mock.patch("api.band.send_command", side_effect=IOError("no ack")):
            with self.assertRaises(CommandError):
                band.send(2, 1)
        self.assertTrue(band.connected)

    def test_send_maps_connection_error_to_connection_lost(self):
        band = self._connected()
        with mock.patch("api.band.send_command",
                        side_effect=ConnectionError("dropped")):
            with self.assertRaises(ConnectionLost):
                band.send(2, 1)
        self.assertFalse(band.connected)

    def test_raw_decodes_hex_body(self):
        band = self._connected()
        seen = {}

        def fake_send(d, sess, ctype, subtype, body=b"", listen=8, expect="auto"):
            seen["body"] = body
            return []

        with mock.patch("api.band.send_command", side_effect=fake_send):
            band.raw(2, 1, "aabb")
        self.assertEqual(seen["body"], b"\xaa\xbb")


class TestMiBandCommands(unittest.TestCase):
    def _capture(self, method, *args, **kwargs):
        band = MiBand()
        band.d, band.sess = _FakeDaemon(), object()
        seen = {}

        def fake_send(d, sess, ctype, subtype, body=b"", listen=8, expect="auto"):
            seen.update(ctype=ctype, subtype=subtype, body=body)
            return []

        with mock.patch("api.band.send_command", side_effect=fake_send):
            getattr(band, method)(*args, **kwargs)
        return seen

    def test_notify_is_type_7_subtype_0(self):
        seen = self._capture("notify", "Title", "Body")
        self.assertEqual((seen["ctype"], seen["subtype"]), (7, 0))
        self.assertIn(b"Title", seen["body"])
        self.assertIn(b"Body", seen["body"])

    def test_find_watch_start_and_stop(self):
        self.assertIn(pb_varint(5, 0), self._capture("find_watch", True)["body"])
        self.assertIn(pb_varint(5, 1), self._capture("find_watch", False)["body"])

    def test_battery_status_parses_reply(self):
        band = MiBand()
        band.d, band.sess = _FakeDaemon(), object()
        battery = pb_varint(1, 85) + pb_varint(2, 2)
        body = pb_bytes(4, pb_bytes(2, pb_bytes(1, battery)))
        reply = [Response(2, 1, 1, False, body)]
        with mock.patch("api.band.send_command", return_value=reply):
            self.assertEqual(band.battery_status(), {"level": 85, "state": 2})

    def test_send_named_rejects_unknown(self):
        band = MiBand()
        with self.assertRaises(BandError):
            band.send_named("nope")


class TestCli(unittest.TestCase):
    def test_commands_lists_catalogue_without_connecting(self):
        from api import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["commands"])
        self.assertEqual(rc, 0)
        self.assertIn("battery", buf.getvalue())
        self.assertIn("notify", buf.getvalue())

    def test_no_verbs_prints_help(self):
        from api import cli
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([]), 0)


class TestRegistryView(unittest.TestCase):
    def test_lookup_accepts_hyphen_and_underscore(self):
        self.assertEqual(registry.lookup("face-list").name, "face-list")
        self.assertEqual(registry.lookup("face_list").name, "face-list")

    def test_lookup_unknown_is_none(self):
        self.assertIsNone(registry.lookup("no-such-command"))

    def test_names_are_unique_and_match_catalogue(self):
        names = registry.names()
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), len(registry.COMMANDS))

    def test_by_status_live_includes_battery(self):
        self.assertIn("battery", [c.name for c in registry.by_status("live")])

    def test_by_service_groups(self):
        grouped = registry.by_service()
        self.assertIn("Notification", grouped)
        self.assertIn("notify", [c.name for c in grouped["Notification"]])


class TestRegistryDrivenCommands(unittest.TestCase):
    def _band(self):
        band = MiBand()
        band.d, band.sess = _FakeDaemon(), object()
        return band

    def test_command_uses_registry_type_subtype(self):
        band = self._band()
        seen = {}

        def fake_send(d, sess, ctype, subtype, body=b"", listen=8, expect="auto"):
            seen.update(ctype=ctype, subtype=subtype, body=body)
            return []

        with mock.patch("api.band.send_command", side_effect=fake_send):
            band.command("face-list")
        self.assertEqual((seen["ctype"], seen["subtype"]), (4, 10))

    def test_command_accepts_underscores(self):
        band = self._band()
        with mock.patch("api.band.send_command", return_value=[]) as sc:
            band.command("face_list")
        self.assertEqual(sc.call_args.args[2:4], (4, 10))

    def test_command_unknown_raises(self):
        band = self._band()
        with self.assertRaises(BandError):
            band.command("nope-not-real")

    def test_dynamic_verb_sends_registry_command(self):
        band = self._band()
        with mock.patch("api.band.send_command", return_value=[]) as sc:
            band.face_list()
        self.assertEqual(sc.call_args.args[2:4], (4, 10))

    def test_explicit_method_shadows_registry_verb(self):
        band = self._band()
        with mock.patch("api.band.send_command", return_value=[]) as sc:
            band.battery()
        self.assertEqual(sc.call_args.args[2:4], (2, 1))

    def test_unknown_attribute_raises(self):
        band = self._band()
        with self.assertRaises(AttributeError):
            band.definitely_not_a_command

    def test_dir_includes_registry_names(self):
        self.assertIn("face_list", dir(MiBand()))

    def test_known_commands_tuples(self):
        rows = MiBand.known_commands()
        self.assertIn((2, 1, "battery", "live"), rows)


class TestEvents(unittest.TestCase):
    def _notify_line(self, body):
        sess = Session(_FakeDaemon([]), b"k" * 16)
        frame = sess.frame(PT_DATA, bytes([CH_PROTOBUF, OP_PLAIN]) + body)
        return "NOTIFY " + UUID_RX + " " + frame.hex()

    def test_read_events_returns_pushed_frames(self):
        line = self._notify_line(command(7, 0))
        band = MiBand()
        band.d = _FakeDaemon([line])
        band.sess = Session(band.d, b"k" * 16)
        out = read_events(band, timeout=0.4)
        self.assertEqual([(r.type, r.subtype) for r in out], [(7, 0)])

    def test_read_events_requires_connection(self):
        with self.assertRaises(api.NotConnectedError):
            read_events(MiBand(), timeout=0.1)


if __name__ == "__main__":
    unittest.main()
