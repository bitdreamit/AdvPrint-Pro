# AdvPrint Pro v3.4.7 — A-to-Z DEVELOPMENT & BUILD GUIDE

AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare
Solutions. This guide covers ONLY the v3.4.7 delta on top of v3.4.6.
Read `AdvPrint-Pro-v3.4.6-A-to-Z-DEV-GUIDE.md` first (one port for every
queue + the popup printer memory) and `AdvPrint-Pro-v3.3.5-A-to-Z-DEV-GUIDE.md`
for the manual re-scan + auto-CRX machinery; everything there still
applies except where this file says otherwise.

---

## 0. The one-paragraph delta

v3.4.7 ships the user's five asks: **(1) a configurable hub port** —
`port` is a real config key now (default 9235; Settings > HUB PORT saves
for real, `python advprint.py port 9300`, config.json, ADVPRINT_PORT env
wins), validated 1024–65535 with 631/5353/9100 refused, applied on
restart, boot-failure log tells how to move off a busy port;
**(2) the DropZone watch toggle fix** — the ONE UI header button was a
static "Disable" that always posted `drop_enabled:false`; it is a real
Enable/Disable toggle bound by id now; **(3) strict LAN share** — new
`lan_strict` key + `_IP_HITS` ring + `GET /lan/hits` + `POST /lan/allow`
(+ `/lan/hits/clear`): while strict is ON every distinct client IP that
touches the hub (allowed or refused) is listed with a one-click Allow
into `allowed_ips` (first Allow replaces `"*"` = lock-down);
**(4) URL rules that really match** — the hub keeps the rule `type`
field (glob/regex/contains) it used to strip, the editor has a type
select + htncr.org recipe presets, a server-side mirror of the
extension matcher (`rule_pattern_to_regex`/`rule_matches`/
`evaluate_rules`) powers `POST|GET /rules/test`, and the Rules panel
test box is finally wired; **(5) no version prefixes in UI notes** —
24 spots cleaned across the ONE UI + dashboard.

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

After editing console.html ALWAYS run the embed step (it rewrites the
`CONSOLE_HTML` r-string inside BOTH advprint.py copies and mirrors the
html):

```
python3 scripts/embed_console.py
cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py
md5sum tool/*/hub/advprint.py     # must be identical
```

v3.4.7 note: if you edited the CONSOLE_HTML inside advprint.py directly
(the pragmatic path for small UI deltas), sync it BACK into
console.html first, or embed_console.py will overwrite your edits with
the stale source:

```
python3 - <<'EOF'
src = open('tool/unix/hub/advprint.py', encoding='utf-8').read()
OPEN = 'CONSOLE_HTML = r"""'
i = src.find(OPEN); j = src.find('\n"""', i + len(OPEN))
open('tool/unix/hub/console.html', 'w', encoding='utf-8').write(src[i+len(OPEN):j])
EOF
python3 scripts/embed_console.py
```

Extension files (`extension/`) are packed by the build; there is no
second copy since v3.2.8.

## 2. v3.4.7 code map (delta only)

### Feature 1 — configurable hub port

| Where | What |
| --- | --- |
| `CFG["port"]` comment block | sources: ADVPRINT_PORT env > config.json `port` > 9235 |
| `CONFIG_KEYS` / `CONFIG_TYPES` | `"port": int` added — init_config now applies config.json (skipped while `ADVPRINT_PORT` is set) |
| `POST /config` `key == "port"` branch | validation: 1024–65535; 631/5353/9100 refused; response gains `restart:true` + `note` when the port changed vs `_BOOT_PORT` |
| `_BOOT_PORT` global | the port the RUNNING loopback listener bound at boot; set in `cmd_serve`, used by the response note |
| `cmd_serve` bind-failure path | branded `[PORT]` log block: all four ways to move the hub to a free port |
| `cmd_port` + `main()` dispatch + `cmd_help` | new CLI `port [N]` (show / validate / busy-check / save + audit row) |
| ONE UI `#p-settings` | the HUB PORT row is real: `saveSettingsPanel` validates + posts `port`, toast explains the restart + URL follow-up |
| health snapshot | `port` + `lan_strict` fields (Settings panel + strict card read them) |

### Feature 2 — DropZone watch toggle

| Where | What |
| --- | --- |
| ONE UI `#p-dropzone` head button | `<button id="dzWatchBtn">` — label follows state in `loadDropzone` (`dzWatchOn`), click posts the OPPOSITE, stat shows ON/OFF |
| ONE UI dropzone button wiring | the old `btnLike(#p-dropzone, /^Disable$/ ...)` (always-false post) replaced by an id-bound toggle |
| backend | UNCHANGED — `drop_watcher` always ran and re-read the config per poll |

### Feature 3 — strict LAN share + IP hit list

| Where | What |
| --- | --- |
| CFG `lan_strict` (bool, default False) | in CONFIG_KEYS / CONFIG_TYPES / redacted_config / health snapshot |
| `_IP_HITS` + `_ip_hit_record` / `ip_hits_snapshot` / `ip_hits_clear` / `ip_hits_set_allowed` | capped ring (128), threaded, records ONLY while strict is ON |
| `Handler._ip_gate` | computes `allowed` once, records the hit (allowed or denied), then decides exactly as before |
| `GET /lan/hits` | strict + allowed list + newest-first rows |
| `POST /lan/allow` | `{"ip": ...}` add / `{"ip": ..., "remove": true}` remove; replaces `["*"]` on first add (lock-down note); 127.0.0.1 refused; audit `acl.allowed` / `acl.removed` |
| `POST /lan/hits/clear` | resets the ring |
| ONE UI LAN panel | "Strict LAN mode" card: `#strictSwitch`, `#hitsBody` table (per-row Allow/Remove via data attributes), `#hitsClear`, `#hitsRefresh`; `loadLanHits()` runs on poll + `showTab("lan")` |
| classic dashboard `loadLan()` | strict row + inline hits table + `strictToggle` / `lanAllow` / `hitsClearAll` |

### Feature 4 — URL rules that really match

| Where | What |
| --- | --- |
| rules_mirror cleaner | keeps `"type"` (`glob`/`regex`/`contains`, default glob) — THE fix: the old cleaner stripped it, degrading every rule to a glob |
| `RULE_TYPES`, `rule_pattern_to_regex`, `rule_matches`, `evaluate_rules`, `rule_test_result` | server-side mirror of `extension/background.js` `patternToRegex`/`matchRule` (glob anchored `^…$` with `*`→`.*`; regex re.I; contains escaped substring re.I; on/enabled; content rules need the kind; title filter; first match wins) |
| `GET|POST /rules/test` | evaluates rules_mirror, answers the winning rule + printer or no-match (nothing is printed) |
| ONE UI rule editor | `#re-ptype` select + `#re-recipe` presets (`RULE_RECIPES`: single-test report, sample ZPL, receipt A5, whole-domain glob, any-PDF glob, contains) + `saveRule` persists `type`; rules table shows the GLOB/REGEX/CONTAINS chip |
| ONE UI Rules panel test box | `#ruleTestUrl` + `#ruleTestBtn` (+ kind-simulated second row) → `POST /rules/test` → `#ruleTestOut` |
| `extension/managed.json` | rules schema: `type` enum gains `contains` |
| `docs/PRINT-RULES-RECIPES.md` | the URL recipes guide (htncr.org set verbatim) |

### Feature 5 — no version prefixes in UI notes

24 exact-string replacements across CONSOLE_HTML + DASHBOARD_HTML
(panel subs, card-h `.r` spans, notes, dashboard `h2 small`s) — see
`scripts/strip_versions_347.py` for the list; /docs keeps its history.

## 3. Tests

`tests/test_v347.py` locks every item:

- port: CONFIG_KEYS membership, POST validation (bad range, reserved),
  save + restart note, init_config env-wins;
- dropzone: the toggle wiring exists in CONSOLE_HTML (id + opposite-of
  state), `/config drop_enabled` round-trip, old always-false handler
  is gone;
- strict: `_ip_hit_record` cap + records-only-when-strict,
  `/lan/hits` payload, `/lan/allow` add (incl. `*` replacement) +
  remove + loopback refusal, hits clear, `_ip_gate` still denies;
- rules: `rule_pattern_to_regex` glob/regex/contains semantics,
  `evaluate_rules` first-match + off-rule skip, the four htncr.org
  recipes (single-id matches, multi-id falls through, sample→ZPL,
  receipt alternation), `/rules/test` endpoint, type survives the
  cleaner, editor wiring present in CONSOLE_HTML;
- UI hygiene: no `vN.N · ` prefixes left in the ONE UI subs/notes.

Run: `python3 -m pytest tests/ -q` (the full suite; test_v347.py alone:
`python3 -m pytest tests/test_v347.py -q`).

## 4. Build

Same chain as every release:

```
python3 scripts/embed_console.py
cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py
bash scripts/build-all.sh          # -> dist/: Setup exe, deb, CRX, zips, SHA256SUMS
```

Then copy `dist/*3.4.7*` + the docs to `download/` and render the UI
previews (the console panels: Settings port field, LAN strict card,
Rules test box) for the release screenshots.
