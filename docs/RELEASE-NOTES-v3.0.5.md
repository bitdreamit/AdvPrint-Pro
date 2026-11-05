# Release notes - AdvPrint Pro v3.0.5 - RULE MANAGER

**AdvPrint Pro (Advanced Printer) - by Bit Dream IT - Innovative Healthcare Solutions**
2026-11-06 - extension-only release, installs over 3.0.4 / 3.0.3 / 3.0.2
(no settings migration, nothing removed)

## Why

The multi-printer lab rules work **hiddenly**: a matching URL is printed
silently in the background - PDF reports on the A4/A5 laser, ZPL label
pages byte-for-byte on the Zebra, ESC-POS receipts on the thermal
printer - no dialog, no window, no trace in the browser UI. That is
exactly what a lab wants, but a hidden worker also needs a **section in
the extension settings where it is managed and controlled**. User
request: *"this work hiddenly. so this option or rule need section to
managed also controlled - the hidden Multi-printer lab rule also be
controlled/managed through extension setting section so that this tool
be more useful."*

## What's new

### 1. A dedicated Rules tab - the Rule Manager
Options now has a **Rules** tab (Queue | History | **Rules** |
Settings | Debug | LAN/PCs | About). The whole rule table moved there -
pattern, type (glob/regex/**contains**), title filter, printer, action
(Auto/PDF/Page/**ZPL label**/**ESC-POS receipt**), copies, paper, On,
Auto, Copy, Delete - together with the "Printers on this PC" chip strip
(one click **+ rule** per printer), the **+ Add rule** button, the
**Save rules** button, the **Reprint a PDF link** box and the lab
recipe card. One tab = the whole lab.

### 2. Pause ALL rules - one switch
The manager status bar has **Pause all rules** / **Resume all rules**.
Paused = `rulesPaused` in the config: `shouldAutoPrint()` returns null,
so **no rule fires and nothing prints hiddenly** - but every manual
print (popup buttons, right-click menu, the reprint box) keeps working.
The popup's **Power** section carries the same switch with a live
sub-line ("2 rules armed - URLs auto-print hiddenly" / "PAUSED - no
rule auto-prints"). This is the rules counterpart of the queue Pause.

### 3. URL simulator - test without printing
Paste a URL into **Test a URL** and press **Which rule fires?** The
manager answers: rule #, pattern + type, **printer**, action,
copies/paper - and warns when the rule's **On** is off, when **Auto**
is off (manual-only), and when **all rules are paused**. If no rule
matches it says so and mentions Simple mode. The simulator only
matches: nothing is printed, no tab opens, the 60 s dedupe is not fed.

### 4. Per-rule run counters
Every rule row shows **"12 runs · last 14:02"** under its buttons
(FAILED rows marked red). Counters live in extension storage
(`ruleStats`) keyed by stable rule ids (every rule gets an id on save;
a Copy gets a fresh id so duplicates never share counters). Fallback
key pattern|printer keeps unsaved/old rules working.

### 5. Rule activity log - the hidden work, now visible
Every rule-triggered job - **auto AND manual** - is recorded (time,
pattern, action badge with auto/manual, printer, result). FAILED rows
show the actual error ("hub offline - job saved and will retry", "this
page does not look like ZPL - no ^ commands found", ...). The log keeps
the **last 100 hits**, the table shows the 30 newest, with **Refresh**,
**Clear log** and **Reset run counters** buttons. Bookkeeping can never
break a print job (all stat writes are try/catch guarded).

### 6. Settings tab points there
The old rules section in Settings is now a short card with an
**"Open the Rule Manager"** button - the section is easy to find, and
the lab documentation (About tab, docs/MULTI-PRINTER.md) references the
Rules tab everywhere.

## Not changed
- The hub: untouched (extension-only release; hub version string bumped
  so dashboard and packages stay in lockstep).
- Rule matching order (first-match-wins), pattern types, per-rule
  printer/copies/paper semantics, the per-job printer priority over the
  Print destination card - all exactly 3.0.3/3.0.4 behavior.
- Enterprise managed rules (managed.json) keep overriding local rules.

## Files
- Windows: `AdvPrint-Pro-Setup-3.0.5.exe` (silent: `/S`)
- Linux: `advprint-pro_3.0.5_all.deb`
- Extension only: `AdvPrint-Pro-Extension-v3.0.5.zip`
- Everything: `AdvPrint-Pro-v3.0.5-FULL.zip`, `AdvPrint-Pro-3.0.5-source.zip`
- Checksums: `SHA256SUMS-3.0.5.txt`
