# AGENTS.md — working rules for this repo

## Rule 0 — firmware first, before trial-and-error

When a protocol behaviour is unclear, or a live attempt fails, **analyze the
device firmware before trying more variations.** Do not brute-force the band by
guessing packet variations.

The Mi Band 9 Active firmware is fully recovered and available locally:

- `notes/FIRMWARE-DEEP.md` — findings (SoC, auth/bind FSM, crypto, packet format)
- `notes/fw/reconstructed.bin` — 3.48 MiB decompressed image
- `notes/fw_reconstruct.py`, `notes/fw_auth.py`, `notes/fw_deep*.py` — scripts

Why this works: the image is **not encrypted**. The AOTA payload is xz-compressed
in 32 KB blocks and decompresses to readable code and strings. It exposes the
device-side implementation of exactly what we reverse-engineer: the `AUTH PSK
BIND` FSM, `miwear-auth`, `hmac sha256 with psk`, AES-CCM, and the
`auth wear packet type/id/payload tag` format.

So: on a failed attempt, grep the reconstructed image for the relevant
subsystem's strings **first**, then adjust the client with evidence.

## Other rules

- `notes/` is gitignored. Research, firmware, keys, and captured traffic live
  there. **Never commit the auth key or captured BLE traffic.**
- Test live only against the owner's own band. Prefer non-destructive commands
  (device info, battery) before anything that changes device state.
- Keep the auth key out of the repo and out of logs (mask it in output).
- The shell-UID daemon is a BLE transport only: bind to `127.0.0.1`, no network.
