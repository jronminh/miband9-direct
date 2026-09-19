# Draft: Codeberg issue for Gadgetbridge (Mi Band 9 Active)

Ready to paste at <https://codeberg.org/Freeyourgadget/Gadgetbridge/issues/new>.
Delete this header and the "How to post" section below before submitting.

---

**Title:** Mi Band 9 Active (fw 2.3.151): protocol findings, activity file-id format, and a firmware wedge on `8,5`

**Body:**

I reverse-engineered the BLE protocol of the **Xiaomi Smart Band 9 Active**
(model `M2435B1`, firmware `2.3.151`) and drove it end-to-end from a standalone
client. `MiBand9ActiveCoordinator` is marked experimental ("activity fetching is
broken", "some settings are broken"), so here are verified findings that may
help. I don't have an Android build environment, so this is a report rather
than a patch.

### Environment

- Device: `Xiaomi Band 9 Active <4 hex>` (matches the existing coordinator regex)
- Firmware: `2.3.151`, model `M2435B1`
- Transport: Xiaomi SPP v2 over the `fe95` service (`005e` notify / `005f` write),
  after the usual encrypted handshake.

### Verified live

- **Auth handshake** (SPP v2) completes against the band: `1,26` phoneNonce →
  band `1,26` watchNonce+hmac → `1,27` authStep3 → authenticated. Keys via
  HMAC-SHA256 `miwear-auth` + AES-CCM devinfo + AES-128-CTR data channel.
- **Reads with replies**: `2,1` battery, `2,2` device info, `2,7` camera state,
  `2,9` password state, `2,14` misc-setting, `2,29` display-items, `7,6`
  screen-on state, `7,9` canned messages, `20,0` RPK list (empty).
- **Sets that work**: `2,6` language, `2,23` DND, `7,7` screen-on-on-notification,
  `7,0` notification, `7,1` dismiss.

### Activity file-id format (may help "activity fetching is broken")

`8,1` (today) and `8,2` (past) return `Health{field2 = bytes}`, where the blob is
a sequence of **7-byte entries**:

```
[ 4-byte little-endian Unix timestamp ][ 3-byte suffix ]
```

On this band that yields ~64 entries spanning Feb 2025 → Aug 2026. Note `8,2`
ignores any id in the body and always returns the full list. The firmware has a
complete mass file-transfer stack (`miwear_mass_prepare/finish`,
`miwear_file_flinger_download_mass_data_handle`, CRC32/MD5 checks), so the
download side looks implementable — we have not implemented it yet.

### Warning: `8,5` wedged the firmware

Sending `8,5` (`ActivitySyncRequestToday`) caused the band to **drop the BLE
link (`status=8`, connection timeout) and reboot on its own**. It recovered
fine (same serial/firmware, auth still works), but the Health activity commands
appear able to wedge the firmware. Worth handling defensively if Gadgetbridge
uses `8,5` for the 9 Active.

### Find-device

`XiaomiCoordinator.supportsFindDevice` is `true` but `MiBand9ActiveCoordinator`
overrides it to `false`. We sent the standard `2,18` (`System.findDevice`,
same as `XiaomiSystemService.CMD_FIND_WATCH`); the band ACKs the write but we
did **not** confirm an on-device vibration, so we can't say whether the override
is correct — just flagging that the command is accepted at the link layer.

### Command catalogue

We catalogued 92 known commands (type/subtype, service, payload shape, status)
for this band. Happy to share the full list / a standalone Python implementation
if useful.

---

## How to post

1. Open <https://codeberg.org/Freeyourgadget/Gadgetbridge/issues/new>
   (you need a Codeberg account; I can't post for you).
2. Paste the title and body above (everything between the `---` markers).
3. Do **not** attach the auth key, captured traffic, MAC, or serial.

## Notes

- No secrets are included above (no auth key, MAC, or serial).
- If you'd rather file a **PR** later, the only concrete candidate we identified
  is flipping `supportsFindDevice` back to `true` — but only after confirming
  live that the band actually vibrates on `2,18`.
