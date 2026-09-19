"""Line-protocol client for the shell-UID BLE daemon on 127.0.0.1:8477."""
import logging
import select
import socket
import time

logger = logging.getLogger(__name__)


class Daemon:
    """Transport to the BLE daemon: send commands, read events/notifications."""

    MAX_LINE = 1 << 20  # 1 MiB: guard against a runaway/compromised daemon

    def __init__(self, host="127.0.0.1", port=8477, timeout=10):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.setblocking(False)
        self.rbuf = b""
        self.buf = []
        try:
            self._readline(timeout)  # consume "OK hello"
        except Exception:
            self.close()
            raise

    def close(self):
        """Close the socket; safe to call more than once."""
        s, self.s = self.s, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    def _readline(self, timeout=8):
        if self.s is None:
            raise EOFError("daemon closed")
        deadline = time.time() + timeout
        while b"\n" not in self.rbuf:
            remain = deadline - time.time()
            if remain <= 0:
                raise TimeoutError("read timeout")
            r, _, _ = select.select([self.s], [], [], remain)
            if not r:
                raise TimeoutError("read timeout")
            data = self.s.recv(4096)
            if not data:
                raise EOFError("daemon closed")
            self.rbuf += data
            if len(self.rbuf) > self.MAX_LINE:
                raise ValueError("daemon line exceeds MAX_LINE")
        line, self.rbuf = self.rbuf.split(b"\n", 1)
        line = line.decode("utf-8", "replace").strip()
        logger.debug("daemon <- %s", line)
        return line

    def read(self, timeout=8):
        return self._readline(timeout)

    def _send(self, text):
        logger.debug("daemon -> %s", text)
        self.s.sendall((text + "\n").encode("utf-8"))

    def cmd(self, c):
        self._send(c)
        while True:
            line = self._readline()
            if line.startswith("OK ") or line.startswith("ERR "):
                return line
            self.buf.append(line)

    def poll(self, timeout=5):
        if self.buf:
            return self.buf.pop(0)
        return self._readline(timeout)

    def mtu(self, n):
        return self.cmd(f"mtu {n}")

    def subscribe(self, uuid):
        return self.cmd(f"subscribe {uuid}")

    def write(self, uuid, data, nr=False):
        return self.cmd(("write-nr " if nr else "write ") + uuid + " " + data.hex())

    def wait_event(self, prefix, timeout=8):
        """Read lines until one starts with `prefix`; buffer the rest."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self._readline(timeout=max(0.1, deadline - time.time()))
            except TimeoutError:
                return None
            if line.startswith(prefix):
                return line
            self.buf.append(line)
        return None

    def write_wait(self, uuid, data, nr=True, timeout=6):
        """Send a write and block until the GATT 'EVENT write' completes."""
        self._send(("write-nr " if nr else "write ") + uuid + " " + data.hex())
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self._readline(timeout=max(0.1, deadline - time.time()))
            except TimeoutError:
                return None
            if line.startswith("EVENT write"):
                return line
            if line.startswith("OK ") or line.startswith("ERR "):
                continue
            self.buf.append(line)
        return None

    def write_reliable(self, uuid, data, timeout=3, retries=8):
        """Write with response and block until the GATT operation completes.

        The band's write characteristic (005f) is write-with-response only, and
        only one GATT operation may be outstanding at a time. The daemon reports
        completion via 'EVENT write-done <status>'; retry on busy/failure.
        """
        for _ in range(retries):
            line = self.cmd("write " + uuid + " " + data.hex())
            if line.startswith("ERR busy"):
                time.sleep(0.05)
                continue
            if line.startswith("ERR"):
                return False
            done = self.wait_event("EVENT write-done", timeout=timeout)
            if done and done.endswith(" 0"):
                return True
            time.sleep(0.05)
        return False

    def read_notify(self, timeout=5):
        """Return (uuid, bytes) for the next NOTIFY, or None on disconnect."""
        while True:
            try:
                line = self.poll(timeout)
            except TimeoutError:
                return "timeout"
            if line.startswith("NOTIFY "):
                _, uuid, hexv = line.split(" ", 2)
                return uuid, bytes.fromhex(hexv)
            if line.startswith("EVENT DISCONNECTED"):
                return None
