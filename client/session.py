#!/usr/bin/env python3
"""Persistent authenticated session to the Mi Band 9 Active (library).

The band allows a single login per BLE session; re-authenticating per command
fails. `open_session()` owns the one connect + subscribe + authenticate
sequence (with retries) that every entry point shares.
"""
import logging
import time

from .log import ensure_configured
from .protocol.constants import UUID_RX
from .protocol.daemon import Daemon
from .protocol.handshake import Session, authenticate
from .commands import load_key

logger = logging.getLogger(__name__)


def open_session(key=None, port=8477, use_session=True, auth_timeout=300,
                 verbose=False, capture=True, capture_maxlen=1000):
    """Connect to the BLE daemon, subscribe, and authenticate with retries.

    Returns `(Daemon, Session)`. Raises `ConnectionError` on timeout. The
    daemon socket is closed before raising if any step fails.
    """
    if verbose:
        ensure_configured()
    secret = load_key(key)
    d = Daemon(port=port)
    try:
        mtu = d.mtu(512)
        mtu_ev = d.wait_event("EVENT mtu")
        sub = d.subscribe(UUID_RX)
        sub_ev = d.wait_event("EVENT subscribed")
        logger.info("connected; mtu=%s (%s)", mtu, mtu_ev)
        logger.info("subscribe=%s (%s)", sub, sub_ev)

        sess = Session(d, secret, capture=capture,
                       capture_maxlen=capture_maxlen)
        deadline = time.time() + auth_timeout
        while time.time() < deadline:
            if authenticate(d, sess, use_session=use_session, verbose=False,
                            attempts=1, timeout=6):
                logger.info("session ready")
                return d, sess
            logger.warning("login rejected; retrying in 5s (band busy/not ready)")
            time.sleep(5)
        logger.error("authentication failed (timed out)")
        raise ConnectionError("authentication failed (timed out)")
    except BaseException:
        logger.debug("closing daemon after failed session setup")
        d.close()
        raise
