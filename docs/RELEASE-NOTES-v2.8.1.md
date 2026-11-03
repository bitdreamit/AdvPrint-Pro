# Release Notes — AdvPrint Pro v2.8.1
### AdvPrint Pro (Advanced Printer) — by Bit Dream IT - Innovative Healthcare Solutions
MIT license · 100% local · no cloud, no tracking · release date 2026-11-03

Two additions to the dashboard's LAN sharing card, both 100% local, both
working on top of the tested v2.8.0 baseline. **Nothing removed.**

---

## 1. Send-portal QR code — phones print without any install

The dashboard **LAN sharing & other PCs** card gets a new row when LAN
sharing is ON:

> **Send portal (phones)** — `http://<this-PC-ip>:9235/send?token=…`
> [Copy send URL] [QR code]

- **Copy send URL** puts the full LAN URL (with token) on the clipboard —
  exactly the URL you asked to copy, but with the LAN IP instead of
  127.0.0.1 so other devices can actually reach it.
- **QR code** toggles a row with the QR, the URL text, a copy button and a
  close button. Any phone or tablet on the same Wi-Fi scans it, opens the
  built-in Send portal, picks a PDF — it prints on this PC's default
  printer seconds later. No app, no extension, no cloud.
- The QR is generated **inside the hub**: a vendored pure-stdlib encoder
  (byte mode, ECC level M, versions 1-40, auto mask) ported from the
  MIT-licensed "QR Code generator" reference design and verified
  **bit-exact** against an independent implementation for every mask 0-7
  on realistic hub URLs. No internet, no CDN, no tracking, no new
  dependency — the Windows bundled runtime needs nothing extra.
- New API: `GET /qr?token=…&kind=send|invite` → `image/svg+xml`
  (`no-store`). `kind=send` = the phone upload URL, `kind=invite` = the
  PC invite link below. `/health` now also reports `"hostname"`.

## 2. One-click LAN invite — connect another PC in 10 seconds

The LAN card gets a second new row:

> **Connect another PC** — `http://<this-PC-ip>:9235/connect?t=<token>&n=<PC-name>`
> [Copy invite link] [QR]

How it works:

1. On the hub PC press **Copy invite link** and send it to the other PC
   (chat, e-mail, QR — any way).
2. On the other PC open the link in a browser. The hub serves a small
   confirmation page: *"Connect to "PC-name"'s printer hub?"* with an
   **Add "PC-name" as a LAN print peer** button.
3. One click — the other PC's own hub receives
   `POST /peer-connect`, saves this hub into its `peer_hubs`
   (deduplicating by URL), health-checks it, shows the peer's version and
   a warning when LAN sharing is off there, then links straight to its
   dashboard. **No retyping the IP, no config.json editing** — exactly
   the "share ip port with token, auto connect" you asked for.
4. The peer appears in that PC's dashboard LAN card where waiting jobs
   can be shifted to it — and where it can be removed again.

Security model (it must work without the receiving hub's token, because
the inviting hub cannot know it):

- **Loopback only** — the accept POST is answered only on the receiving
  PC itself.
- **Origin check** — a browser always sends its Origin on a cross-site
  form POST; it must equal the peer URL being added. A random website
  cannot forge this, so drive-by CSRF cannot silently inject a peer
  (denials are audited as `peer.connect.denied`).
- **Private-LAN URLs only** — localhost / 10.x / 172.16-31.x /
  192.168.x / 169.254.x http(s).
- **Explicit click** — GET `/connect` never changes anything; the peer is
  written only when the user presses the button.
- **Audited** — `peer.invite` (page opened), `peer.connected` (saved).
- The invite link carries the hub token — treat it like a password; the
  QR shows it only on the owner's screen.

## Also in this release

- Dashboard LAN card polish: **Copy URL** anchors to the first row
  explicitly (the new rows also use mono cells), the no-peers tip now
  points at the invite link, and the open QR row survives the 15-second
  LAN card refresh instead of collapsing.
- Docs page (`/docs`) gained "QR code" + "One-click invite" sections;
  API.md documents `/qr`, `/connect`, `/peer-connect`; the Full Guide
  (HTML + PDF) was updated.
- Version 2.8.1 across hub, tool, setup.nsi (VIProductVersion 2.8.1.0),
  deb control, extension manifest, tests, README, START-HERE.

## Quality gates

- 146/146 pytest tests (13 new for v2.8.1: golden QR matrix, SVG
  endpoint auth, invite page validation, peer-connect success / CSRF /
  public-IP / missing-token / dedupe, dashboard markers, nsi version).
- 28/28 live self-check on a real booted hub (QR SVG round-trips to the
  exact module matrix; invite flow saves the peer and audits it; the
  /send portal upload regression test passes).
- QR encoder: 756/756 bit-exact comparisons vs the independent pip
  `qrcode` implementation (all forced masks × all ECC levels ×
  representative payloads), all 160 ECC-table entries verified.

## Files in this release

| File | What it is |
|---|---|
| `AdvPrint-Pro-Setup-2.8.1.exe` | Windows installer (silent: `/S`) |
| `advprint-pro_2.8.1_all.deb` | Linux (Debian/Ubuntu) package |
| `AdvPrint-Pro-v2.8.1-FULL.zip` | Everything: source + installers + docs |
| `AdvPrint-Pro-2.8.1-source.zip` | Source only |
| `AdvPrint-Pro-Full-Guide.html/.pdf` | Step-by-step guide |
| `SHA256SUMS.txt` | Checksums of every artifact |

## Upgrade

Run `AdvPrint-Pro-Setup-2.8.1.exe` over the old install (or
`sudo apt install ./advprint-pro_2.8.1_all.deb`). The setup stops and
reinstalls the optional service, wipes old program files and keeps your
token, settings, peers and history. After upgrading: dashboard → LAN card
→ Enable → **Copy invite link** / **QR code**.
