#!/usr/bin/env python3
"""Tests for the mibandd daemon core (no band, no BLE).

Run with: python -m unittest discover -s tests -v
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mibandd import client
from mibandd.domains import register_all
from mibandd.rpc import VERSION, RpcServer
from mibandd.session import SessionManager
from store.db import Database
from store.summary import SLOT_SIZES


def daily_payload(values, version=4):
    """Minimal v3/v4 daily-summary body for the given slot values."""
    header = bytearray(3)
    for index in values:
        header[index // 8] |= 1 << (7 - (index % 8))
    body = bytearray()
    for index, size in enumerate(SLOT_SIZES):
        body += int(values.get(index, 0)).to_bytes(size, "little")
    file_id = (1789784085).to_bytes(4, "little") + bytes([28, version, 0x01])
    return bytes(file_id) + b"\x00" + bytes(header) + bytes(body)


def rpc(port, obj, timeout=3.0):
    with socket.create_connection(("127.0.0.1", port), timeout) as sock:
        sock.sendall((json.dumps(obj) + "\n").encode())
        reader = sock.makefile("r")
        return json.loads(reader.readline())


class FakeBackend:
    """Stands in for BandData: records concurrency, touches no BLE."""

    def __init__(self):
        self.connected = True
        self.active = 0
        self.max_active = 0
        self.closed = False

    def op(self, delay=0.0):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        time.sleep(delay)
        self.active -= 1
        return {"ok": True}

    def close(self):
        self.closed = True
        self.connected = False


def make_server(session, idle_timeout=None):
    server = RpcServer(("127.0.0.1", 0), session)
    port = server.server_address[1]
    thread = threading.Thread(
        target=server.serve,
        kwargs={"idle_timeout": idle_timeout, "poll": 0.1},
        daemon=True)
    thread.start()
    return server, port, thread


class TestRpc(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.session = SessionManager(backend_factory=lambda: self.backend)
        self.session.register("demo", {"ping": lambda b, **a: b.op()})
        self.server, self.port, self.thread = make_server(self.session)

    def tearDown(self):
        self.server.state.stop.set()
        self.thread.join(timeout=2)

    def test_ping_round_trip(self):
        resp = rpc(self.port, {"id": 1, "domain": "", "op": "ping", "args": {}})
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["result"], "pong")

    def test_version(self):
        resp = rpc(self.port, {"id": 2, "domain": "", "op": "version", "args": {}})
        self.assertEqual(resp["result"]["version"], VERSION)

    def test_domain_op(self):
        resp = rpc(self.port, {"id": 3, "domain": "demo", "op": "ping", "args": {}})
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["result"], {"ok": True})

    def test_unknown_builtin_error_shape(self):
        resp = rpc(self.port, {"id": 4, "domain": "", "op": "nope", "args": {}})
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"]["code"], "unknown_op")

    def test_unknown_domain_op_error(self):
        resp = rpc(self.port, {"id": 5, "domain": "demo", "op": "nope", "args": {}})
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"]["code"], "unknown_op")

    def test_bad_json(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=3) as sock:
            sock.sendall(b"not json\n")
            reader = sock.makefile("r")
            resp = json.loads(reader.readline())
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"]["code"], "bad_json")


class TestSerialization(unittest.TestCase):
    def test_requests_do_not_interleave(self):
        backend = FakeBackend()
        session = SessionManager(backend_factory=lambda: backend)
        session.register("demo", {"work": lambda b, **a: b.op(delay=0.2)})
        results = []

        def call():
            results.append(session.request("demo", "work", {}))

        threads = [threading.Thread(target=call) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 4)
        self.assertEqual(backend.max_active, 1)


class TestIdleExit(unittest.TestCase):
    def test_idle_exit(self):
        backend = FakeBackend()
        session = SessionManager(backend_factory=lambda: backend)
        _server, _port, thread = make_server(session, idle_timeout=0.3)
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())

    def test_activity_keeps_it_alive(self):
        backend = FakeBackend()
        session = SessionManager(backend_factory=lambda: backend)
        server, port, thread = make_server(session, idle_timeout=0.6)
        try:
            for _ in range(3):
                resp = rpc(port, {"id": 1, "domain": "", "op": "ping", "args": {}})
                self.assertTrue(resp["ok"])
                time.sleep(0.25)
            self.assertTrue(thread.is_alive())
        finally:
            server.state.stop.set()
            thread.join(timeout=2)


class FakeDb:
    """Minimal stand-in for store.Database."""

    def history(self, name=None, limit=20):
        return [{"name": name}]

    def samples(self, metric=None, limit=20):
        return [{"metric": metric}]

    def stats(self):
        return {"samples": 1}

    def activity_files(self, limit=50):
        return [{"file_ts": 1}]


class FakeBand:
    """Stands in for BandData: records commands, no BLE."""

    def __init__(self):
        self.connected = True
        self.calls = []
        self.db = FakeDb()

    def raw(self, name, ctype, subtype, body=b"", listen=None, ts=None):
        self.calls.append((name, ctype, subtype, body))
        return []

    def battery(self):
        return {"level": 80, "state": 2}

    def info(self):
        return {"serial": "x", "firmware": "1", "model": "m"}

    def collect_activity(self, **kwargs):
        return [{"ts": 1, "suffix": "1c0401"}]

    def blob(self, file_ts, suffix):
        return b"\x01\x02"

    def activity_blobs(self, limit=500):
        return [{"file_ts": 1}]

    def activity_files(self, past=False):
        return [{"ts": 1, "suffix": "1c0401"}]

    def close(self):
        self.connected = False


class TestDomains(unittest.TestCase):
    """Domain ops dispatch through the router against a fake band."""

    def setUp(self):
        self.band = FakeBand()
        self.session = SessionManager(backend_factory=lambda: self.band)
        self.domains = register_all(self.session)

    def test_domains_registered(self):
        self.assertEqual(self.domains,
                         ["device", "health", "notify", "store"])

    def test_device_battery(self):
        self.assertEqual(self.session.request("device", "battery", {}),
                         {"level": 80, "state": 2})

    def test_device_state_is_response_dicts(self):
        self.assertEqual(self.session.request("device", "state", {}), [])

    def test_device_clock_sends_command(self):
        self.assertEqual(self.session.request("device", "clock", {"h12": True}),
                         {"ok": True, "responses": 0})
        self.assertEqual(self.band.calls[-1][1:3], (2, 3))

    def test_device_raw_requires_type(self):
        with self.assertRaises(ValueError):
            self.session.request("device", "raw", {})

    def test_notify_sends_notification(self):
        result = self.session.request(
            "notify", "notify", {"title": "hi", "text": "there"})
        self.assertTrue(result["ok"])
        self.assertEqual(self.band.calls[-1][1:3], (7, 0))

    def test_health_collect(self):
        result = self.session.request("health", "collect", {})
        self.assertEqual(result["stored"], [{"ts": 1, "suffix": "1c0401"}])

    def test_health_list(self):
        self.assertEqual(self.session.request("health", "list", {}),
                         [{"ts": 1, "suffix": "1c0401"}])

    def test_health_blob_hex(self):
        result = self.session.request(
            "health", "blob", {"file_ts": 1, "suffix": "1c0401"})
        self.assertEqual(result["hex"], "0102")

    def test_store_stats(self):
        self.assertEqual(self.session.request("store", "stats", {}),
                         {"samples": 1})

    def test_unknown_domain(self):
        from mibandd.session import UnknownOp
        with self.assertRaises(UnknownOp):
            self.session.request("nope", "nope", {})


class TestClientLib(unittest.TestCase):
    """The thin RPC client against a live server (no spawn)."""

    def setUp(self):
        self.backend = FakeBackend()
        self.session = SessionManager(backend_factory=lambda: self.backend)
        self.session.register("demo", {"ping": lambda b, **a: b.op()})
        self.server, self.port, self.thread = make_server(self.session)

    def tearDown(self):
        self.server.state.stop.set()
        self.thread.join(timeout=2)

    def test_call_round_trip(self):
        self.assertEqual(
            client.call("demo", "ping", {}, port=self.port, spawn=False),
            {"ok": True})

    def test_call_failure_raises(self):
        with self.assertRaises(client.RpcFailure):
            client.call("demo", "nope", {}, port=self.port, spawn=False)

    def test_call_no_spawn_unavailable(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
        probe.close()
        with self.assertRaises(client.DaemonUnavailable):
            client.call("demo", "ping", {}, port=dead_port, spawn=False)


OLD_TS = 1789774136
NEW_TS = 1789784085


class FakeSummaryBand:
    """Fake backend exposing stored daily-summary blobs + a real Database."""

    def __init__(self, db, blobs):
        self.db = db
        self._blobs = blobs          # {file_ts: payload}
        self.connected = True

    def activity_blobs(self, limit=500):
        return [{"file_ts": ts, "suffix": "1c0401",
                 "kind": "activity-daily", "detail": "summary"}
                for ts in sorted(self._blobs, reverse=True)]

    def blob(self, file_ts, suffix):
        return self._blobs[file_ts]

    def close(self):
        pass


class TestHealthDecode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "t.db"))
        base = {0: 528, 1: 58, 3: 54, 4: 94, 6: 55, 12: 32}
        self.blobs = {
            OLD_TS: daily_payload({**base, 8: 68}),
            NEW_TS: daily_payload({**base, 8: 73}),
        }
        self.band = FakeSummaryBand(self.db, self.blobs)
        self.session = SessionManager(backend_factory=lambda: self.band)
        register_all(self.session)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_decode_writes_daily_samples(self):
        result = self.session.request("health", "decode", {})
        self.assertEqual(result["decoded"], 2)
        rows = self.db.samples(prefix="daily.", limit=100)
        self.assertEqual(len(rows), 14)
        self.assertIsNotNone(rows[0]["date"])

    def test_decode_is_idempotent(self):
        self.session.request("health", "decode", {})
        first = len(self.db.samples(prefix="daily.", limit=100))
        self.session.request("health", "decode", {})
        second = len(self.db.samples(prefix="daily.", limit=100))
        self.assertEqual(first, second)

    def test_summary_is_latest_day(self):
        self.session.request("health", "decode", {})
        summary = self.session.request("health", "summary", {})
        self.assertEqual(summary["file_ts"], NEW_TS)
        self.assertEqual(summary["fields"]["hr_avg"], 73)

    def test_trend_is_chronological(self):
        self.session.request("health", "decode", {})
        trend = self.session.request("health", "trend",
                                     {"metric": "daily.hr_avg"})
        self.assertEqual([p["value"] for p in trend["series"]], [68, 73])


class TestMibanddCli(unittest.TestCase):
    """The `mibandd <domain> <op>` CLI."""

    def setUp(self):
        self.backend = FakeBand()
        self.session = SessionManager(backend_factory=lambda: self.backend)
        register_all(self.session)
        self.server, self.port, self.thread = make_server(self.session)

    def tearDown(self):
        self.server.state.stop.set()
        self.thread.join(timeout=2)

    def test_parser_maps_domains_and_builtins(self):
        from mibandd.main import client_parser
        parser = client_parser()
        for argv in (["health", "summary"], ["device", "battery"],
                     ["store", "stats"], ["notify", "notify"], ["ping"],
                     ["commands"], ["key"], ["schedule", "status"],
                     ["watch"]):
            self.assertTrue(callable(parser.parse_args(argv).fn), argv)

    def test_cli_call_against_server(self):
        import contextlib
        import io
        from mibandd import main as mibandd_main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = mibandd_main(["store", "stats", "--no-spawn",
                               "--port", str(self.port), "--json"])
        self.assertEqual(rc, 0)
        self.assertIn("samples", buf.getvalue())


class TestCompletion(unittest.TestCase):
    def test_candidates(self):
        from mibandd.complete import candidates
        self.assertIn("health", candidates([""]))
        self.assertIn("summary", candidates(["health", ""]))
        self.assertIn("--json", candidates(["health", "summary", "--"]))
        self.assertIn("store", candidates(["call", ""]))

    def test_script(self):
        from mibandd.complete import script
        for shell in ("bash", "zsh", "fish"):
            self.assertIn("__complete", script(shell))

    def test_unknown_shell(self):
        from mibandd.complete import script
        with self.assertRaises(ValueError):
            script("tcsh")


if __name__ == "__main__":
    unittest.main()
