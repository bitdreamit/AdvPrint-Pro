# Print Rules — URL Recipes Guide

**AdvPrint Pro v3.4.8** · by Bit Dream IT - Innovative Healthcare Solutions

> **v3.4.8 kind fix** — the ONE UI editor's URL TYPE select saves real kinds now: PDF link = `pdf`, Web page = `html`, Plain text / stream = `text`, **ZPL label page = `zpl`, Image page = `image`**, Any = any kind. Rules saved by older builds with the dead kind `web` read as `html` in both matchers (they start working). A content rule left on Any defaults to `html`.

How to route ANY page to ANY printer by its address — including pages with
dynamic ids, query arrays, several printer targets on one domain — and how
to PROVE a rule works before you trust it. Everything here is managed in
one place: **ONE UI → Auto-Print Rules** (the hub console at `/ui`), and
the browser extension adopts the rules automatically.

---

## 1. How the rule engine works (30 seconds)

- Rules live in the hub config (`rules_mirror`) and are **mirrored into
  every paired browser**; the extension evaluates them when a tab is
  auto-printed or printed from the popup.
- Rules run **top to bottom — first match wins**. A page that matches NO
  rule prints through the normal pipeline with the **OS default printer**
  (that is the "no check needed" fall-through you asked for).
- Each rule has:
  - **pattern** — the URL filter text,
  - **type** — how the pattern is read (this is the v3.4.7 fix — the hub
    used to strip this field, so every rule silently degraded to a glob):
    - **Glob** — `*` = anything. Easiest. `*://www.htncr.org/lab/*`
    - **Regex** — a real regular expression (case-insensitive). Needed for
      dynamic ids, alternations, end anchors.
    - **Contains** — the URL only has to CONTAIN the text. Zero learning.
  - optional **page content** text and **URL type** (any / PDF link / web
    page / plain text) — extra conditions, all must pass,
  - the **printer**, **what to print** (whole page / linked PDF / raw
    ZPL stream / selected element), **copies**, **paper**,
  - **On** + **Auto** switches (Auto = silent printing, no dialog).

## 2. The four lab recipes (htncr.org), verbatim

These are built into the rule editor as the **"load a ready recipe…"
dropdown** — load one, pick your printer, save, test.

### Recipe A — a report with ONE test id → the report printer

```
URL:  https://www.htncr.org/lab/medical_reports/pdf/203182?tests%5B%5D=671839
```

| Field   | Value |
|---------|-------|
| Type    | `regex` |
| Pattern | `htncr\.org/lab/medical_reports/pdf/\d+\?tests%5B%5D=\d+$` |
| Printer | your report printer |
| Action  | Entire web page (or Linked PDF only if the URL IS the pdf) |

Why it works:
- `\d+` = the **dynamic** report id (`203182`) and the **dynamic** test id
  (`671839`) — the rule keeps working for every new id, no per-id rules.
- `\?` = a literal `?`. Browsers keep `%5B%5D` in the address bar — that is
  the encoding of `tests[]`, so the pattern must match `%5B%5D`, not `[]`.
- the trailing **`$` anchor** is the trick that separates ONE test id from
  MANY: a multi-test URL contains `&tests%5B%5D=...` after the first id, so
  it does NOT end in a single id and this pattern refuses it.

### Recipe B — a report with MANY test ids → default A4 (no rule at all)

```
URL:  https://www.htncr.org/lab/medical_reports/pdf/203182?tests%5B%5D=671843&tests%5B%5D=671840&...
```

**Create no rule.** The multi-test URL does not match Recipe A (the `$`
anchor), so it falls through to the OS default printer with A4 — exactly
"normally default, so no check needed". If you ever want to be explicit
anyway (e.g. to force paper), use a regex that REQUIRES a second id:

```
Type: regex    Pattern: tests%5B%5D=\d+&tests%5B%5D=\d+    Printer: (your A4)
```

Order matters: put Recipe A ABOVE this one if you use the explicit form.

### Recipe C — sample pages → the Zebra ZPL printer

```
URL:  https://www.htncr.org/lab/sample/203182
```

| Field   | Value |
|---------|-------|
| Type    | `regex` |
| Pattern | `htncr\.org/lab/sample/\d+$` |
| Printer | your Zebra |
| Action  | Raw text / ZPL / ESC-POS stream (the page prints as the label it is) |

`\d+$` again = any sample id. If the page body actually contains ZPL
(`^XA … ^XZ`), you can also use a **content rule** instead: match by
content kind `ZPL` with no URL at all — the extension detects the ZPL
signature by itself. Content rules are immune to URL changes.

### Recipe D — receipt printing (client / all / lab / admin) → the A5 printer

```
URL:  https://www.htncr.org/lab/receipt-print/203695/client
      (…/all, …/lab, …/admin — same rule)
```

| Field   | Value |
|---------|-------|
| Type    | `regex` |
| Pattern | `htncr\.org/lab/receipt-print/\d+/(client|all|lab|admin)$` |
| Printer | your A5 receipt printer |
| Action  | Entire web page |

`(client|all|lab|admin)` = an **alternation** — one rule covers every
variant. Add more roles by extending the group: `(client|all|lab|admin|doctor)`.

### Same idea on any domain

- Lock a rule to ONE domain: start the pattern with the host, e.g.
  `htncr\.org/...` (regex) or `*://www.htncr.org/*` (glob). Other sites
  can never fire the rule.
- Whole-site rule: glob `*://www.htncr.org/*`.
- Only PDF links anywhere: glob `*://*/*.pdf`.
- Just a word in the URL: contains, e.g. `receipt-print`.

## 3. Prove it before you trust it — three ways

1. **The Test box** (ONE UI → Auto-Print Rules → "Test which rule fires"):
   paste the address, press **Which rule fires?** — the hub answers which
   rule matches and which printer it selects, or "no rule → OS default".
   The second row simulates a detected page kind (ZPL / PDF / image /
   plain text / web page) for content rules. Nothing is printed.
2. **The API** — same engine, scriptable:

   ```
   POST /rules/test        body {"url": "https://www.htncr.org/lab/sample/203182"}
   GET  /rules/test?url=https%3A%2F%2Fwww.htncr.org%2Flab%2Fsample%2F203182
   ```

   Answer: `{"ok":true,"matched":true,"rule":{...},"printer":"Zebra …"}`
   or `{"ok":true,"matched":false,"printer":"OS default printer",...}`.
3. **The activity log** — every real firing is counted per rule (runs +
   last run) in the rules table, and the last 100 rule jobs are in the
   extension's Options → Rules activity log.

## 4. Rules for the same PC vs other PCs

- Rules are edited ONCE in the hub's ONE UI. They are stored centrally
  (`rules_mirror`) and every paired browser on that PC adopts them on its
  next sync (extension ⇄ hub, automatic).
- The hub's own rule mirror also powers the **/rules/test** endpoint, so
  what you test at the hub is exactly what the browsers run.
- Paper size: the PRINTER normally decides the paper (your A5 printer
  prints A5). A rule can additionally force paper/copies/color/duplex.

## 5. Quick syntax reference

| You want | Type | Pattern |
|---|---|---|
| One page kind of URL, any id | regex | `htncr\.org/lab/sample/\d+$` |
| One exact URL | contains | `lab/receipt-print/203695/client` |
| A section of a site | glob | `*://www.htncr.org/lab/*` |
| A query param with any value | regex | `\?patient=\d+` |
| `tests[]` with ONE id | regex | `tests%5B%5D=\d+$` |
| `tests[]` with 2+ ids | regex | `tests%5B%5D=\d+&tests%5B%5D=\d+` |
| Several path variants | regex | `/(client\|all\|lab\|admin)$` |
| Any PDF link | glob | `*://*/*.pdf` |

Notes: regexes are case-insensitive; a bad regex simply never matches (it
cannot break printing); `*` in glob is "anything"; URLs are matched the
way the browser's address bar shows them (already percent-encoded).

## 6. Where the pieces live (for developers)

| Piece | File / endpoint |
|---|---|
| Rule storage | `config.json` → `rules_mirror` (hub) ⇄ chrome.storage (extension) |
| Extension matcher | `extension/background.js` → `patternToRegex()` + `matchRule()` |
| Hub mirror of the matcher | `tool/unix/hub/advprint.py` → `rule_pattern_to_regex()` / `rule_matches()` / `evaluate_rules()` |
| Test endpoint | `POST /rules/test`, `GET /rules/test?url=…` (token-protected like every endpoint) |
| ONE UI editor | Rules panel → New rule / Edit → pattern type select + recipe dropdown |
