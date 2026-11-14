# AdvPrint Pro v3.4.8 — A-to-Z DEVELOPMENT & BUILD GUIDE

AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare
Solutions. This guide covers ONLY the v3.4.8 delta on top of v3.4.7.
Read `AdvPrint-Pro-v3.4.7-A-to-Z-DEV-GUIDE.md` first (configurable hub
port + DropZone watch toggle + strict LAN share + URL rules that really
match) and `AdvPrint-Pro-v3.4.6-A-to-Z-DEV-GUIDE.md` (one port for
every queue + the popup printer memory); everything there still
applies except where this file says otherwise.

---

## 0. The one-paragraph delta

v3.4.8 is the final-polish release. **(1) The rules table fits** —
the user's reported bug ("edit button goes outside when paper or
other extra selected") is fixed at the root: the 14 nowrap headers
used to force a 1145px table inside a 990px card; headers wrap now,
the rules table is compact, long pattern/content cells clamp with an
ellipsis, and every ONE UI table sits in a `.tbl-wrap` horizontal
scroll container as a last resort (13/13 wrapped). **(2) The rule
editor saves real kinds** — the URL-type select used a SHIFTED
positional array and saved `web`, a kind no page ever reports; it
carries values now (pdf/web/text/zpl/image/""), ZPL + Image joined,
legacy `web` reads as `html` in BOTH matchers, and a content rule on
Any defaults to html. **(3) Run bookkeeping is synced** — `last_run`
rides along with the extension's rules push and the hub cleaner keeps
`title` + `last_run`. **(4) `/rules/test` GET/POST parity** — the GET
form honors `&kind=` + `&title=` now.

## 1. The files that must stay in sync (edit BOTH, always)

```
tool/unix/hub/advprint.py              <- the canonical hub
tool/windows/portable/hub/advprint.py  <- byte-identical copy
                                          (tests/conftest.py imports
                                           THIS one - a stale copy runs
                                           the WRONG code in tests)
tool/unix/hub/console.html             <- THE ONE UI source
tool/windows/portable/hub/console.html <- mirrored by embed script
```

The v3.4.8 workflow that keeps everything consistent (used for this
release — edit the CONSOLE_HTML inside the unix advprint.py, then
sync BACK out to console.html, then re-embed into BOTH copies):

```
# 1. edit tool/unix/hub/advprint.py (CONSOLE_HTML region + python code)
# 2. sync back out to the standalone console.html:
python3 - <<'EOF'
src = open('tool/unix/hub/advprint.py', encoding='utf-8').read()
OPEN = 'CONSOLE_HTML = r"""'
i = src.find(OPEN); j = src.find('\n"""', i + len(OPEN))
open('tool/unix/hub/console.html', 'w', encoding='utf-8').write(src[i+len(OPEN):j])
EOF
# 3. re-embed into BOTH advprint.py copies + mirror console.html:
python3 scripts/embed_console.py
# 4. the python-side edits (matcher, cleaner, endpoints) exist only in
#    the unix copy - copy it over the windows one:
cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py
md5sum tool/*/hub/advprint.py     # must be identical
```

Extension files (`extension/`) are packed by the build; there is no
second copy since v3.2.8.

## 2. v3.4.8 code map (delta only)

### Fix 1 — the rules table fits (the reported bug)

| Where | What |
| --- | --- |
| ONE UI CSS `.tbl th` | `white-space:normal` + `vertical-align:bottom` — headers may wrap (the old nowrap forced 1145px) |
| ONE UI CSS `.tbl-wrap` | NEW: `overflow-x:auto` — the horizontal scroll container |
| ONE UI CSS `.tbl.compact` | NEW: `padding:6px 6px` cells + `.doc` clamp 118px for the 14-column rules table |
| ONE UI rules table markup | `class="tbl compact"`, min-widths shrunken (Rule 84→58, URL 110→80, Printer 90→70, Cpl 30→26, Paper 40→46, Runs 58→52, edit col 86→84), wrapped in `<div class="tbl-wrap">` |
| ALL 13 ONE UI `table.tbl` | wrapped in `.tbl-wrap` by `scripts/wrap_tables_348.py` (idempotent) |
| `renderRules()` td[4] | page-content cell gets `className="doc"` + `max-width:100px` inline — long "must contain" text clamps with an ellipsis (the class sits on the TD; inline spans do not clip) |

### Fix 2 — the rule editor saves real kinds

| Where | What |
| --- | --- |
| ONE UI `#re-type` select | options carry VALUES now: `pdf` / `web` / `text` / `zpl` / `image` / `""` (Any); ZPL label page + Image page are new picks |
| ONE UI `saveRule()` | value-based kind IIFE: `web`→`html` normalization, whitelist `["pdf","html","text","zpl","image",""]`, content rule on Any defaults to `html`; `match` no longer reads a select index |
| ONE UI `openRuleEditor()` | sets `#re-type` by VALUE (kind), not by label; legacy `web` shows as Web page and saves back as `html` |
| ONE UI `KIND_LABELS` | gains `html: "Web page"`, `zpl: "ZPL label page"`, `image: "Image page"` (legacy `web` kept for display) |
| `extension/background.js` `matchRule()` | legacy alias: `const wantKind = r.kind === "web" ? "html" : r.kind;` |
| hub `rule_matches()` | same alias (rules saved by older builds start matching html pages) |
| `extension/managed.json` | unchanged (policy schema has no kind field) |

Detected kinds (unchanged, `detectTabKind`): `pdf` | `image` | `zpl` |
`text` | `html`. There was NEVER a `web` kind — that was the bug.

### Fix 3 — run bookkeeping synced

| Where | What |
| --- | --- |
| `extension/background.js` `rulesWithRuns()` | pushes `last_run: (s && s.lastRun) || r.last_run || ""` together with the runs counter |
| hub rules_mirror cleaner (POST /config) | keeps `title` (≤120 chars) + `last_run` (≤32 chars) on central edits |
| ONE UI `renderRules()` td[12] | unchanged — already rendered `r.last_run` as "last HH:MM"; it just never received the field |

### Fix 4 — `/rules/test` GET/POST parity

| Where | What |
| --- | --- |
| `GET /rules/test` | honors `&title=` (≤200) + `&kind=` (≤16) exactly like the POST body — content rules are testable from the browser bar now |

## 3. Tests

`tests/test_v348.py` locks every item (17 tests):

- table fit: the rules table is `tbl compact` inside a `.tbl-wrap`,
  all 13 ONE UI tables are wrapped (each immediately preceded by its
  wrapper), headers wrap, compact CSS present, rendered cells clamp,
  the user's 12 column labels are all still in the header;
- kinds: the select values, the saveRule IIFE (`web`→`html`,
  content→`html` default, the OLD positional array is GONE),
  open-by-value, KIND_LABELS coverage, hub matcher alias semantics
  (unit), extension alias string, `/rules/test` end-to-end with a
  legacy `web` rule (`kind=html` fires, `kind=text` does not);
- bookkeeping: cleaner keeps `title` + `last_run` (round-trip through
  POST /config), extension pushes `last_run`;
- `/rules/test` GET form passes kind + title;
- version coherence 3.4.8 (VERSION, VERSION_NAME, VERSION.txt,
  manifest, NSIS, popup badge, i18n brandLines en+bn, api.js
  fallback, console fallback) + the two hub copies byte-identical and
  the embedded console fresh.

NOTE: the endpoint test cleans its `rules_mirror` up in a `finally`
block — a leftover catch-all rule would re-route the worker tests
that run after it (session-scoped hub fixture).

Run: `python3 -m pytest tests/ -q` (the full suite; v3.4.8 alone:
`python3 -m pytest tests/test_v348.py -q`). The three CRX-version
anchors (`test_v328.py`) go green only AFTER `build-all.sh` re-signed
the 3.4.8 CRX and synced every embedded copy.

## 4. Build

Same chain as every release:

```
python3 scripts/embed_console.py
cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py
bash scripts/build-all.sh          # -> dist/: Setup exe, deb, CRX, zips, SHA256SUMS
```

Then copy `dist/*3.4.8*` + the docs to `download/`, zip the FULL
package, and render the UI previews (the rules table WITH the Edit
buttons visible is the release screenshot: `scripts/fix348-*.png`).
