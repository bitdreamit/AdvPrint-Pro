# AdvPrint Pro v2.7.0 — RELEASE NOTES
**History manager + Share modes + dashboard layout fix — 2026-11-01**
AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare Solutions - MIT license - 100% local - no cloud, no tracking.

---

## 1. Job history is a real manager now (dashboard + extension)

The old "Recent jobs" table (dashboard) and the plain History tab
(extension Options) became the same **professional Job history manager**:

| Feature | Dashboard | Extension Options > History |
|---|---|---|
| **Filter** by any status (printed / queued / printing / held / scheduled / failed / dead / canceled / saved / forwarded) + one-click **"Not printed (failed + dead + canceled)"** | ✔ | ✔ |
| **Search** by title / printer / `#job-id` | ✔ | ✔ |
| **Load size**: last 50 / 100 / 300 / 1000 | ✔ | ✔ |
| **Paging** (50 rows per page, newer/older) | ✔ | single list |
| **Tick rows** — per-row checkbox + master check / uncheck ALL (with the indeterminate state) + live "N selected" counter | ✔ | ✔ |
| **Reprint selected** — one call | ✔ | ✔ |
| **Reprint all non-printed** | ✔ | ✔ |
| **Clear ALL history** (hub) | ✔ | ✔ |
| Clear extension copy | — | kept (unchanged) |

Safety rules built in:

- **Clear ALL history only deletes FINISHED jobs** (printed / failed /
  dead / canceled / forwarded / saved). Waiting jobs (queued /
  printing / held / scheduled) are never touched — clearing the
  history can never cancel a real print.
- **Reprint** skips jobs whose original PDF file is gone and reports
  them as *skipped*; the batch never aborts halfway.
- Everything is audited (`reprint.bulk`, `history.cleared`).

New HTTP API (same token auth as everything else):

```
POST /jobs/bulk-reprint   {"ids":[12,13]}      ← reprint the ticked rows
POST /jobs/bulk-reprint   {"scope":"not_printed"} ← reprint every failed/dead/canceled
POST /history/clear       {}                   ← wipe finished jobs only
```

## 2. Share Receive Mode + Share Send Mode — right in the POPUP

The two LAN questions now have two named switches at the top of the
toolbar popup (section **LAN sharing**):

- **Share Receive Mode** — *this PC accepts jobs from other PCs.*
  That is the hub's `share_lan`: ON = the hub rebinds to
  `0.0.0.0:9235` after the usual hub restart (other PCs print through
  this one); OFF = strictly this PC. Saved straight into the hub
  config via `POST /config`; the live state comes back from
  `/health`, so the switch always shows the truth.
- **Share Send Mode** — *this browser may send jobs to peer PCs.*
  OFF locks every shift / send-to-PC button in this browser: the
  background refuses `queueShift` with a clear message, so nothing
  leaves this machine toward another PC. ON restores the Queue-tab
  and LAN-tab shift buttons.

Both switches turn gray while the hub is offline ("connect to the hub
first") and carry en + বাংলা labels. The LAN / PCs tab in Options
cross-references them — **no option was removed anywhere.**

## 3. Dashboard layout fixed (the "broken design" below the page)

- The **Live debug & test tool** and the SumatraPDF **Hub settings**
  box used to sit *after* the closing `</main>` — full-width,
  unstyled, hanging below the page. They are now proper panels
  **inside the main column**: live test right under the Debug card,
  settings right below it.
- The dashboard header got a **v2.7.0 version badge**; inputs,
  selects and checkboxes are styled; the `forwarded` status chip got
  its color.

## 4. Fixed on the way: dashboard tables were ALWAYS empty

`/jobs?limit=12` + `?token=...` were glued into
`/jobs?limit=12?token=...` — a query the hub cannot parse. Result on
every real install: the dashboard **Recent jobs** and **Audit trail**
tables silently stayed empty (you may have seen this on the v2.6.9
screenshot). The token is now joined with `&` (`withQ()` helper) and
additionally sent as the `X-AdvPrint-Token` header — history, audit
and the live-test printer field all work with a tokened dashboard
link. The same glue bug in the live-test tool ("Send test print") is
fixed too: a typed printer name no longer gets `?token=...` glued to
it.

## 5. Professional polish, nothing removed

- Extension **About** panel now shows the REAL manifest version
  (it used to stay on the hardcoded 2.6.4 forever); the popup
  version badge follows the manifest as well.
- History tab text, LAN tab hints and the built-in `/docs` guide all
  document the new controls; new en + Bangla strings for every new
  element; `hub version` card, START-HERE, CHANGELOG, API.md,
  EXTENSION-API.md, setup.nsi 2.7.0.0 — one version everywhere.

## 6. Tests

- **117/117 pytest** (111 before + 6 new v2.7.0 tests): bulk-reprint
  by ids (incl. unknown-id = skipped, per-id results), bulk-reprint
  `scope=not_printed` (printed rows never re-queued),
  `/history/clear` (finished only — a held job survives),
  single-reprint still behaves through the shared core, bad payload
  → 400, missing-file rows are skipped without aborting the batch.
- Full visual pass (Playwright): dashboard top / live-test panel /
  history manager, popup with the four switches, Options History tab
  with filter + select-all — zero JS errors.

## Upgrade

1. Run `AdvPrint-Pro-Setup-2.7.0.exe` over the old install (settings
   + history migrate automatically) — Linux: `sudo dpkg -i advprint-pro_2.7.0_all.deb`.
2. Chrome → `chrome://extensions` → AdvPrint Pro → **Reload**.
3. Open the dashboard → the **Job history** section: filter, tick,
   reprint — done.
