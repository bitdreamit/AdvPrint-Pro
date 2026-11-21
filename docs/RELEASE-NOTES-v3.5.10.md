# Release Notes — AdvPrint Pro v3.5.10
**ONE POWER SWITCH (POPUP + CONSOLE + OPTIONS = THE SAME SWITCH)** — 2026-11-21
by Bit Dream IT — Innovative Healthcare Solutions

## What the owner reported

Three switch bugs, one conversation:

1. **"popup switch off after some time it auto on — why?"** — the
   popup master switch was flipped OFF and, minutes later, AdvPrint
   was enabled again on its own.
2. **"this switch why not same operation both"** — the popup switch
   and the console (ONE UI) switch did not behave like the same
   switch.
3. **"queue on off no effect in ui — why?"** — flipping the
   Queue-mode switch in the console changed nothing visible anywhere.

All three had the same root: **the popup wrote to one place and the
console wrote to another, and the sync between them was one-way,
slow, and blind to popup changes.**

## 1. Root cause — a one-way, one-speed mirror

Since v3.2.1 the hub keeps an `ext_prefs` mirror of the extension's
power keys (`enabled`, `queueMode`, `rulesPaused`, `hookPrint`,
`debugMode`, `retryOffline`, `lang`, `autoPrintAllPdfs`,
`closeAfterPrint`, `failFallback`, `contextMenu`, `badge`). The
console's Power Switches panel writes that mirror directly
(`POST /config`), and the extension adopts it — via
`adoptHubExtPrefs()` on the **5-minute** rules sync alarm.

The popup (and the Options page) wrote only `chrome.storage.local`:

- the hub **never learned** about a popup flip — so the popup switch
  and the console switch performed **different operations**;
- on the next 5-minute alarm, `adoptHubExtPrefs()` copied the hub's
  **stale** `enabled: true` back over the popup's `enabled: false` —
  the auto-ON. The switch did not "turn itself on"; the stale mirror
  overrode it;
- a console Queue-mode flip took up to 5 minutes to reach the
  browsers, and the Queue tab status card was **static demo HTML**
  (`Queue mode ON` + `hub #2047 in progress` hardcoded) — so nothing
  visible changed anywhere: "queue on off no effect in ui".

## 2. The fix — one bidirectional sync, last writer wins

`extension/background.js` v3.5.10 adds a real sync engine:

- **PUSH (local → hub)**: `chrome.storage.onChanged` watches the power
  keys; any local flip (popup, Options, content script) calls
  `scheduleExtPrefsPush()` (800 ms debounce) → `pushExtPrefsToHub()`
  POSTs a **full** `ext_prefs` object to `/config`, merged with the
  hub's current copy so console-owned keys (`print_defaults`) survive
  the whole-dict replace.
- **NO AUTO-REVERT**: `adoptHubExtPrefs()` returns early while
  `_extPrefPushPending` is set — a pending local change can never be
  clobbered by the stale hub copy. A push that fails (hub offline)
  stays pending and is retried by the sync tick every minute, on every
  popup open, and on startup — a switch flipped while the hub is down
  still wins when the hub comes back.
- **PULL (hub → local)**: new `EXT_PREF_SYNC_ALARM`
  (`advprintExtPrefSync`, **1 minute** instead of the old 5-minute-only
  adoption) runs `extPrefSyncTick()`: push when pending, otherwise
  adopt the hub copy. `getCfg` (every popup open) fires a tick too.
- **POPUP LIVE MIRROR**: the popup listens for `enabled`/`queueMode`
  storage changes and re-renders its switches live — a console flip
  reaches an open popup within a second.
- **CONFLICT RULE**: last writer wins. Whoever flipped last is pushed
  to the hub; every other surface adopts that. Nothing flips itself
  back.

## 3. The Queue tab card is live

`console.html` v3.5.10: the status card got `id="qmodeHead"` and a new
`renderQueueMode(jobs)` render, called on every 3-second poll. It
shows the **real** `ext_prefs.queueMode` (the exact key the popup
switch writes), the **real** hub pause state (RUNNING/PAUSED chip) and
the **real** printing count ("2 jobs printing now" replaces the
hardcoded "hub #2047 in progress"). The notes in the Power Switches
panel and the Queue tab now say explicitly that the popup switch and
these switches are THE SAME switch, synced within seconds; the save
toast says seconds, not "5 min".

## 4. Carried guarantees

- v3.5.9 UNBREAKABLE DEB BUILD (SCANNER-PROOF STAGING) — untouched.
  The whole defense stays in `scripts/build-all.py`: `_read_visible()`
  (visibility-retry reads that self-heal a momentary scanner hide),
  `_walk_loud()` (a hidden directory fails the build instead of
  quietly shipping an INCOMPLETE .deb), `verify_deb_stage()` +
  `deb_expected_files()` (the staged tree is verified file-by-file
  BEFORE tarring) and `build_deb_scannerproof()` (automatic re-stage +
  retry of the whole stage/tar cycle, with the Defender exclusion hint
  on final failure).
- v3.5.8 REAL WINDOW BUTTONS + BRAND TITLE + TAB MEMORY — untouched.
- v3.5.7 SILENT WINDOWS (`CREATE_NO_WINDOW`, HIDE counts 21/6) —
  untouched; UAC remains the only visible dialog by design.
- Signed CRX chain (`likldbkamojokkfdlcjibiljpgbbnohc`), LAN admin
  console, `ipp://` printer URLs, full build kit — untouched.

## 5. Locked by tests

`tests/test_v3510.py` (version coherence across hub / console /
extension / installer / DEB / VERSION.txt, hub + console twins
byte-identical, embed byte-fresh, exact source pins for the sync
engine: `EXT_PREF_KEYS`, `scheduleExtPrefsPush`, `pushExtPrefsToHub`
full-object merge, `_extPrefPushPending` adoption guard,
`EXT_PREF_SYNC_ALARM` period 1, `getCfg` sync, popup storage listener,
`#qmodeHead` + `renderQueueMode`, absence of the static demo card,
carried guarantees) and `scripts/smoke_v3510.py` (real-hub Playwright
probe: console master-switch flip → hub `/config` shows it → live
queue card follows → flip back → everything returns).
