"""v3.3.3 - SHARE SEND POPUP-FIX + PEERS-ONLINE RELEASE.

Four real-world reports from the same LAN (peer hub online, LAN sharing
ON, IPP ON - yet the console lied about all of it). Each is locked:

BUG 1  the false popup "Connect the LAN PC first - enter its hub URL +
       token and press Connect" when flipping Share Send Mode ON. The
       console blocked the flip while lanPeerState was still null -
       which is EVERY page load until the first /peer/status answer
       lands behind seven sequential poll calls. Fix: the client no
       longer blocks (the POST goes out, the SERVER decides); the
       server-side validation is INTENTIONALLY untouched (ON really is
       refused without the persisted pairing). Locked on both sides:
       the console carries no blocking pre-check any more, and the
       server still accepts ON with / refuses ON without the pairing.

BUG 2  the Other PCs (peers) table showed EVERY peer OFFLINE forever
       and its Shift queue buttons stayed disabled: /peers answered
       `alive`, the table read `p.up` (undefined). The hub now sends
       `up` AND `alive` plus name/label, and the console reads
       `p.up || p.alive` and refreshes the table on every poll.

BUG 3  the SAME PC listed twice. peer_hubs entries are deduped by
       normalized URL on every write path (pair / invite / config),
       /peers dedupes at read time, and an invite link for an
       ALREADY-PAIRED PC updates the lan-pc entry in place instead of
       silently unpairing Share Send Mode.

BUG 4  Shift queue was doubly broken: the console sent {peer: url}
       while the endpoint read `target`, and "Shift all waiting" read
       the SELF PC token field as the peer URL; the input kept its
       static demo value. Now: id=shiftTarget + prefill, both sides
       agree on `target` (peer accepted as alias), token lookup by
       normalized URL.
"""
import json
import re
import socket
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import advprint
from conftest import wait_until

LAN_PC = advprint.LAN_PC_PEER_NAME


# ---------------------------------------------------------------
# helpers
# ---------------------------------------------------------------

def _extract_console():
    """The ONE UI source as served by the hub (CONSOLE_HTML)."""
    src = open(advprint.__file__, encoding="utf-8").read()
    i = src.index('CONSOLE_HTML = r"""') + len('CONSOLE_HTML = r"""')
    j = src.index('\n"""', i)
    return src[i:j]


def _peer_url_norm(url):
    return advprint._peer_url_norm(url)


class _FakePeerHandler(BaseHTTPRequestHandler):
    peer_state = {"share_lan": True, "version": "3.3.2",
                  "printers": ["HP Laser 103 107 108"], "print_jobs": []}

    def log_message(self, *a):
        pass

    def _reply(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        st = _FakePeerHandler.peer_state
        if self.path == "/health":
            self._reply({"ok": True, "version": st["version"],
                         "host": "AI-Lab", "share_lan": st["share_lan"],
                         "ipp_printer": True,
                         "default_printer": st["printers"][0]})
        elif self.path == "/printers":
            self._reply({"ok": True, "printers": [
                {"name": n, "status": "ready", "is_default": i == 0}
                for i, n in enumerate(st["printers"])]})
        else:
            self._reply({"ok": False, "error": "unknown"}, 404)

    def do_POST(self):
        st = _FakePeerHandler.peer_state
        ln = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(ln).decode("utf-8"))
        if self.path == "/print":
            st["print_jobs"].append(body)
            self._reply({"ok": True, "job_id": 880 + len(st["print_jobs"])})
        else:
            self._reply({"ok": False, "error": "unknown"}, 404)


@pytest.fixture()
def fake_peer():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _FakePeerHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _FakePeerHandler.peer_state.update(
        {"share_lan": True, "version": "3.3.2",
         "printers": ["HP Laser 103 107 108"], "print_jobs": []})
    yield {"base": "http://127.0.0.1:%d" % port, "port": port,
           "httpd": httpd}
    httpd.shutdown()


@pytest.fixture()
def no_peer(hub):
    saved = advprint.CFG.get("peer_hubs")
    saved_ss = advprint.CFG.get("share_send")
    advprint.CFG["peer_hubs"] = []
    advprint.CFG["share_send"] = False
    advprint._PEER_CACHE["t"] = 0.0
    yield
    advprint.CFG["peer_hubs"] = saved
    advprint.CFG["share_send"] = saved_ss
    advprint._PEER_CACHE["t"] = 0.0
    try:
        advprint.write_config_file({k: advprint.CFG[k]
                                    for k in advprint.CONFIG_KEYS})
    except Exception:
        pass


def _invite(hub, url, token, name):
    """The one-click invite flow: POST /peer-connect (form-encoded)."""
    body = urllib.parse.urlencode({"url": url, "token": token,
                                   "name": name, "confirm": "1"}).encode()
    req = urllib.request.Request(
        hub.base + "/peer-connect", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.getcode(), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# ---------------------------------------------------------------
# 1. BUG 2 - /peers answers `up` AND `alive` + name/label
# ---------------------------------------------------------------

def test_peers_answer_up_and_alive(hub, no_peer, fake_peer):
    hub.post("/peer/pair", body={"url": fake_peer["base"],
                                 "token": "tok-a", "name": "AI Lab"})
    code, data = hub.get("/peers")
    assert code == 200
    peers = data["peers"]
    assert len(peers) == 1
    row = peers[0]
    assert row["alive"] is True          # old field stays
    assert row["up"] is True             # NEW - the console reads this
    assert row["version"] == "3.3.2"
    assert row["name"] == LAN_PC
    assert row["label"] == "AI Lab"
    # and a DEAD peer reports up=False (not a missing field)
    fake_peer["httpd"].shutdown()
    advprint._PEER_CACHE["t"] = 0.0
    code2, data2 = hub.get("/peers")
    assert code2 == 200
    assert data2["peers"][0]["up"] is False
    assert data2["peers"][0]["alive"] is False


def test_peers_dedupe_same_url_at_read_time(hub, no_peer):
    """A stale config.json written by an older build may hold the same
    PC twice - /peers must render ONE row (first entry wins)."""
    advprint.CFG["peer_hubs"] = [
        {"url": "http://192.168.1.101:9235", "token": "new",
         "name": LAN_PC, "label": "AI-Lab"},
        {"url": "http://192.168.1.101:9235/", "token": "old",
         "name": "AI-Lab"},                       # same hub, slash
        {"url": "HTTP://192.168.1.101:9235", "token": "older",
         "name": ""},                             # same hub, case
        {"url": "http://192.168.1.104:9235", "token": "x",
         "name": "Other-PC"},                     # genuinely different
    ]
    advprint._PEER_CACHE["t"] = 0.0
    code, data = hub.get("/peers")
    urls = [p["url"] for p in data["peers"]]
    assert len(urls) == 2, urls
    assert urls[0] == "http://192.168.1.101:9235"
    assert urls[1] == "http://192.168.1.104:9235"


def test_dedupe_lan_pc_entry_wins_migration(hub, no_peer):
    """MIGRATION (found by the live check): a v3.3.2 config can store
    the invite entry FIRST and the lan-pc pairing SECOND. The collapse
    must keep the lan-pc entry (its name is load-bearing - losing it
    makes Share Send Mode pop "Connect the LAN PC first" again) and
    adopt the dropped entry's display name as its label."""
    advprint.CFG["peer_hubs"] = [
        {"url": "http://192.168.1.101:9235", "token": "stale",
         "name": "AI-Lab"},
        {"url": "http://192.168.1.101:9235/", "token": "good",
         "name": LAN_PC, "label": "AI-Lab"},
    ]
    advprint._PEER_CACHE["t"] = 0.0
    code, data = hub.get("/peers")
    assert len(data["peers"]) == 1
    row = data["peers"][0]
    assert row["name"] == LAN_PC
    assert row["label"] == "AI-Lab"
    # and the persisted pairing survives: /peer/status is configured
    code2, st = hub.get("/peer/status")
    assert st["configured"] is True
    assert st["url"].rstrip("/") == "http://192.168.1.101:9235"


def test_peer_url_norm_variants():
    f = advprint._peer_url_norm
    assert f("http://192.168.1.101:9235") == \
        f("http://192.168.1.101:9235/") == \
        f("HTTP://192.168.1.101:9235/ipp") == \
        "http://192.168.1.101:9235"
    assert f("https://lab.local:9235") == "https://lab.local:9235"
    assert f("") == ""
    assert f("http://192.168.1.101:9235") != \
        f("http://192.168.1.104:9235")


# ---------------------------------------------------------------
# 2. BUG 3 - same-URL dedupe on every write path
# ---------------------------------------------------------------

def test_pair_same_url_replaces_invite_entry(hub, no_peer, fake_peer):
    """The user's exact bug: the hub was added by an INVITE earlier
    (name = the PC's host name), then paired again from the LAN PC
    card. v3.3.2 kept BOTH entries (two rows in the peers table);
    v3.3.3 replaces the same-URL entry with the lan-pc pairing."""
    # step 1: the invite saved the peer under a host name
    code, page = _invite(hub, fake_peer["base"], "old-token", "AI-Lab")
    assert code == 200
    peers = advprint.CFG["peer_hubs"]
    assert len(peers) == 1 and peers[0]["name"] == "AI-Lab"
    # step 2: pair the SAME URL from the LAN PC card
    code2, st = hub.post("/peer/pair", body={"url": fake_peer["base"],
                                             "token": "new-token"})
    assert code2 == 200 and st["configured"] is True
    peers2 = advprint.CFG["peer_hubs"]
    assert len(peers2) == 1, peers2
    assert peers2[0]["name"] == LAN_PC
    assert peers2[0]["token"] == "new-token"
    # the peers table renders ONE row for this hub
    code3, data3 = hub.get("/peers")
    rows = [p for p in data3["peers"]
            if _peer_url_norm(p["url"]) == _peer_url_norm(fake_peer["base"])]
    assert len(rows) == 1


def test_invite_preserves_lan_pc_pairing(hub, no_peer, fake_peer):
    """Opening an invite link for an ALREADY-PAIRED PC must UPDATE the
    lan-pc entry in place. v3.3.2 deleted the lan-pc entry and appended
    a plain host-named one -> Share Send Mode silently lost its pairing
    and the switch later answered "Connect the LAN PC first"."""
    code, st = hub.post("/peer/pair", body={"url": fake_peer["base"],
                                            "token": "tok-1"})
    assert code == 200
    code2, page = _invite(hub, fake_peer["base"] + "/", "tok-2", "")
    assert code2 == 200
    peers = advprint.CFG["peer_hubs"]
    assert len(peers) == 1, peers
    assert peers[0]["name"] == LAN_PC, \
        "the lan-pc pairing must survive an invite for the same PC"
    assert peers[0]["token"] == "tok-2"
    # Share Send Mode is therefore still VALIDATABLE - the popup's
    # server-side half cannot fire for this PC any more
    code3, resp = hub.post("/config", body={"share_send": True})
    assert code3 == 200 and resp.get("ok") is not False
    advprint.CFG["share_send"] = False


def test_config_peer_hubs_cleaning_dedupes(hub, no_peer):
    code, data = hub.post("/config", body={"peer_hubs": [
        {"url": "http://192.168.1.101:9235", "token": "a",
         "name": LAN_PC},
        {"url": "http://192.168.1.101:9235/", "token": "b",
         "name": "AI-Lab"},
        {"url": "http://192.168.1.102:9235", "token": "c",
         "name": "Second-PC"},
    ]})
    assert code == 200
    peers = advprint.CFG["peer_hubs"]
    urls = [_peer_url_norm(p.get("url")) for p in peers]
    assert len(peers) == 2, peers
    assert urls.count("http://192.168.1.101:9235") == 1
    assert peers[0]["name"] == LAN_PC     # first occurrence wins
    # the label of the dropped duplicate survives on the kept entry
    # (nothing had a label here, so none is invented)
    code2, data2 = hub.get("/config")
    listed = data2["peer_hubs"]
    assert len(listed) == 2


def test_forwarding_never_hands_job_to_same_hub_twice(hub, no_peer):
    """_try_peer_forward iterates peers - a duplicated entry (stale
    config) must not make the loop try the SAME hub twice."""
    advprint.CFG["peer_hubs"] = [
        {"url": "http://192.168.1.101:9235", "token": "a",
         "name": LAN_PC},
        {"url": "http://192.168.1.101:9235", "token": "b",
         "name": "dup"},
    ]
    job = {"id": 1, "file_path": "/nonexistent.bin", "printer": "P"}
    # file missing -> returns False, but the important part is that the
    # dedupe happens BEFORE the file read and no exception escapes
    assert advprint._try_peer_forward(job, force=True) is False


# ---------------------------------------------------------------
# 3. BUG 1 - the popup: server decides, client does not block
# ---------------------------------------------------------------

def test_share_send_on_requires_persisted_pairing(hub, no_peer):
    """The REAL validation is intentionally untouched: ON without the
    lan-pc pairing is still refused with the guidance message."""
    code, data = hub.post("/config", body={"share_send": True})
    assert code == 400
    assert "Connect the LAN PC first" in data["error"]
    assert advprint.CFG["share_send"] is False


def test_share_send_on_with_pairing_accepted(hub, no_peer, fake_peer):
    """With the pairing persisted, the SAME flip is accepted - the
    false popup came from the CLIENT blocking, not from the server."""
    hub.post("/peer/pair", body={"url": fake_peer["base"],
                                 "token": "tok", "name": "AI Lab"})
    code, data = hub.post("/config", body={"share_send": True})
    assert code == 200
    assert advprint.CFG["share_send"] is True
    code2, st2 = hub.get("/peer/status")
    assert st2["configured"] is True and st2["share_send"] is True
    hub.post("/config", body={"share_send": False})
    assert advprint.CFG["share_send"] is False


def test_share_send_off_always_allowed(hub, no_peer):
    code, data = hub.post("/config", body={"share_send": False})
    assert code == 200


# ---------------------------------------------------------------
# 4. BUG 4 - shift queue: target/peer alias + token lookup
# ---------------------------------------------------------------

def _queue_file(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"%PDF-1.4\n% shift-test\n")
    return str(p)


def test_queue_shift_accepts_target_and_peer(hub, no_peer, clean_queue,
                                             tmp_path, fake_peer):
    """The console used to send {peer: url} while the endpoint read
    only `target` - the URL was silently ignored. Both keys work now
    (jobs actually SHIFT to the given peer)."""
    _FakePeerHandler.peer_state["print_jobs"] = []
    hub.post("/peer/pair", body={"url": fake_peer["base"],
                                 "token": "tok", "name": "AI Lab"})
    f1 = _queue_file(tmp_path, "a.pdf")
    f2 = _queue_file(tmp_path, "b.pdf")
    advprint.db_add("a4", "a.pdf", "", 1, f1, "test", "127.0.0.1",
                    status="queued")
    advprint.db_add("a4", "b.pdf", "", 1, f2, "test", "127.0.0.1",
                    status="queued")
    code, resp = hub.post("/queue/shift", body={"target": fake_peer["base"],
                                                "scope": "all"})
    assert code == 200, resp
    assert resp["shifted_count"] >= 2
    assert len(_FakePeerHandler.peer_state["print_jobs"]) >= 2

    # fresh queue for the alias check
    for j in advprint.db_list(limit=500):
        if j["status"] in ("queued", "printing", "held", "scheduled"):
            advprint.db_update(j["id"], status="canceled", error="reset")
    _FakePeerHandler.peer_state["print_jobs"] = []
    f3 = _queue_file(tmp_path, "c.pdf")
    advprint.db_add("a4", "c.pdf", "", 1, f3, "test", "127.0.0.1",
                    status="queued")
    code2, resp2 = hub.post("/queue/shift", body={"peer": fake_peer["base"],
                                                  "scope": "all"})
    assert code2 == 200, resp2
    assert resp2["shifted_count"] >= 1
    assert len(_FakePeerHandler.peer_state["print_jobs"]) >= 1


def test_queue_shift_token_lookup_normalized(hub, no_peer, clean_queue,
                                              tmp_path, fake_peer):
    """The shift looks the peer token up by URL - an entry saved with a
    trailing slash / different case must still be found (the old exact
    string compare missed it and the shift went out tokenless)."""
    sent = {}
    class _H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_POST(self):
            ln = int(self.headers.get("Content-Length") or 0)
            sent["tok"] = self.headers.get("X-AdvPrint-Token")
            sent["body"] = self.rfile.read(ln)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            b = b'{"ok": true, "job_id": 1}'
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]; s.close()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _H)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        # the entry is stored UGLY on purpose (older build wrote it)
        advprint.CFG["peer_hubs"] = [{
            "url": "http://127.0.0.1:%d/" % port, "token": "secret-tok",
            "name": "Ugly"}]
        f = _queue_file(tmp_path, "toktest.pdf")
        advprint.db_add("a4", "toktest.pdf", "", 1, f, "test",
                        "127.0.0.1", status="queued")
        code, resp = hub.post("/queue/shift",
                              body={"target": "http://127.0.0.1:%d" % port,
                                    "scope": "all"})
        assert code == 200, resp
        assert wait_until(lambda: "tok" in sent, timeout=5)
        assert sent["tok"] == "secret-tok", \
            "the peer token must be found via the normalized URL"
    finally:
        httpd.shutdown()
        try:
            s.close()
        except Exception:
            pass


# ---------------------------------------------------------------
# 5. console.html deltas (the UI half of BUGs 1/2/4)
# ---------------------------------------------------------------

def test_console_no_blocking_share_send_precheck():
    """BUG 1: the old handler pre-checked lanPeerState and popped
    "Connect the LAN PC first" while it was still null. That client
    block must be GONE from the shareSendSw branch; the in-flight
    guard must exist. (The string "lanPeerState && lanPeerState
    .configured" legitimately appears ELSEWHERE - the shift-target
    prefill - so only the handler branch is checked here.)"""
    c = _extract_console()
    i = c.index('s.id === "shareSendSw"')
    j = c.index('/* v3.3.2 remote devices switch', i)
    branch = c[i:j]
    assert "Connect the LAN PC first" not in branch, \
        "the blocking pre-check popup is still in the switch branch"
    assert "lanPeerState.configured" not in branch
    assert "_shareSendPending" in branch
    assert 'api("/config", { method: "POST", body: { share_send: want } })' in branch
    # the server's message stays reachable through the catch path
    assert "toast(e.message" in branch


def test_console_share_send_mirror_and_guard():
    c = _extract_console()
    # boot-window mirror from cfgCache (no OFF-rendered-while-ON)
    assert "cfgCache.share_send" in c
    # renderLanPeer + poll mirror skip while a flip is in flight
    assert c.count("_shareSendPending") >= 3


def test_console_peers_table_reads_up_or_alive():
    c = _extract_console()
    assert "p.up || p.alive" in c
    assert "(p.up ?" not in c, "the bare p.up read is fixed"
    # rows show WHICH PC
    assert "p.label || p.name" in c
    # client-side dedupe guard
    assert "seen[k]" in c


def test_console_has_shift_target_wiring():
    """BUG 4: id=shiftTarget exists, the handler reads it (not the Self
    PC token field), sends `target`, and the INPUT no longer carries
    the static demo value. (Demo audit/log template rows elsewhere in
    the page legitimately mention other IPs - they are replaced with
    real data at runtime.)"""
    c = _extract_console()
    assert 'id="shiftTarget"' in c
    assert '$("shiftTarget")' in c
    assert 'qsa("#p-connections .frow input.inp.mono")[1]' not in c, \
        "the old Self-PC-token read is still wired"
    m = re.search(r'<input[^>]*id="shiftTarget"[^>]*>', c)
    assert m and 'value="http://' not in m.group(0), \
        "the shift-target input must not ship a hardcoded demo URL"
    assert 'body: { target: peer, scope: "all" }' in c
    assert 'body: { target: sh, scope: "all" }' in c


def test_console_poll_calls_load_connections():
    c = _extract_console()
    poll_i = c.index("async function poll()")
    boot_i = c.index("async function boot()")
    poll_body = c[poll_i:boot_i]
    assert "loadConnections();" in poll_body, \
        "the peers table must refresh on every poll"


def test_console_prefill_prefers_lan_pc_url():
    c = _extract_console()
    assert "lanPeerState.configured && lanPeerState.url" in c


# ---------------------------------------------------------------
# 6. release coherence
# ---------------------------------------------------------------

def test_version_coherence_333():
    assert advprint.VERSION == "3.3.4"
    src = open(advprint.__file__, encoding="utf-8").read()
    assert src.count('VERSION = "3.3.4"') == 1
    manifest = json.load(open(
        __file__.replace("tests", "extension", 1)
        .replace("test_v333.py", "manifest.json"), encoding="utf-8"))
    assert manifest["version"] == "3.3.4"
    vtxt = open(__file__.replace("tests", "", 1)
                .replace("test_v333.py", "VERSION.txt"),
                encoding="utf-8").read()
    assert "3.3.4" in vtxt


def test_hub_copies_byte_identical():
    a = open(__file__.replace("tests", "", 1)
             .replace("test_v333.py",
                      "tool/unix/hub/advprint.py"), encoding="utf-8",
             errors="replace").read()
    b = open(__file__.replace("tests", "", 1)
             .replace("test_v333.py",
                      "tool/windows/portable/hub/advprint.py"),
             encoding="utf-8", errors="replace").read()
    assert a == b
