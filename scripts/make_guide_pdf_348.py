#!/usr/bin/env python3
"""Update docs/AdvPrint-Pro-Full-Guide.html to v3.4.8 (base 3.4.7 as
the user asked) and render docs/AdvPrint-Pro-Full-Guide.pdf."""

import os

ROOT = "/home/z/my-project/ap348-src"
P = os.path.join(ROOT, "docs", "AdvPrint-Pro-Full-Guide.html")
s = open(P, encoding="utf-8").read()

# 1) cover version
s = s.replace("Version 3.0.7 — Enterprise Edition<br>",
              "Version 3.4.8 — Enterprise Edition<br>", 1)

# 2) TOC row for the new section
s = s.replace(
    '<tr><td class="n">14</td><td>Upgrade, uninstall, files &amp; folders</td></tr>',
    '<tr><td class="n">14</td><td>Upgrade, uninstall, files &amp; folders</td></tr>\n'
    '    <tr><td class="n">15</td><td>Recent releases — 3.4.6 · 3.4.7 · 3.4.8 '
    '(one port · configurable hub port · strict LAN · rules that really match · '
    'the rules-table fix)</td></tr>', 1)

# 3) section 6.6 note: the v3.4.8 rules editor + table state
old66 = 'Full worked example + API snippets: <span class="mono">docs/MULTI-PRINTER.md</span>\n(ships in this package).</p>'
new66 = ('Full worked example + API snippets: <span class="mono">docs/MULTI-PRINTER.md</span>\n'
         '(ships in this package).</p>\n'
         '<div class="note" style="border:1px solid #bfdbfe;background:#eff6ff;border-radius:10px;'
         'padding:12px 14px;margin:10px 0 0">'
         '<b>v3.4.8 — THE RULES TABLE FITS AND SAVES REAL KINDS.</b> The ONE UI rules table '
         '(Rule · URL / address filter · Match by · Page content · URL type · Printer · '
         'What to print · Cpl · Paper · On · Auto · Runs) no longer pushes the Edit/Del '
         'buttons outside the card when Paper or another extra is selected: headers wrap, '
         'the table is compact, long pattern / content cells clamp with an ellipsis and every '
         'ONE UI table scrolls horizontally INSIDE its card as a last resort. The rule editor '
         'saves real URL types now (PDF link / Web page / Plain text / ZPL label page / '
         'Image page / Any — the old editor saved a shifted kind, so "Web page" rules could '
         'never fire), legacy <span class="mono">web</span> rules read as '
         '<span class="mono">html</span> in both matchers, the Runs column shows "last HH:MM" '
         'again, and <span class="mono">/rules/test?url=...&amp;kind=...</span> honors kind + '
         'title on the GET form too.</div>')
assert old66 in s
s = s.replace(old66, new66, 1)

# 4) new section 15 before </body> (after section 14)
section15 = '''
<!-- ============ 15 ============ -->
<h2>15. Recent releases — 3.4.6 · 3.4.7 · 3.4.8</h2>
<p>These three releases re-built the console around ONE hub port and a
rule engine you can actually verify. Everything below ships in this
package; the per-release developer guides live in <span class="mono">docs/</span>
and the full change log in <span class="mono">CHANGELOG.md</span>.</p>

<h3>15.1 v3.4.6 — ONE port for every queue + the popup remembers the last printer</h3>
<ul>
<li><b>One TCP port (9235)</b> serves every printer for every PC — exactly like a CUPS
server: the queues are distinguished by their full IPP URI
(<span class="mono">/ipp/print</span> = the default queue,
<span class="mono">/ipp/print/&lt;printer&gt;</span> = that one printer) plus a unique
per-queue identity. One firewall rule, no port exhaustion, every printer still adds side
by side. IPP printing, RAW 9100 and mDNS stay.</li>
<li><b>The popup printer selector</b> shows the hub's REAL default and remembers the last
printer you picked (restored on the next popup open; picking another printer makes THAT
the OS default, idempotent since v3.3.4).</li>
</ul>

<h3>15.2 v3.4.7 — Configurable hub port · DropZone watch fix · Strict LAN share · URL rules that really match</h3>
<ul>
<li><b>The hub port is configurable</b> (default 9235): ONE UI → Settings → HUB PORT
saves for real now, or <span class="mono">python advprint.py port 9300</span>,
<span class="mono">"port"</span> in config.json, or <span class="mono">ADVPRINT_PORT</span>
(wins). Validated 1024–65535 with 631 / 5353 / 9100 refused; applied on restart; every URL
(browser, other PCs, IPP printer URL) follows the new port.</li>
<li><b>The DropZone watch button really toggles</b> (the old button always sent
<span class="mono">drop_enabled:false</span> — the watch could never be turned on).</li>
<li><b>Strict LAN share</b> (<span class="mono">lan_strict</span>): while ON the hub records
EVERY distinct client IP that touches it — even refused ones — and the LAN panel lists each
IP with hit count and a one-click <b>Allow</b> (the first Allow replaces <span class="mono">*</span>
and locks the hub down). Endpoints: <span class="mono">GET /lan/hits</span>,
<span class="mono">POST /lan/allow</span>, <span class="mono">POST /lan/hits/clear</span>.</li>
<li><b>URL rules that really match:</b> the ONE UI editor gained the pattern TYPE select
(<b>glob</b> <span class="mono">*</span> wildcards · <b>regex</b> for dynamic ids ·
<b>contains</b> plain text) — the hub keeps the field it used to strip — plus ready recipes
(the htncr.org lab set) and a REAL test engine: <span class="mono">POST /rules/test</span>
or the "Which rule fires?" box answers the winning rule + printer without printing.
See <span class="mono">docs/PRINT-RULES-RECIPES.md</span>.</li>
</ul>

<h3>15.3 v3.4.8 — The rules table fits · real kinds · run bookkeeping (this release)</h3>
<ul>
<li><b>The rules table never pushes Edit/Del outside again</b> — the reported bug: with
Paper or another extra selected the 14 nowrap headers forced a 1145 px table inside a
990 px card and the Edit button rendered outside the card border. Fixed at the root:
headers wrap, the table is compact, long pattern / content cells clamp with an ellipsis
(measured after the fix: table 990 = card 990, overflow 0) and EVERY ONE UI table sits in
a horizontal-scroll <span class="mono">.tbl-wrap</span> inside its card as a last resort.</li>
<li><b>The rule editor saves real URL types</b> — PDF link / Web page / Plain text /
<b>ZPL label page / Image page</b> / Any with real values (the old editor saved a shifted
kind: "Web page" stored <span class="mono">web</span>, a kind no page ever reports, so such
rules could never fire). Legacy <span class="mono">web</span> rules read as
<span class="mono">html</span> in BOTH matchers; a content rule left on Any defaults to
<span class="mono">html</span>.</li>
<li><b>Run bookkeeping synced</b> — the Runs column shows "12 runs · last 14:22" again:
<span class="mono">last_run</span> rides along with the extension's rules push and the hub
cleaner keeps it (plus the title filter) on central edits.</li>
<li><b><span class="mono">/rules/test</span> GET/POST parity</b> — the GET form honors
<span class="mono">&amp;kind=</span> and <span class="mono">&amp;title=</span> too.</li>
<li><b>Full A-to-Z audit:</b> 666 pytest tests green; an independent JS wiring audit of the
ONE UI + dashboard found 0 undefined calls, 0 missing/duplicate ids, 0 unsubstituted
placeholders; the two hub copies stay byte-identical with the embedded console fresh.</li>
</ul>
</body>'''
assert s.count("</body>") == 1
s = s.replace("</body>", section15, 1)

open(P, "w", encoding="utf-8").write(s)
print("guide html updated:", len(s), "bytes")

# ---------- render to PDF with Chromium (print CSS background) ----------
from playwright.sync_api import sync_playwright

out = os.path.join(ROOT, "docs", "AdvPrint-Pro-Full-Guide.pdf")
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page()
    pg.goto("file://" + P, wait_until="networkidle", timeout=60000)
    pg.pdf(path=out, format="A4", print_background=True,
           margin={"top": "14mm", "bottom": "14mm",
                   "left": "12mm", "right": "12mm"})
    b.close()
print("pdf written:", out, os.path.getsize(out), "bytes")
