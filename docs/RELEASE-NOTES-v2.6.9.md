# AdvPrint Pro v2.6.9 — Release Notes

**AdvPrint Pro (Advanced Printer)** — by Bit Dream IT - Innovative Healthcare Solutions
MIT license · 100% local · no cloud · no tracking
Date: 2026-11-01 · Base: v2.6.8 (full feature set kept 1:1)

## The one fix: every page printed TWICE with Queue Mode OFF

**What you saw (v2.6.8, live Debug tab):** printing worked — and then the
printer printed the same page again ("after print it extra again auto
print"). The log showed each job twice: two `command:` lines, two
`[PRINT] SumatraPDF -> …` lines and two `[OK] job #N printed` lines with
different timings (e.g. 2183 ms "(direct)" and 1809 ms).

**Root cause — a race inside the hub, NOT your printer or its driver:**
with Queue Mode OFF the job row was created in the database as `queued`
and only flipped to `printing` *after* the slow printer-status probe
(hundreds of milliseconds on Windows). The FIFO worker polls every
0.35 s and claimed the job inside that window — so **both** the direct
thread and the queue worker sent the same job to SumatraPDF. One job,
two sheets.

**The fix:** the execution path (direct vs queue) is now decided *before*
the job row exists, and the row is born in its final state (`printing`
for direct jobs). The worker — which only claims `queued` rows — can
never see a direct job. One job = one sheet = one `[OK]` line.

**Proof:** a new race regression test slows the printer-status probe to
0.6 s and fails on v2.6.8 (the log reproduces the double `[OK]` exactly
as on the user's machine) and passes on v2.6.9. A live end-to-end check
(fake CUPS backend) proves the print backend is invoked **exactly once**
for a Queue-OFF job. Full suite: 111/111 pytest + 68/68 live checks.

## Also fixed in 2.6.9

- **Direct-mode retry keeps its PDF:** a Queue-OFF job that fails was
  deleting its own PDF before the automatic retry, so the retry always
  died with "file no longer stored". Terminal-state-only cleanup now,
  same rule the FIFO worker already used.

## Files in this release

| File | What it is |
| --- | --- |
| `AdvPrint-Pro-Setup-2.6.9.exe` | Windows setup (~9.7 MB, bundled Python 3.11.9, UAC once) |
| `advprint-pro_2.6.9_all.deb` | Debian/Ubuntu/Mint package |
| `AdvPrint-Pro-v2.6.9-FULL.zip` | Portable full tree + both installers + docs |
| `AdvPrint-Pro-2.6.9-source.zip` | Complete source (MIT) |
| `AdvPrint-Pro-Full-Guide.pdf/.html` | Full A-to-Z guide (v2.6.9) |
| `SHA256SUMS-v2.6.9.txt` | SHA-256 of every deliverable |

## Upgrade (2 minutes)

1. Run `AdvPrint-Pro-Setup-2.6.9.exe` over the old install (settings and
   history migrate automatically; the setup kills any old hub first).
2. Chrome → `chrome://extensions` → AdvPrint Pro → **Reload**.
3. Print one page with Queue Mode OFF — the log now shows exactly one
   `command:` line and one `[OK] job #N` line, and the printer outputs
   one sheet.

*Nothing else changed: the full v2.6.8 feature set (printer-name
self-heal, clean context menus, Errno-13 save-as-PDF fix, File (PDF)
virtual routing, tray, dashboard, service, CLI) is kept 1:1.*
