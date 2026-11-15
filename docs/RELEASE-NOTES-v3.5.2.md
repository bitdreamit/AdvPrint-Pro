# AdvPrint Pro v3.5.2 - Release Notes

**Dashboard data you can trust - real success rate, no save-password
prompts, date+time everywhere, history View button + date filter.**
by Bit Dream IT - Innovative Healthcare Solutions

## The report

> "3.5.1 fine. need update dashboard success rate also now fake,
> search area anything search it browser take password save like
> suppose search title placeholder='Search title / printer / #id' or
> anywhere insert text it browser show save password this search as
> username and token treat as password - this is very bad and problem
> working. In visitor title time need show date and time both needed.
> Any option button to view file also is it possible in history, and
> extra filter date wise also add. Update new version v3.5.2."

Five real issues, all fixed in this release. No print / rule / queue /
theme / network logic was touched - everything else is exactly the
working v3.5.1 build.

## 1. The success rate was still not honest ("now fake")

v3.5.1 made every dashboard CARD live, but the **Success Rate KPI**
kept the old math: only `status='printed'` counted as success over the
7-day window. Two everyday situations freeze that number:

- a hub that delivers most jobs as **saved files** (Save as PDF
  workflows, Share Send Mode) - `saved` jobs were invisible to the
  rate, so it sat at whatever printed/failed ratio the week held;
- a printer that is **offline** - jobs fail, the rate sinks, and once
  the bad jobs leave the 7-day window it snaps back - it never
  describes "how is my printing going right now".

A number that never moves reads as fake even when it is technically
real - the user is right to call it that.

**The v3.5.2 math (`db_stats()`):**

| Outcome                | Counts as          | In the rate? |
|------------------------|--------------------|--------------|
| `printed`              | success            | yes          |
| `saved` (file)         | success            | yes - a saved file IS a delivered document |
| `failed` / `dead`      | failure            | yes          |
| `canceled`             | user action        | NO - excluded (it is not a printer outcome) |

`/stats` now returns every count: `printed_7d`, `saved_7d`,
`failed_7d`, `canceled_7d`, `total_7d` next to `success_rate`.

**The tile shows the numbers BEHIND the percentage.** The small label
above the % now reads `7d 14 ok / 2 fail` (was the static text
"7 days") and the hover tooltip spells out the whole calculation:
`last 7 days: 14 printed + 2 saved = 16 ok, 2 failed/dead -> 88.9% of
18 finished (3 canceled not counted)`. If it ever says 33.3% again,
the tooltip says exactly which jobs made it so.

## 2. The browser offered to SAVE A PASSWORD when you searched

**Root cause:** the Connections tab token boxes (Self PC Token + LAN
PC token) were real `type="password"` fields. Chrome's credential
heuristics pair text inputs with password fields ON THE SAME PAGE -
so typing into the history SEARCH box (or the Hub URL box, or any
text box) made the browser pop "save password?" with the SEARCH TEXT
as the user name and the hub token as the password. Nothing is ever
submitted anywhere; it was pure field-pairing noise - but it trained
the user to distrust the console.

**The fix:**

- both token boxes are ordinary text inputs now, masked by CSS
  (`-webkit-text-security: disc`) - the browser never sees a password
  field, so it can never offer to save one;
- the Self PC token box (`id="selfTokenInp"`) **auto-fills the REAL
  hub token** at boot (the old markup carried a static demo token
  that never changed - one more fake value gone); "Detect token"
  re-fills it on click;
- `autocomplete="off"` is set on EVERY text / search / date input at
  boot (and in the markup), the token-entry modal included;
- the old `/dashboard` page search box gets it too;
- Firefox ignores `-webkit-text-security` (shows the token in plain
  text) - acceptable for an owner-only console page, noted in the CSS
  comment.

## 3. DATE + TIME in every row ("need show date and time both")

History rows, the dashboard Recent Jobs list, the Audit (visitor)
rows, the LAN visitors' first/last hit columns, the DropZone activity
list and the /debug problem rows used to slice the timestamp to the
TIME ONLY (`14:19:41`) - yesterday's jobs looked like they happened
today. All of them show the full `YYYY-MM-DD HH:MM:SS` now. (Log-panel
lines and the paired-PC schedule time stay time-of-day on purpose.)

## 4. History: per-row VIEW file button ("any option button to view file")

Every finished job that still has its stored file on disk gets a
**View** button next to Reprint. It opens
`/jobs/<id>/file?view=1&token=...` in a new tab:

- `_send_file()` learned `inline=True` and answers
  `Content-Disposition: inline`, so the BROWSER's PDF viewer shows
  the document - no download prompt;
- the default stays `attachment` (download) for every existing link;
- raw `.prn` spool files get no View button (no browser viewer);
- the endpoint is still token-gated like every other GET route.

## 5. History: date-wise filter ("extra filter date wise also add")

The filter row now has **From / To date inputs + a Clear dates
button**. While a date is set, the table renders from a server query
- `/jobs?limit=200&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` - instead
of filtering only the last-100 rows the poll fetched:

- `db_list()` grew optional `date_from` / `date_to` parameters
  (`substr(created_at,1,10) BETWEEN`, inclusive on both ends);
- the `/jobs` route validates both with a strict `YYYY-MM-DD` regex -
  bad values are ignored, never a 500;
- the card caption reads `date filter 2026-11-01 -> 2026-11-15 ·
  N match(es) of M` while active;
- Clearing the dates falls back to the live poll list instantly.

## How to verify (3 minutes)

1. Open `http://127.0.0.1:9235/ui` -> Dashboard:
   - the Success Rate tile shows `7d N ok / M fail` with YOUR counts -
     hover it for the full breakdown; print a few pages and watch the
     counts move on the next poll;
2. History tab:
   - finished rows with a stored file show a `View` button - click it,
     the PDF opens inline in a new tab;
   - pick From / To dates - the caption switches to
     `date filter ... N match(es)` and the rows come from the WHOLE
     database; Clear dates returns to the live list;
   - the Time column shows date AND time;
3. Connections tab: the Token box shows your real token (masked) -
   and typing in the history search box does NOT trigger any browser
   save-password offer any more;
4. `http://127.0.0.1:9235/health` reports `"version": "3.5.2"`;
5. Automated: `python3 tests/test_v352.py` (20 checks: success-rate
   math, no password fields, autocomplete sweep, date+time renders,
   View endpoint inline disposition, date-filter route + SQL, copy
   coherence, version 3.5.2 everywhere, v3.5.1/v3.5.0 features
   untouched).

## Files

- `tool/unix/hub/advprint.py` (+ windows/portable + installer/stage
  copies, byte-identical) - `db_stats()` success math, `db_list()`
  date filter, `/jobs` date params, `_send_file(inline=)`,
  `/jobs/<id>/file?view=1`, version 3.5.2, embedded console rebuilt
  from the new console.html.
- `tool/unix/hub/console.html` (+ windows/portable + installer/stage
  copies, byte-identical) - KPI counts + tooltip, CSS-masked token
  boxes + autocomplete sweep, date+time renders, View button, date
  filter UI.
- `extension/*` - version 3.5.2 (manifest, popup, i18n EN+BN, api.js
  fallback); the embedded signed CRX rebuilt at 3.5.2 (Chrome
  auto-update needs the higher version).
- `tests/test_v352.py` - locks all of the above.
- `CHANGELOG.md` / this file / `START-HERE.txt` / `README.md` /
  `installer/setup.nsi` / `installer/deb/DEBIAN/control` /
  `VERSION.txt` - version + feature text updated.
- `download/AdvPrint-Pro-Console-UI-Template-v3.5.2-ProTheme.html` -
  the same UI as a standalone theme template (TEMPLATE PREVIEW chip
  when the hub is offline).
