# Release Notes - AdvPrint Pro v3.5.4

**CRX SIGNATURE VERIFIED - the extension package is signed and build-checked**

by Bit Dream IT - Innovative Healthcare Solutions - 2026-11-15

---

## The one-line story

v3.5.3 kept the status bar always visible but shipped its `.crx` with a
STALE signature and Chrome refused it ("crx signature verification
failed - previous 3.5.2 crx work fine but current so fix"). The
same-day hot-fix repaired the file; **v3.5.4 is the full release** that
bakes the fix into the tree, bumps every version string to 3.5.4 and
rebuilds every artifact with the signature check as a hard build gate.

## Root cause recap - a stale signature, not a bad key

The CRX3 header carries an RSA signature over
`"CRX3 SignedData\0" + LE32(len) + signed_header_data + <the zip>`.
The v3.5.3 file was signed over an older zip than the archive actually
packed inside. The build's existing guards stay green on such a file -
`cmp` proves copies identical, the version guard reads only the payload
manifest - so the stale-signed CRX passed the build and Chrome rejected
it at install. Independent forensics: v3.5.2 CRX = signature VALID
(that is why 3.5.2 loaded), v3.5.3 CRX = signature INVALID over both
the old and the new payload, while the payload itself was byte-identical
to the extension source.

## What v3.5.4 changes

1. **Every CRX repacked fresh** from `extension/` with the SAME stable
   release key `extension-signing/advprint-printer.pem` - the extension
   ID stays `likldbkamojokkfdlcjibiljpgbbnohc`, so hub pairing, stored
   settings and the `/extension/updates.xml` auto-update chain all
   survive the upgrade.
2. **`tool/crx3.py verify <crx> [version]`** - a Chrome-identical
   verification (ID/key match, RSA-PKCS1v15-SHA256 over the exact
   archive inside, payload zip integrity, expected version). It FAILS
   on the broken v3.5.3 file and PASSES every good one - no false
   positives on v3.5.2.
3. **Hard build gate** in `scripts/build-all.sh` right after the
   sync/version guards: the build REFUSES to ship a CRX whose signature
   does not match its payload. A stale-signed CRX can never reach a
   release again.
4. **Version coherence 3.5.4** everywhere: hub `VERSION`/`VERSION_NAME`
   ("CRX SIGNATURE VERIFIED"), `VERSION.txt`, `extension/manifest.json`,
   popup + i18n (EN/Bangla) + api.js fallback, console title,
   `BOOT.version` fallbacks (x3), hub stat card, NSIS
   `VIProductVersion 3.5.4.0` / `DisplayVersion` / exe name, deb
   `control`, README + START-HERE. The v3.5.3 statusbar-fix CSS stays
   byte-for-byte (its stylesheet comment intentionally still says
   "v3.5.3 statusbar fix" - that is history, not the current version).

## Verified end-to-end

Signature forensics (independent Chrome-identical verifier):

| File | Signature | Payload |
|------|-----------|---------|
| v3.5.2 CRX | RSA VALID | 3.5.2 - the reference that always worked |
| v3.5.3 CRX (broken) | RSA INVALID over old AND new payload | 3.5.3 |
| v3.5.4 CRX (this release) | RSA VALID | 3.5.4, byte-identical to source |
| Chromium `--pack-extension`, same key | RSA VALID, same extension ID | reference cross-check |

Live hub + real Chromium render (`scripts/smoke_v354.py`):

| Viewport | Status bar (top..bottom) | Viewport height | Desktop bottom | Doc scroll height | JS errors |
|----------|--------------------------|-----------------|----------------|-------------------|-----------|
| 1280x720 | 678..705 | 720 | 720 | 720 | 0 |
| 1440x900 | 858..885 | 900 | 900 | 900 | 0 |

- `/health` reports `version: 3.5.4` (worker alive);
- `/extension/info` reports `3.5.4`, `stale: false`;
- the served `/ui` title reads *ALL-IN-ONE Console v3.5.4* and the
  status bar version pane reads *Printing Hub v3.5.4 · Bit Dream IT*;
- screenshots: `docs/v3.5.4-preview-720p.png`,
  `docs/v3.5.4-preview-900p.png`.

Test suite: `tests/test_v354.py` (new - CRX verification, gate, stable
key, coherence) plus the regression suites `test_v353.py`,
`test_v352.py`, `test_v351.py`, `test_hub_v2.py`:
**237 passed, 1 skipped** (the skip is the long-standing optional
printer-backend case).

Artifacts rebuilt and byte-checked to embed the fixed CRX:
`advprint-pro_3.5.4_all.deb` (dpkg-deb extraction md5 match) and
`AdvPrint-Pro-Setup-3.5.4.exe` (NSIS payload extraction md5 match).
Checksums: `docs/SHA256SUMS-3.5.4.txt`.

## What did NOT change

Print logic, queue, rules, ProTheme engine (8 themes + density /
corners / frame), network sharing, IPP/RAW, DropZone, history behavior,
the always-visible status bar - all exactly the working v3.5.3 build.

## Upgrade

Same as every 3.x release: close the old hub, install over it (the
Windows setup exe keeps config.json, the queue database and rules),
restart; Chrome self-updates the extension from the hub within a
minute. Linux: `sudo dpkg -i advprint-pro_3.5.4_all.deb`. Drag-install
instead: use the included `AdvPrint-Pro.crx` (Developer mode ON at
chrome://extensions) and check its SHA256 first - see
`docs/SHA256SUMS-3.5.4.txt`.
