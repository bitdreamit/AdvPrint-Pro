# v3.4.8 - RULES TABLE FITS + RULE EDITOR SAVES REAL KINDS + RUN BOOKKEEPING SYNCED (2026-11-14)

**Base: v3.4.7** — the configurable hub port, the DropZone watch
toggle, strict LAN share with the IP hit list, URL rules that really
match (glob / regex / contains + `/rules/test`) and the clean UI notes
all stay. v3.4.8 is the FINAL-POLISH release: the reported layout bug
is fixed at the root and the full A-to-Z audit fixed every remaining
gap it found. Every item is locked by `tests/test_v348.py` (17 tests).

---

## 1. The rules table never pushes Edit/Del outside again (the reported bug)

**You reported:** the Rules table columns *"Rule / URL / address
filter / Match by / Page content / URL type / Printer / What to print /
Cpl / Paper / On / Auto / Runs"* — *"th so td outside when paper or
other extra selected edit button goes outside."*

**Measured root cause (v3.4.7):** the 14 column headers could not wrap
(`white-space:nowrap`) and the cell padding was generous, so the table
forced a **1145 px minimum width inside a 990 px card**. The Runs
column and the **Edit/Del buttons rendered OUTSIDE the card border**
(edit button right edge 1399 px vs card right edge 1245 px) — with
Paper ("58mm receipt", "4×6″ label") or a long page-content filter
selected the rows just got taller and it looked even worse.

**The fix — three layers, so it can never come back:**

1. **The table fits.** Headers may wrap to a second line now, the
   rules table is `compact` (tighter cells, shrunken min-widths) and
   the long pattern / page-content cells clamp with an ellipsis.
   Measured after the fix: table 990 px = card 990 px, **overflow 0**,
   Edit button fully inside.
2. **A scroll safety net.** EVERY ONE UI table (13 of them — rules,
   activity log, queue, history, dashboard, audit, LAN hits,
   connections, dropzone, extension, debug) sits in a `.tbl-wrap`
   that scrolls horizontally INSIDE the card as a last resort. On a
   very narrow window you scroll within the card — a button can never
   again render outside the visible area.
3. **Same look, same columns.** The header still reads exactly
   Rule / URL / address filter / Match by / Page content / URL type /
   Printer / What to print / Cpl / Paper / On / Auto / Runs (plus the
   edit column) — nothing was removed to make it fit.

## 2. The rule editor saves REAL URL types (A-to-Z audit gap #1)

The ONE UI rule editor's URL TYPE select was saved through a **shifted
positional array** (`["", "pdf", "web", "text"]` against the options
PDF link / Web page / Plain text / stream / Any):

| You picked | v3.4.7 saved | Effect |
|---|---|---|
| PDF link | `""` (Any) | type shown as Any |
| Web page | `"pdf"` | a content rule matched only PDF pages |
| Plain text / stream | `"web"` | **never matched anything** — no page is ever detected as "web" (the browser answers `html`) |
| Any | `"text"` | matched only text/plain pages |

Fixed: the select now carries real **values** (`pdf / web / text / zpl
/ image / ""`), **ZPL label page** and **Image page** joined the list
(the extension detects both), `web` normalizes to `html` on save, and
a content rule left on **Any** defaults to `html` (a content rule
without a kind is skipped by the matchers). Rules saved by older
builds with the dead kind `web` **start working** — BOTH matchers
(extension `matchRule` + hub `rule_matches`) alias `web` → `html`.

## 3. Run bookkeeping reaches the ONE UI (A-to-Z audit gap #2)

The extension tracked `lastRun` but pushed only the counter to the
hub, and the hub's rules cleaner dropped `last_run` (and the `title`
filter) — so the Runs column could show "128 runs" but never the
promised "last 14:22". Now `last_run` rides along with every push and
the cleaner keeps `title` + `last_run` on central edits.

## 4. `/rules/test` GET form honors `kind` + `title` (A-to-Z audit gap #3)

The POST form passed both, the GET form silently dropped them — a
content rule could never be tested from the browser bar
(`/rules/test?url=...&kind=html`). Both forms behave identically now.

## 5. The A-to-Z audit verdict

- Full pytest suite: **680 tests** green after the release build
  (17 new v3.4.8 locks included).
- Independent JS wiring audit of the ONE UI + classic dashboard:
  0 undefined function calls, 0 missing ids, 0 duplicate ids,
  0 unsubstituted placeholders, 0 JS syntax errors.
- The two hub copies (`tool/unix/hub/advprint.py`,
  `tool/windows/portable/hub/advprint.py`) stay byte-identical and
  the embedded console matches `console.html`.
- The popup printer memory (v3.4.6), one-port IPP path routing,
  configurable hub port, strict LAN share and the rule test engine
  are all verified unchanged.

## Files

- Hub: `tool/unix/hub/advprint.py` + `tool/windows/portable/hub/advprint.py` (byte-identical), `console.html` embedded
- Extension: `background.js` (kind alias + last_run push), manifest 3.4.8
- Tests: `tests/test_v348.py`
- Docs: this file, `CHANGELOG.md`, `README.md`,
  `docs/AdvPrint-Pro-v3.4.8-A-to-Z-DEV-GUIDE.md`,
  `docs/PRINT-RULES-RECIPES.md` (kind note), the regenerated
  `docs/AdvPrint-Pro-Full-Guide.pdf`
