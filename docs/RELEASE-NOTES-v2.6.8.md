# AdvPrint Pro v2.6.8 - Release Notes
by Bit Dream IT - Innovative Healthcare Solutions - MIT license - 100% local, no cloud, no tracking

## Fixed in 2.6.8 (both found through the Debug tab on a live install)

### 1. "printer 'Canon LBP6230/6240Canon LBP6230/6240' not found on this PC"
- The stored printer name was the SAME TEXT TWICE (typed/pasted twice or
  saved from a stale field). A doubled name can never match an installed
  printer, so the job died.
- The hub now SELF-HEALS: a doubled name collapses to its half, names that
  differ only by case or spaces match the installed printer exactly. The
  job prints on the REAL printer, the history row is corrected and a
  printer.corrected audit entry records what happened.
- The extension collapses a doubled name BEFORE sending (second net).
- Old dead jobs: just press Retry in the history - they print now.

### 2. Extension error "Cannot access contents of url
     chrome-extension://... must request permission to access this host"
- Right-click "Print this page" on a browser-internal page (the
  extension's own options page, chrome://, edge://, about:, Web Store)
  cannot work - Chrome forbids injection there.
- The context menus now only exist on printable pages (http/https/file,
  documentUrlPatterns), and the click handlers + Alt+P shortcut show a
  friendly notification instead of an error report.

Nothing else changed: full v2.6.7 reliability set kept 1:1 (atomic
save-as-PDF with AV-lock retry, "File (PDF)" virtual routing, backend
stdout/stderr in errors, printer-not-found guard, screen-glitch fix).

## Files
- AdvPrint-Pro-Setup-2.6.8.exe  (Windows installer, bundled Python 3.11.9)
- advprint-pro_2.6.8_all.deb    (Debian/Ubuntu/Mint)
- AdvPrint-Pro-v2.6.8-FULL.zip  (all-in-one: source + installers + docs)
