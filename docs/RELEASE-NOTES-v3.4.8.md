# AdvPrint Pro v3.4.8 - Release Notes

**Rules table fits - the Edit button never leaves the card.**
by Bit Dream IT - Innovative Healthcare Solutions

## What happened to the first v3.4.8?

The first v3.4.8 attempt shipped the table fix together with three
extra logic changes and did not work ("fully bug"). Per your request it
was REVERTED completely: this release is built on the untouched,
working **v3.4.7** tree. Nothing from the buggy attempt is in this
build - the release notes below describe the only change that ships.

## The fix

**The ONE UI rules table (14 columns) overflowed the card.** With
`Paper` or another extra column showing, the `white-space:nowrap`
headers forced a ~1145px minimum width inside a ~990px card, pushing
the `Runs` column and the `Edit` / `Del` buttons OUTSIDE the visible
card.

v3.4.8 fixes it at the root with CSS only - no print, rule, queue or
network logic touched:

1. **Headers may wrap** to a second line (`white-space:normal`).
2. **Every ONE UI table sits in a horizontal scroll container** that
   lives INSIDE the card - on very narrow windows the table scrolls,
   the card border is never crossed, the page never scrolls sideways.
3. **The rules table is compact** (tighter cells + slimmer column
   widths) so at the normal console width it fits with NO scrolling.
4. **Long "Page content" cells clamp** with an ellipsis, exactly like
   the URL pattern cells.

Measured on the live hub: 0px overflow at 1280px, Edit/Del fully
inside the card; at 800px the inner container scrolls and the buttons
stay reachable inside the card (`scripts/ui_check_v348.py` PASS).

## Everything else = working v3.4.7

Configurable hub port (9235 default, movable when busy), DropZone
watch Enable/Disable toggle, strict LAN share with the IP hit list +
one-click Allow, URL rules that really match (glob / regex / contains
+ the "Which rule fires?" test box), one TCP port 9235 for every queue,
the popup that remembers the last printer, manual LAN/IPP re-scan,
auto-CRX on install, idempotent set-default.

## Upgrade

Install straight over v3.4.6 / v3.4.7 (Setup exe / deb) - settings,
history and printer queues are kept. Browsers with the auto-installed
CRX update themselves; manual installs: Remove + Load unpacked the new
`AdvPrint-Pro-Extension-3.4.8.zip`.

## Verification chain

- 663 pytest green (incl. the new `tests/test_v348.py` which locks the
  fix AND the absence of the reverted logic changes)
- Real-browser UI check 1280px + 800px PASS, zero JS errors
- CRX3 re-signed v3.4.8, every embedded copy byte-verified
- SHA256SUMS-3.4.8.txt: 4/4 OK
