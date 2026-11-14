# AdvPrint Pro v3.5.1 - Release Notes

**Dashboard live data - every dashboard value comes from the hub.**
by Bit Dream IT - Innovative Healthcare Solutions

## The report

> "in all previous version dashboard data so fake it need update 3.5.1
> bug fix only dashboard related it like alwase show 33.3% siuccess and
> default printer and other this is not dynamic"

The user was right. The dashboard LOOKED live, but these values were
STATIC DEMO MARKUP that no render code ever replaced, in every release
since the ONE UI shipped:

| Dashboard value                       | What it really was                        |
|---------------------------------------|-------------------------------------------|
| `uptime 04:12:37`                     | hardcoded text in the card header          |
| Default Printer name / OFFLINE / hold | hardcoded "HP Laser 103 107 108" sample    |
| `2 PCs` / `2 peers` connections       | hardcoded chips, never updated             |
| `RAW port LISTENING 10.26.94.206:9100`| hardcoded sample address                   |
| `DropZone ON watching 1 folder`       | hardcoded sample text                      |
| `last 6 of 38 today` caption          | hardcoded "38"                             |
| dashboard subtitle `AI-Lab`           | hardcoded sample PC name                   |
| IPP row                               | BUG: overwritten with the mDNS text        |

The KPI row (jobs today / success rate / queue / printers ready) and
the Recent Jobs rows WERE already live - they come from `/stats`,
`/printers` and `/jobs`. The hub also already returned every missing
real value (`/health` carries `default_printer`, `worker_alive`,
`raw_active`, `raw_addrs`, `raw_printer_port`; `/peers` the peer
counts; `/dropzone` the waiting count; `/config` the hold setting).
Only the console wiring was missing.

## The fix (v3.5.1 - dashboard only, on the untouched v3.5.0 tree)

1. **New `renderDashboard()`** writes every Print Hub Status + Default
   Printer row through explicit element ids (`dashUptime`, `dashService`,
   `dashListen`, `dashLan`, `dashIpp`, `dashRaw`, `dashDrop`, `dashConn`,
   `dashToken`, `dpName`, `dpStatus`, `dpHold`, `dashRecentCap`,
   `dashSub`) on every 3 s poll. A missing row can never silently keep
   a static value again.
2. **The old key-guessing "glance" loop is deleted.** It matched rows
   by substring (`key.indexOf("ipp") >= 0`), which is why the uptime,
   RAW, DropZone, Connections and Default-Printer rows stayed static
   forever and why the IPP row got the mDNS text
   ("printers announce themselves") instead of READY /ipp/print.
3. **loadConnections() publishes the live peer answer**
   (`dashConnState`) so the dashboard Connections row shows this PC
   (+1 when a LAN PC is saved) and online/total peers from `/peers`.
4. **poll() now refreshes DropZone every cycle** so the waiting-PDF
   count on the dashboard is live (before: only on boot / tab open).

Zero server-side (advprint.py) logic changes - the endpoints already
had every value. No print / rule / queue / theme / network logic
changed.

## How to verify (2 minutes)

1. Open `http://127.0.0.1:9235/ui` -> Dashboard:
   - the uptime chip starts from YOUR hub's real uptime and ticks
     every second (never 04:12:37 again);
   - Default Printer shows YOUR real default printer; pause/unplug it
     and the chip flips to OFFLINE; the Hold row follows your real
     PRINTER STATUS HOLD switch in Settings;
   - Connections shows your real peers (a fresh hub shows
     `1 PC 0/0 peers`, never `2 PCs 2 peers`);
   - DropZone OFF shows `OFF enable it in the DropZone tab`, and with
     the watch ON the row shows the real waiting-PDF count;
   - the subtitle shows your real PC name.
2. `http://127.0.0.1:9235/health` reports `"version": "3.5.1"` and
   carries `default_printer`, `worker_alive`, `raw_active`.
3. Automated: `python3 tests/test_v351.py` (structure + live-hub
   checks when a test hub is started by the harness).

## Files

- `tool/unix/hub/console.html` (+ windows/portable + installer/stage
  copies, byte-identical) - the ONE UI with the live dashboard.
- `download/AdvPrint-Pro-Console-UI-Template-v3.5.1-ProTheme.html` -
  the same UI as a standalone theme template (TEMPLATE PREVIEW chip
  when the hub is offline).
- `tests/test_v351.py` - locks the fix.
- `CHANGELOG.md` / this file / `START-HERE.txt` - updated.
