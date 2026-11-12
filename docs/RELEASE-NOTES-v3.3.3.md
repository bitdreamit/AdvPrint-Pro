# v3.3.3 - SHARE SEND POPUP-FIX + PEERS-ONLINE RELEASE (2026-11-12)

**Base: v3.3.2** (user-verified: "v3.3.2 version work fine"). Four new
real-world reports from the same LAN, all fixed and locked by
`tests/test_v333.py`.

---

## BUG 1 - false popup: Share Send Mode "cant be on"

**The report:** *"bug popup share send mode cant be on"* - flipping the
Connections LAN PC card's Share Send switch popped **"Connect the LAN
PC first - enter its hub URL + token and press Connect"** even though
the card above showed **CONNECTED** and the pairing was saved.

**The root cause:** the console's switch handler pre-checked the
in-memory `lanPeerState` and blocked the flip while it was still null.
`lanPeerState` stays null until the FIRST `/peer/status` answer - and
that answer waits behind seven sequential poll calls (`/health`,
`/stats`, `/queue`, `/printers`, `/jobs`, `/audit`, `/config`;
`/printers` alone can take seconds on Windows WMI). Clicking Share Send
in the first seconds after opening the console ALWAYS hit the false
popup, even though the pairing was persisted in config.json and the
server would have accepted the flip.

**The fix (console.html):**

| Item | v3.3.2 | v3.3.3 |
| --- | --- | --- |
| Client pre-check | blocks the flip with the popup while `lanPeerState` is null | **removed** - the POST goes out, the SERVER (the persisted truth) decides; on 400 the switch reverts and the server's real message shows |
| Boot-window switch render | OFF until the first `/peer/status` even when `share_send` was already ON in config.json (flip-and-popup bait) | mirrors `cfgCache.share_send` from the main poll body immediately |
| 3 s poll vs a flip in flight | the next poll could visually revert the switch before the POST landed | `_shareSendPending` guard - poll and `renderLanPeer` skip mirroring until the flip resolves |

## BUG 2 - peers table: "conected hub online and on but other pc show offline"

**The report:** the Other PCs (peers) table showed the peer **OFFLINE**
- twice - while the LAN PC card showed **CONNECTED** for the same PC
and the peer's hub was online with LAN sharing + IPP ON.

**The root cause:** field-name mismatch. The `/peers` endpoint answers
with `{"alive": true}`; the console table read `p.up` - **undefined on
every response** - so every row rendered OFFLINE and every Shift queue
button stayed disabled forever.

**Two more lies in the same table, fixed in the same pass:**

1. Every row read "· PC" because the endpoint never returned the
   entry's name/label. It does now - the row shows WHICH PC it is
   (`http://192.168.1.101:9235 · AI-Lab`).
2. The table only rendered at page load; `loadConnections()` was never
   called from the poll loop, so a peer that came online stayed OFFLINE
   until a manual reload. It refreshes on every poll now (`/peers` is
   cached 15 s server-side, so this costs the hub nothing).

**The fix (both sides agree):** the hub sends `up` AND `alive`; the
table reads `p.up || p.alive`.

## BUG 3 - the SAME PC listed twice (duplicate peer rows)

**The report:** the peers table listed `http://192.168.1.101:9235`
TWICE - both rows OFFLINE, both v3.3.2.

**The root cause:** the LAN PC card's Connect (`/peer/pair`) removed
only entries NAMED `lan-pc` before inserting the fresh pairing. An
entry for the SAME hub saved earlier by an invite link (name = the PC's
host name) survived next to it - and the duplicate probed with a stale
token.

**The fix (dedupe by normalized URL everywhere):**

| Path | Behaviour in v3.3.3 |
| --- | --- |
| `POST /peer/pair` | drops EVERY entry that already points at the same `scheme://host:port` (any name) before inserting the lan-pc pairing; keeps the old entry's label |
| invite `POST /peer-connect` | same dedupe; **if the invited hub is ALREADY paired as lan-pc, the entry is updated in place** - the old code deleted the lan-pc entry and appended a plain host-named one, silently unpairing Share Send Mode (the popup's second root cause) |
| `POST /config` peer_hubs cleaning | dedupes before persisting |
| `GET /peers` | dedupes defensively at read time (guards a stale config.json written by an older build) |
| `_try_peer_forward` | same-URL entries can never hand the same job to the same hub twice |
| console table | first occurrence wins (display-level guard) |

## BUG 4 - Shift queue was doubly broken

**The report (visible in the same console dump):** *"Shift whole queue
to http://10.26.94.77:9235"* - an IP that is not even on the peer list
- and Shift queue buttons that never did anything.

**The root causes (three of them):**

1. The "Shift whole queue to" input kept its STATIC demo value
   (`http://10.26.94.77:9235` - a PC from the design mockup) forever.
2. "Shift all waiting" read `qsa("#p-connections .frow input.inp.mono")[1]`
   - which, after the LAN PC card was inserted above it, is the **SELF
   PC token field**, so the shift fired at a garbage "URL".
3. Both console Shift buttons sent `{peer: url}` while the endpoint
   reads `target` - the URL was silently ignored and the endpoint
   guessed the first live peer.

**The fix:** the input has `id=shiftTarget`, is prefilled with the LAN
PC's URL (else the first ONLINE peer), the handlers read it by id and
send `{target, scope:"all"}`, and `/queue/shift` accepts `peer` as an
alias for `target` (older consoles keep working). The demo value is
gone.

---

## Verification

- `python3 -m pytest tests/` - full suite green, including the new
  `tests/test_v333.py` (21 checks): `/peers` shape (`up` + `alive` +
  name/label) + read-time dedupe, `/peer/pair` same-URL dedupe (no
  duplicate rows), invite-preserves-lan-pc, share_send still refuses
  ON-without-peer (the REAL validation is untouched),
  `/queue/shift` target/peer alias + token lookup by normalized URL,
  and the console UI deltas (no blocking pre-check, `shiftTarget`
  wired, `loadConnections()` in the poll loop).
- `node --check` clean on the extracted console JS.

## Upgrade notes

- Install over v3.3.2 (Setup exe / deb). config.json is kept. A config
  written by v3.3.2 that already contains duplicate peer entries keeps
  working: `/peers` collapses the duplicates at read time, and the next
  pairing / config save cleans the file itself.
- If Share Send Mode refuses to go ON after the upgrade (a v3.3.2
  invite may have renamed the lan-pc entry), reconnect ONCE: Connections
  > Another PC (LAN PC) > enter the peer's hub URL + token > Connect.
  From then on the pairing is dedupe-safe.
