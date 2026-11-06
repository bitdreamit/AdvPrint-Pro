# Release notes - AdvPrint Pro v3.0.6

**Rules match by CONTENT (ZPL / text / PDF / image) + Options reorganized into 9 human tabs**

AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare Solutions
MIT license - 100% local - no cloud, no tracking

## The question this release answers

*"How does it detect which printer is for ZPL? The current design is only
URL-based. I need ZPL, text, PDF, image, etc."*

Until 3.0.5 a rule fired only when the **URL** matched: "page at
`.../labels/*` -> Action ZPL label -> Zebra". The content itself was never
looked at when picking the rule (only afterwards, to guard the print). v3.0.6
adds **content rules**: the rule's **Match by** column decides what triggers
it.

## 1. Match by Content - the page itself decides

A rule no longer needs a URL. Set **Match by: Content** and pick what the
page must BE:

| Page content (kind) | Fires when | Printed as |
| --- | --- | --- |
| **ZPL label (^XA...^XZ)** | the page text carries a ZPL label (full `^XA...^XZ` block or any `^XA/^FO/^FD/^PQ...` command) | the text streams **byte-for-byte** to the rule's printer (the Zebra), with the usual safety guard against text with no `^` commands |
| **Receipt / plain text** | `document.contentType` is `text/plain` | an **ESC-POS receipt** (auto cut) on the rule's thermal printer |
| **PDF document** | `.pdf` URL or `application/pdf` content type | the PDF pipeline (paper/tray/duplex/copies from the rule) |
| **Image** | image URL or `image/*` content type | the picture prints via the new **image pipeline** (download with login cookies -> hub `image_base64`; fallback = capture of the visible tab) |
| **Web page (HTML)** | everything else | DOM render -> hub prints via headless Chrome |

- **How detection works**: the already-open tab is probed ONCE
  (`document.contentType` + a text sample: the user selection first, then a
  `<pre>`/`<textarea>` block, then the visible body text, first 4000 chars).
  No extra download, no page JavaScript, and only when content rules exist
  (`hasContentRules()`) - pure URL users pay nothing.
- **URL rules are untouched**: without the Match-by column set to Content,
  everything behaves exactly like 3.0.5.
- **A URL in a content rule narrows it**: "ZPL pages on THIS site only" -
  both the content and the URL filter must match.
- **The pipeline follows the content**: `ruleActionFor()` runs the action
  that fits the detected kind (a ZPL page always prints as ZPL, an image
  always as an image) even if the dropdown says something else - a wrong
  choice can never send garbage to the printer. URL rules keep their
  configured Action.
- **Rule 2 of the lab with zero URLs**: Match by Content -> ZPL label ->
  printer: Zebra -> Auto. Any label page from any web tool now lands on the
  Zebra.

## 2. Auto-print rules power switch - now in Options only

The popup no longer carries the auto-print rules switch (v3.0.5 put it
there; user request: *"Auto-print rules no need popup, section it shift to
setting power switch setting option"*). The SAME setting (`rulesPaused`) is
now two synced switches in the Options page:

- the **power switch on the Rule Manager bar** (Rules tab, next to Save
  rules), and
- the **"Auto-print rules (silent background printing)" toggle in General >
  Power switches**.

OFF = paused: NO rule auto-prints; manual prints (popup buttons, right-click
menu) keep working - exactly like the queue Pause, but for rules.

## 3. Options reorganized - 9 human tabs, every option explained

The old single **Settings** tab (9 stacked sections) is split into focused
tabs with plain-English names, every option kept and given a full
description:

| Tab | What lives there |
| --- | --- |
| **Queue** | live queue, Pause, Clear |
| **History** | job history manager (filter/search/reprint) |
| **Rules** | the Rule Manager - URL + content rules, power switch, simulators, run counters, activity log |
| **General** | power switches (master, queue mode, **auto-print rules**, window.print() hook, debug, retry, language) + browser behavior + Rule Manager pointer |
| **Printing** | default printer + default print options (copies/pages/quality/duplex/paper...) |
| **Connections** | Self PC hub, LAN PC profile, LAN sharing tools (peers, shift), Website API permission |
| **Hub** | the hub-side settings (queue & retries, security, reprint & audit, thermal engine, PDF folder, Windows engine) |
| **Debug** | WHEN / WHY / WHERE is the problem |
| **About** | version, updates, developer API |

Old deep links keep working: `options.html#settings` -> General,
`#api` / `#lan-settings` -> Connections (scrolled to the right card).

## 4. Two simulators - test without printing

- **URL simulator (upgraded)**: fetches the URL once with your login
  cookies, reads the content type, samples the text for `^XA` - then names
  the winning rule, printer, action and the DETECTED CONTENT (or says the
  page could not be fetched and matched by URL only).
- **Text simulator (new)**: paste the label/receipt text - it answers
  "this is ZPL / receipt text" and which content rule would fire.

## 5. Smaller changes

- Rules table: **Match by** + **Page content** columns (a URL rule grays
  the content dropdown out; a content rule treats the URL as an optional
  filter); **Copy** carries the new fields; **Action: Image** joins the
  dropdown for URL rules.
- `maybeCloseTab(force)`: a content-rule hit can close its tab when
  "Close tab after auto-print" is on (the URL-only re-check cannot see a
  kind-only rule).
- LAN tab merged into **Connections**; the 8 s LAN refresh follows it.
- Regression tests updated + a new v3.0.6 test (`test_v306_content_rules_engine`)
  locks the engine, the UI columns, the power switches and the simulators.

## Compatibility

- Extension-only release; the hub is untouched (version string bump only).
- Nothing removed: old URL rules keep working, `match`/`kind` default to
  the old behavior, every option survived the tab split.
- Upgrade in place: chrome://extensions -> Reload, or run the Setup exe /
  deb over the old install. Settings and history are kept.

## Files

- `AdvPrint-Pro-Extension-v3.0.6.zip` - the extension only ("Load unpacked")
- `AdvPrint-Pro-Setup-3.0.6.exe` - Windows installer (hub + extension + docs)
- `advprint-pro_3.0.6_all.deb` - Linux (Debian/Ubuntu) package
- `AdvPrint-Pro-v3.0.6-FULL.zip` - portable tree (hub + extension + docs)
- `AdvPrint-Pro-3.0.6-source.zip` - complete source incl. tests
- `SHA256SUMS-3.0.6.txt` - checksums for all of the above
