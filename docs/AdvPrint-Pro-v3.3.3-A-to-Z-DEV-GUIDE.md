# AdvPrint Pro v3.3.3 — A-to-Z DEVELOPMENT & BUILD GUIDE

> **v3.3.3 = "SHARE SEND POPUP-FIX + PEERS-ONLINE RELEASE" on top of
> v3.3.2.** Four new real-world LAN reports, all fixed and locked by
> `tests/test_v333.py`. Everything from v3.3.2 (SHARE SEND MODE, the
> Windows IPP add-fix, the per-printer queues), v3.3.0 (any-PC invite,
> dual-stack listeners) and earlier stays unchanged. The deep
> architecture reference lives in
> `docs/AdvPrint-Pro-v3.2.7-A-to-Z-DEV-GUIDE.md`; this guide documents
> the v3.3.3 delta.

> **BUG 1 — the false "Connect the LAN PC first" popup.** The console
> blocked the Share Send flip while `lanPeerState` was still null —
> which is EVERY page load until the first `/peer/status` answer lands
> behind seven sequential poll calls. The client no longer blocks: the
> POST goes out, the server (the persisted truth) decides, an in-flight
> flip is guarded against the 3 s poll (`_shareSendPending`), and the
> switch mirrors `cfgCache.share_send` at boot.
>
> **BUG 2 — the peers table showed every peer OFFLINE forever.**
> `/peers` answered `alive`; the table read `p.up` (undefined). The hub
> now sends `up` AND `alive`, the entry's `name`/`label` (rows said
> "PC" for every peer), and the table refreshes on every poll instead
> of only at page load.
>
> **BUG 3 — the SAME PC listed twice.** peer_hubs entries are deduped
> by normalized URL (`_peer_url_norm` / `_dedupe_peer_hubs`) on every
> write path — `/peer/pair`, invite `/peer-connect`, POST /config —
> `/peers` dedupes defensively at read time, job forwarding can never
> double-hand a job, and an invite link for an ALREADY-PAIRED PC
> updates the lan-pc entry in place instead of silently unpairing
> Share Send Mode.
>
> **BUG 4 — Shift queue was doubly broken.** The console sent
> `{peer: url}` while the endpoint read `target`, and "Shift all
> waiting" read the SELF PC token field as the peer URL (the LAN PC
> card had shifted the `qsa()` indexes); the input kept its static
> demo value `http://10.26.94.77:9235` forever. Now: `id=shiftTarget`,
> prefilled with the LAN PC's URL, both sides agree on `target`
> (`peer` accepted as alias), demo value gone.

---

## 1. The three files that must stay in sync

| File | Role |
| --- | --- |
| `tool/unix/hub/advprint.py` | the hub source of truth (VERSION 3.3.3) |
| `tool/windows/portable/hub/advprint.py` | byte-identical copy (installer + tests import THIS one) |
| `tool/unix/hub/console.html` | ONE UI source; embedded into BOTH hub copies by `scripts/embed_console.py` |

After editing the UI: `python3 scripts/embed_console.py`. After editing
hub code: `cp tool/unix/hub/advprint.py
tool/windows/portable/hub/advprint.py`.

## 2. v3.3.3 code map (delta only)

### Peer list + dedupe — `tool/unix/hub/advprint.py`

```
_peer_url_norm(url)                  scheme://host:port, host lowercased
                                     http://IP:9235/ == HTTP://ip:9235/ipp
_dedupe_peer_hubs(peers)             first entry per normalized URL wins;
                                     a dropped entry's label/name survives
                                     on the kept entry when it has none
probe_peers(timeout=3)               dedupes CFG.peer_hubs FIRST, then
  ├─ entry {url, up, alive, version, latency_ms, name, label, error?}
  │     up = alive (the console table read p.up - undefined before)
  └─ cached 15 s (_PEER_CACHE; reset on pair/unpair/config.peer_hubs)
```

### Write-path dedupe

```
POST /peer/pair     _peer_pair       drops EVERY same-URL entry (any
                                     name) before inserting lan-pc;
                                     keeps the old entry's label
POST /peer-connect  _peer_connect    same dedupe; an invite for an
                                     ALREADY-PAIRED hub updates the
                                     lan-pc entry IN PLACE (was_lan_pc)
POST /config        peer_hubs key    cleaned then deduped; _PEER_CACHE
                                     reset when peer_hubs changed
_try_peer_forward   job forwarding   dedupes before iterating
GET  /peers         probe_peers      dedupes defensively at read time
```

### Shift queue

```
POST /queue/shift    target = body.target OR body.peer (v3.3.3 alias)
  └─ token lookup: _peer_url_norm(target) == _peer_url_norm(entry.url)
     (the old exact-string match missed case/slash variants)
console: Shift all waiting  -> $("shiftTarget") -> {target, scope:"all"}
console: row ⇆ Shift queue  -> {target: p.url, scope:"all"}
```

### Console (CONSOLE_HTML / console.html)

```
Connections > Other PCs (peers) table   loadConnections()
  ├─ var up = !!(p.up || p.alive)       OFFLINE-forever fix (BUG 2)
  ├─ who = p.label || p.name || "PC"    rows show WHICH PC (BUG 2)
  ├─ client-side same-URL dedupe        stale-config guard (BUG 3)
  ├─ $("shiftTarget") prefill           lanUrl || first ONLINE peer;
  │                                     the static demo value is gone
  └─ called from poll() EVERY 3 s       was page-load-only (BUG 2)

Share Send Mode switch                  bindSwitches() branch
  ├─ NO client pre-check any more       the false popup fix (BUG 1):
  │                                     POST /config {share_send} goes
  │                                     out; the server decides
  ├─ _shareSendPending guard            poll/render skip mirroring
  │                                     while a flip is in flight
  └─ poll() mirrors cfgCache.share_send before the first /peer/status
     answer (no OFF-rendered-while-ON boot window)
```

## 3. Config keys

No new keys. `share_send` / `show_remote_printers` (v3.3.2) unchanged;
`peer_hubs` entries may now carry `label` (kept through dedupe).

## 4. Tests (tests/test_v333.py)

- `test_peers_answer_up_and_alive` / `_carry_name_and_label` -
  BUG 2 (the console contract).
- `test_peers_dedupe_same_url_at_read_time` -
  BUG 3 (a stale duplicated config renders as ONE row).
- `test_dedupe_lan_pc_entry_wins_migration` -
  BUG 3 (a v3.3.2 config may store the invite entry FIRST, lan-pc
  second - the lan-pc pairing must win the collapse; found by the
  live check).
- `test_pair_same_url_replaces_invite_entry` / `_no_duplicate_rows` -
  BUG 3 (pair after invite = ONE lan-pc entry, peers list has ONE row).
- `test_invite_preserves_lan_pc_pairing` -
  BUG 3 / BUG 1's second root cause (invite for a paired hub keeps the
  lan-pc name, Share Send stays validatable).
- `test_share_send_on_requires_persisted_pairing` /
  `_off_always_allowed` - the REAL validation is untouched.
- `test_queue_shift_accepts_target_and_peer` / `_token_lookup_normalized` -
  BUG 4.
- `test_console_no_blocking_share_send_precheck` /
  `_has_shift_target_wiring` / `_poll_calls_load_connections` /
  `_peers_table_reads_up_or_alive` - the console deltas.

Run: `python3 -m pytest tests/test_v333.py -q` (and the whole suite
before shipping).

## 5. Build + release checklist

```bash
python3 -m pytest tests/ -q            # full suite green
python3 scripts/embed_console.py       # after ANY console.html edit
cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py
bash scripts/build-all.sh              # CRX3 + extension zip + NSIS exe + deb + SHA256SUMS
```

`build-all.sh` re-signs the CRX (repo key
`extension-signing/advprint-printer.pem`), syncs EVERY embedded CRX
copy and hard-fails if any copy or version drifts (the v3.2.8
stale-CRX guard). Deliverables land in `dist/`.

## 6. Upgrade notes for users

- Install over the old version (Setup exe / deb). config.json is kept;
  duplicates in an old peer_hubs list keep working (`/peers` collapses
  them at read time; the next pairing / config save cleans the file).
- If Share Send Mode refuses to go ON after the upgrade (a v3.3.2
  invite may have renamed the lan-pc entry), reconnect ONCE:
  Connections > Another PC (LAN PC) > enter the peer's hub URL + token
  > Connect. From then on the pairing is dedupe-safe.
- The peers table shows ONLINE/OFFLINE truth now, refreshes itself, and
  "Shift whole queue to" is prefilled with the LAN PC's URL.
