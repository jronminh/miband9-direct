#!/usr/bin/env python3
"""Tests for the automation helpers (no band, no scheduler, no Termux:API).

Run with: python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mibandd import setup


class WatchdogScriptTest(unittest.TestCase):
    def test_script_wakes_and_respawns(self):
        body = setup._watchdog_script_body()
        self.assertTrue(body.startswith("#!"))
        self.assertIn("termux-wake-lock", body)
        self.assertIn("serve --stay --daemonize", body)
        self.assertIn(setup.DAEMON_PID, body)
        self.assertIn(setup.WATCHDOG_LOG, body)


class _SchedulerTest(unittest.TestCase):
    """Base: redirect the generated scripts to a temp dir, fake subprocess."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patches = [
            mock.patch.object(setup, "JOB_DIR", self.tmp.name),
            mock.patch.object(setup, "_need_scheduler"),
            mock.patch.object(setup.subprocess, "run"),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.run = setup.subprocess.run
        self.run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

    @staticmethod
    def _job_arg(args, flag):
        return args[args.index(flag) + 1]


class WatchdogInstallTest(_SchedulerTest):
    def setUp(self):
        super().setUp()
        self.script = os.path.join(self.tmp.name, "watchdog.sh")
        patch = mock.patch.object(setup, "WATCHDOG_SCRIPT", self.script)
        patch.start()
        self.addCleanup(patch.stop)

    def test_registers_job_8802(self):
        info = setup.watchdog_install(period_min=15)
        self.assertEqual(info["job_id"], 8802)
        args = self.run.call_args.args[0]
        self.assertEqual(self._job_arg(args, "--job-id"), "8802")
        self.assertEqual(self._job_arg(args, "--period-ms"), "900000")
        self.assertEqual(self._job_arg(args, "--persisted"), "true")
        self.assertEqual(self._job_arg(args, "--battery-not-low"), "true")
        self.assertTrue(os.path.exists(self.script))
        self.assertEqual(os.stat(self.script).st_mode & 0o777, 0o700)

    def test_period_has_15_min_floor(self):
        setup.watchdog_install(period_min=1)
        args = self.run.call_args.args[0]
        self.assertEqual(self._job_arg(args, "--period-ms"), "900000")


class ScheduleRefactorTest(_SchedulerTest):
    def setUp(self):
        super().setUp()
        self.script = os.path.join(self.tmp.name, "collect.sh")
        patch = mock.patch.object(setup, "JOB_SCRIPT", self.script)
        patch.start()
        self.addCleanup(patch.stop)

    def test_collect_still_registers_job_8801(self):
        info = setup.schedule_install(period_min=15)
        self.assertEqual(info["job_id"], 8801)
        self.assertEqual(info["log"], setup.JOB_LOG)
        args = self.run.call_args.args[0]
        self.assertEqual(self._job_arg(args, "--job-id"), "8801")
        with open(self.script) as fh:
            self.assertIn("health collect", fh.read())


class WakeLockTest(unittest.TestCase):
    def test_wake_lock_uses_termux_tool(self):
        with mock.patch.object(setup, "_need_termux_tool",
                               return_value="/bin/termux-wake-lock") as tool, \
                mock.patch.object(setup.subprocess, "run") as run:
            self.assertEqual(setup.wake_lock(), {"wake_lock": True})
        tool.assert_called_once_with("termux-wake-lock")
        run.assert_called_once_with(["/bin/termux-wake-lock"], check=True)

    def test_missing_tool_raises(self):
        with mock.patch.object(setup.shutil, "which", return_value=None):
            with self.assertRaises(ValueError):
                setup.wake_lock()


class AutomateStopTest(_SchedulerTest):
    def test_cancels_both_jobs_and_unlocks(self):
        with mock.patch.object(setup, "wake_unlock",
                               return_value={"wake_lock": False}) as unlock, \
                mock.patch.object(setup, "_shutdown_daemon",
                                  return_value={"pid": 7, "stopped": True}):
            result = setup.automate_stop()
        self.assertTrue(result["collect_cancelled"])
        self.assertTrue(result["watchdog_cancelled"])
        unlock.assert_called_once()
        cancelled = []
        for call in self.run.call_args_list:
            args = call.args[0]
            if "--cancel" in args:
                cancelled.append(self._job_arg(args, "--job-id"))
        self.assertIn("8801", cancelled)
        self.assertIn("8802", cancelled)


if __name__ == "__main__":
    unittest.main()
