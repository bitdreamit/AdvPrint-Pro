"""v3.3.0 - THE ANY-PC INVITE + DUAL-STACK LISTENER RELEASE.

Locks the three user-reported bugs end to end:

BUG 1 - the one-click invite /connect?t=<token> pointed the OTHER PC at
  the WRONG hub: the page built the peer URL from the serving hub's own
  lan_ip() guess (never the address the visitor typed), and a user who
  opened the invite ON the hub PC itself silently added the hub to
  ITSELF ("it redirect own pc"). v3.3.0: per-device peer URL (Host
  header), a self-invite EXPLAINER page for loopback visitors, POST
  /peer-connect refuses self-invites, the page probes the visiting
  PC's own hub, and the ?t= mismatch explains a DIFFERENT PC's hub.

BUG 2 - every LAN listener (9235 LAN, 631 mirror, RAW 9100) bound ONE
  IPv4 address and never spoke IPv6. v3.3.0: bind_listener_sockets()
  binds one IPv4 socket per interface IP + one [::] socket (V6ONLY),
  partial binds degrade gracefully, _bind_signature() drives automatic
  rebinds, health/boot expose raw_addrs / ipp_std.addrs /
  lan_bind_addrs / lan_ips6, and the mDNS announce carries AAAA.

BUG 3 - per-printer IPP queues must work for ANY printer that exists:
  the old [^a-z0-9] slug folded every non-ASCII printer name (Bangla,
  Arabic, CJK) to the single slug "printer", so those queues collided.
  v3.3.0: Unicode-aware slugs (percent-encoded in URLs/URIs), the
  collision-tolerant _ipp_queue_key() join key, a forced printer-list
  refresh on negative matches, live queues listed in the 404, and the
  mDNS per-printer cap 12 -> 24.

Also locked: version coherence 3.3.0 everywhere, byte-identical hub
copies, and the new release docs.
"""
import json
import os
import re
import socket
import struct
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

import advprint
from conftest import ROOT

HUB_DIR = os.path.join(ROOT, "tool", "windows", "portable", "hub")
UNIX_HUB = os.path.join(ROOT, "tool", "unix", "hub")
EXT = os.path.join(ROOT, "extension")

CONSOLE = open(os.path.join(HUB_DIR, "console.html"),
               encoding="utf-8").read()
ADVPRINT_SRC = open(os.path.join(HUB_DIR, "advprint.py"),
                    encoding="utf-8").read()
VERSION_TXT = open(os.path.join(ROOT, "VERSION.txt"),
                   encoding="utf-8").read()
MANIFEST = json.load(open(os.path.join(EXT, "manifest.json"),
                          encoding="utf-8"))
CHANGELOG = open(os.path.join(ROOT, "CHANGELOG.md"),
                 encoding="utf-8").read()
NSI = open(os.path.join(ROOT, "installer", "setup.nsi"),
           encoding="utf-8").read()

# ---- minimal IPP wire helpers (same encoding as tests/test_ipp.py) ----
T_OP, T_END = 0x01, 0x03
V_INT, V_BOOL, V_ENUM = 0x21, 0x22, 0x23
V_TEXT, V_NAME, V_KEYWORD = 0x41, 0x42, 0x44
V_URI, V_CHARSET, V_LANG, V_MIME = 0x45, 0x47, 0x48, 0x49


def _attr(tag, name, value):
    if isinstance(value, int):
        value = struct.pack(">i", value)
    nb = name.encode()
    vb = value if isinstance(value, bytes) else str(value).encode()
    return (bytes([tag]) + len(nb).to_bytes(2, "big") + nb +
            len(vb).to_bytes(2, "big") + vb)


def _req(op, uri_path="/ipp/print", port=None, doc=b"", rid=7, ver=(1, 1)):
    out = bytearray()
    out += bytes(ver) + op.to_bytes(2, "big") + rid.to_bytes(4, "big")
    out += bytes([T_OP])
    out += _attr(V_CHARSET, "attributes-charset", "utf-8")
    out += _attr(V_LANG, "attributes-natural-language", "en")
    if port is not None:
        out += _attr(V_URI, "printer-uri",
                     "http://10.26.94.55:%d%s" % (port, uri_path))
        out += _attr(V_NAME, "requesting-user-name", "pytest")
    out += bytes([T_END])
    return bytes(out) + doc


def _resp_groups(raw):
    """Walk an IPP response into [(name, [(tag, value_str), ...]), ...]."""
    assert raw[:2] in (b"\x01\x01", b"\x01\x00", b"\x02\x00", b"\x02\x01")
    status = int.from_bytes(raw[2:4], "big")
    rid = int.from_bytes(raw[4:8], "big")
    attrs = []
    i, n = 8, len(raw)
    cur = None
    last = ("",)
    while i < n:
        b = raw[i]
        if b == T_END:
            break
        if b in (T_OP, 0x02, 0x04, 0x05):
            cur = []
            attrs.append(cur)
            i += 1
            continue
        nl = int.from_bytes(raw[i + 1:i + 3], "big")
        i += 3
        name = raw[i:i + nl].decode("utf-8", "replace")
        i += nl
        vl = int.from_bytes(raw[i:i + 2], "big")
        i += 2
        val = raw[i:i + vl]
        i += vl
        if cur is not None:
            if not name:
                name = last[0] if last else ""
            else:
                last = (name,)
            cur.append((name, (b, val.decode("utf-8", "replace"))))
    return status, rid, attrs


def _vals(group, name):
    return [v for (n, v) in group if n == name]


# ---------------------------------------------------------------
# 1. version coherence 3.3.0
# ---------------------------------------------------------------

def test_version_330_everywhere():
    assert advprint.VERSION == "3.3.2"
    assert advprint.VERSION_NAME.startswith("v3.3.2")
    assert "SHARE SEND MODE" in advprint.VERSION_NAME
    assert "3.3.2" in VERSION_TXT
    assert MANIFEST["version"] == "3.3.2"
    assert 'var _apVerFallback = "3.3.2";' in open(
        os.path.join(EXT, "content", "api.js"), encoding="utf-8").read()
    assert 'BOOT.version || "3.3.2"' in CONSOLE
    assert "## v3.3.0 - THE ANY-PC INVITE + DUAL-STACK LISTENER RELEASE" \
        in CHANGELOG
    assert 'VIProductVersion "3.3.2.0"' in NSI
    assert "AdvPrint-Pro-Setup-3.3.2.exe" in NSI
    # old fallback gone from the live UI source
    assert 'BOOT.version || "3.2.9"' not in CONSOLE


def test_release_docs_330_exist():
    notes = open(os.path.join(ROOT, "docs", "RELEASE-NOTES-v3.3.0.md"),
                 encoding="utf-8").read()
    assert "redirect own pc" in notes
    assert "bind_listener_sockets" in notes
    assert "IPv6" in notes
    guide = open(os.path.join(ROOT,
                 "docs", "AdvPrint-Pro-v3.3.0-A-to-Z-DEV-GUIDE.md"),
                 encoding="utf-8").read()
    assert "_ipp_queue_key" in guide
    assert "_bind_signature" in guide
    assert "scripts/embed_console.py" in guide


def test_hub_copies_byte_identical():
    for name in ("advprint.py", "console.html"):
        a = open(os.path.join(UNIX_HUB, name), "rb").read()
        b = open(os.path.join(HUB_DIR, name), "rb").read()
        assert a == b, "%s copies drifted" % name


# ---------------------------------------------------------------
# 2. BUG 1 - the invite connects the RIGHT PC
# ---------------------------------------------------------------

def test_connect_page_uses_visitor_host_not_lan_ip(monkeypatch):
    """The peer URL on the page is built from the address the VISITOR
    used (req_host) - never the serving hub's own lan_ip() guess."""
    monkeypatch.setattr(advprint, "lan_ip", lambda: "10.26.94.206")
    page = advprint.connect_page_html(
        "tok123", "AI-Lab", req_host="192.168.1.104", req_port=9235)
    assert "http://192.168.1.104:9235" in page
    # the PEER URL span (what the form saves) carries the visitor's address
    assert 'id="peerUrl">http://192.168.1.104:9235<' in page
    assert 'name="url" id="fUrl" value="http://192.168.1.104:9235"' in page
    # the form still posts to the VISITING PC's own loopback hub
    assert 'action="http://127.0.0.1:9235/peer-connect"' in page
    # the page probes the visitor's own hub before the click
    assert '127.0.0.1:" + DPORT + "/health' in page
    assert "peer-connect" in page


def test_connect_page_loopback_host_falls_back(monkeypatch):
    """A loopback Host header (hub owner opening it locally) falls back
    to the hub's LAN address so the owner still copies a shareable URL."""
    monkeypatch.setattr(advprint, "lan_ip", lambda: "192.168.1.101")
    monkeypatch.setitem(advprint.CFG, "share_lan", True)
    page = advprint.connect_page_html("tok123", "AI-Lab",
                                      req_host="127.0.0.1", req_port=9235)
    assert "http://192.168.1.101:9235" in page


def test_connect_page_lists_other_addresses(monkeypatch):
    """v3.3.0 BUG 1+2: every hub interface IP (v4 AND v6) appears as a
    'use this' chip so the visitor can swap the peer URL."""
    monkeypatch.setattr(advprint, "list_lan_ips",
                        lambda *a, **k: ["192.168.1.101", "10.26.94.206"])
    monkeypatch.setattr(advprint, "list_lan_ips6",
                        lambda *a, **k: ["2001:db8::10"])
    page = advprint.connect_page_html("tok", "AI-Lab",
                                      req_host="192.168.1.101",
                                      req_port=9235)
    assert "use this" in page
    assert "http://[2001:db8::10]:9235" in page      # IPv6 bracketed
    assert "http://10.26.94.206:9235" in page


def test_connect_page_visitor_is_hub_gets_explainer():
    """A visitor ON the hub PC gets the self-invite explainer - never
    the add-to-self form (the 'it redirect own pc' bug)."""
    page = advprint.connect_page_html("tok", "AI-Lab",
                                      req_host="192.168.1.101",
                                      req_port=9235, visitor_is_hub=True)
    assert "hub PC" in page
    assert "OTHER PC" in page
    assert "peer-connect" not in page          # no form to add itself
    assert "/connect?t=tok" in page            # the link to carry over


def test_connect_error_names_different_hub():
    page = advprint.connect_error_html(
        "The ?t= parameter does not match THIS hub's token -"
        " the invite link is old, mistyped, or it belongs to a"
        " DIFFERENT PC's hub.")
    assert "DIFFERENT PC" in page


def test_peer_connect_refuses_self_invite(hub, cfg_reset):
    """POSTing the hub's OWN url must be refused - nothing saved."""
    hub_url = "http://192.168.1.101:%d" % advprint.CFG["port"]
    monkey = pytest.MonkeyPatch()
    monkey.setattr(advprint, "lan_ip", lambda: "192.168.1.101")
    monkey.setattr(advprint, "list_lan_ips",
                   lambda *a, **k: ["192.168.1.101"])
    try:
        body = urllib.parse.urlencode({
            "url": hub_url, "token": "whatever",
            "name": "SelfPC", "confirm": "1"}).encode()
        req = urllib.request.Request(
            hub.base + "/peer-connect", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                page = r.read().decode()
                code = r.getcode()
        except urllib.error.HTTPError as e:
            page = e.read().decode()
            code = e.code
    finally:
        monkey.undo()
    assert code == 400
    assert "own invite" in page
    assert advprint.CFG.get("peer_hubs") in (None, [],) or \
        all("192.168.1.101" not in str(p.get("url"))
            for p in advprint.CFG.get("peer_hubs") or [])


def test_peer_connect_still_accepts_a_real_peer(hub, cfg_reset):
    """A LAN PC adding ANOTHER PC's hub still works end to end."""
    peer_url = "http://192.168.1.200:%d" % advprint.CFG["port"]
    body = urllib.parse.urlencode({
        "url": peer_url, "token": "peer-token",
        "name": "Shop-PC", "confirm": "1"}).encode()
    req = urllib.request.Request(
        hub.base + "/peer-connect", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as r:
        page = r.read().decode()
    assert "Connected" in page or "connected" in page
    peers = advprint.CFG.get("peer_hubs") or []
    assert any(p.get("url") == peer_url and p.get("name") == "Shop-PC"
               for p in peers)


def test_invite_page_via_http_is_per_device(hub, cfg_reset):
    """End to end: GET /connect with a LAN Host header serves the page
    with THAT address as the peer URL."""
    advprint.CFG["share_lan"] = True
    # route /connect is reachable without auth (MGMT_OPEN_GET_EXACT)
    req = urllib.request.Request(
        hub.base + "/connect?t=%s&n=OtherLab"
        % urllib.parse.quote(advprint.CFG["token"]),
        headers={"Host": "192.168.1.104:%d" % advprint.CFG["port"],
                 "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=10) as r:
        page = r.read().decode()
    assert "http://192.168.1.104:%d" % advprint.CFG["port"] in page


# ---------------------------------------------------------------
# 3. BUG 2 - dual-stack, every-interface listeners
# ---------------------------------------------------------------

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_bind_listener_sockets_binds_both_stacks():
    port = _free_port()
    socks, errs = advprint.bind_listener_sockets(port, "test")
    try:
        assert len(socks) >= 1
        v6 = [s for s in socks if s.family == socket.AF_INET6]
        v4 = [s for s in socks if s.family == socket.AF_INET]
        if socket.has_dualstack_ipv6():
            assert v6, "expected the [::] listener when dual-stack exists"
            for s in v6:
                assert s.getsockname()[0] == "::"
                # V6ONLY=1: the v6 socket never takes IPv4 traffic
                v6only = s.getsockopt(socket.IPPROTO_IPV6,
                                      socket.IPV6_V6ONLY)
                assert v6only == 1
        for s in v4:
            host = s.getsockname()[0]
            assert not host.startswith("127."), \
                "v4 binds must skip loopback (the loopback hub owns it)"
        # every socket actually accepts connections
        for s in socks:
            probe = socket.socket(s.family, socket.SOCK_STREAM)
            probe.settimeout(3)
            addr = s.getsockname()[:2]
            if s.family == socket.AF_INET6:
                probe.connect(("::1", addr[1]))
            else:
                probe.connect((addr[0], addr[1]))
            probe.close()
        assert isinstance(errs, list)
    finally:
        for s in socks:
            s.close()


def test_bind_listener_sockets_skips_loopback_v4(monkeypatch):
    """127.0.0.1 is NEVER bound by the helper - the loopback hub owns
    exactly that address (other 127.x aliases are bindable and legal,
    which the v3.2.2-era tests rely on)."""
    def fake_ips(*a, **k):
        return ["127.0.0.1", "127.0.0.5", "192.168.1.101"]

    monkeypatch.setattr(advprint, "list_lan_ips", fake_ips)
    port = _free_port()
    socks, errs = advprint.bind_listener_sockets(port, "test")
    try:
        bound_v4 = [s.getsockname()[0] for s in socks
                    if s.family == socket.AF_INET]
        assert "127.0.0.1" not in bound_v4
        assert "127.0.0.5" in bound_v4          # a loopback ALIAS binds
        # 192.168.1.101 is not local in most CI sandboxes - if it DID
        # bind it must appear in the label list, failures are reported
        if "192.168.1.101" not in bound_v4:
            assert any("192.168.1.101" in e for e in errs)
        if socket.has_dualstack_ipv6():
            assert any(s.family == socket.AF_INET6 for s in socks)
    finally:
        for s in socks:
            s.close()


def test_bind_listener_sockets_partial_bind_is_graceful(monkeypatch):
    """One dead IPv4 address must NOT kill the listener - the working
    sockets stay up and the failure is REPORTED, not silent."""
    monkeypatch.setattr(advprint, "list_lan_ips",
                        lambda *a, **k: ["203.0.113.9"])   # TEST-NET-3
    port = _free_port()
    socks, errs = advprint.bind_listener_sockets(port, "test")
    try:
        assert len(socks) >= 1          # the [::] socket still works
        assert errs and "203.0.113.9" in errs[0]
    finally:
        for s in socks:
            s.close()


def test_bind_listener_sockets_raises_when_nothing_binds(monkeypatch):
    monkeypatch.setattr(advprint, "list_lan_ips",
                        lambda *a, **k: ["203.0.113.9"])
    monkeypatch.setattr(advprint.socket, "has_dualstack_ipv6",
                        lambda: False)
    port = _free_port()
    with pytest.raises(OSError):
        advprint.bind_listener_sockets(port, "test")


def test_bind_signature_shape():
    sig = advprint._bind_signature()
    assert isinstance(sig, tuple) and len(sig) == 2
    ips, v6 = sig
    assert isinstance(ips, tuple)
    assert isinstance(v6, bool)


def test_raw_listener_dual_stack_and_stop():
    """RAW 9100: start binds >=1 socket on a free port, the health
    snapshot sees raw_addrs, and stop releases everything."""
    port = _free_port()
    old = advprint.CFG.get("raw_printer_port")
    old_lan = advprint.CFG.get("share_lan")
    advprint.CFG["raw_printer_port"] = port
    advprint.CFG["share_lan"] = True
    try:
        err = advprint.raw_listen_start()
        assert err is None, err
        assert advprint.raw_listen_active()
        assert len(advprint._RAW_SOCKS) >= 1
        for s in advprint._RAW_SOCKS:
            assert s.getsockname()[1] == port
            if s.family == socket.AF_INET:
                assert not s.getsockname()[0].startswith("127.")
        snap = advprint.build_health_snapshot()
        assert snap["raw_active"] is True
        assert snap["raw_addrs"] == list(advprint._RAW_BINDS)
        # start again is a no-op, stop releases
        assert advprint.raw_listen_start() is None
        advprint.raw_listen_stop()
        assert not advprint.raw_listen_active()
        assert advprint._RAW_SOCKS == []
    finally:
        advprint.raw_listen_stop()
        advprint.CFG["raw_printer_port"] = old
        advprint.CFG["share_lan"] = old_lan


def test_health_snapshot_new_address_fields():
    snap = advprint.build_health_snapshot()
    assert "raw_addrs" in snap
    assert "lan_ips6" in snap
    assert "lan_bind_addrs" in snap
    assert isinstance(snap["lan_ips6"], list)
    assert "addrs" in snap["ipp_std"]


def test_boot_json_carries_lan_ips6(hub):
    """The /ui boot JSON exposes the IPv6 address list (v3.3.0 BUG 2)."""
    code, body = hub.get("/ui")
    assert code == 200
    html = body.decode("utf-8")
    start = html.find('<script id="bootjson" type="application/json">') + \
        len('<script id="bootjson" type="application/json">')
    end = html.find("</script>", start)
    boot = json.loads(html[start:end])
    assert "lan_ips6" in boot and isinstance(boot["lan_ips6"], list)
    assert "lan_ips" in boot


def test_list_lan_ips6_excludes_link_local_and_loopback():
    ips = advprint.list_lan_ips6()
    for a in ips:
        assert not a.startswith("fe80:")
        assert a != "::1"
        assert not a.startswith("::ffff:")


def _mdns_rtype(rec):
    """Walk the variable-length NAME labels, then read the 2-byte TYPE."""
    i = 0
    while True:
        ln = rec[i]
        if ln == 0:
            i += 1
            break
        i += 1 + ln
    return int.from_bytes(rec[i:i + 2], "big")


def test_mdns_rrset_includes_aaaa_when_available(monkeypatch):
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda *a, **k: [])
    recs_v4 = advprint._mdns_rrset("192.168.1.101")
    a_recs = [r for r in recs_v4 if _mdns_rtype(r) == 1]
    assert a_recs, "A record must always be present"
    assert b"\xc0\xa8\x01\x65" in a_recs[0] or \
        bytes([192, 168, 1, 101]) in a_recs[0]
    recs_v6 = advprint._mdns_rrset("192.168.1.101", ip6="2001:db8::10")
    aaaa = [r for r in recs_v6 if _mdns_rtype(r) == 28]
    assert aaaa, "AAAA record missing when an IPv6 was given"
    assert aaaa[0][-16:] == socket.inet_pton(socket.AF_INET6,
                                             "2001:db8::10")
    # and NO AAAA when the hub has no usable IPv6
    recs_none = advprint._mdns_rrset("192.168.1.101", ip6=None)
    assert not [r for r in recs_none if _mdns_rtype(r) == 28]


def test_mdns_services_cap_raised(monkeypatch):
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda *a, **k: ["Printer %d" % i
                                         for i in range(24)])
    svcs = advprint._mdns_services()
    assert len(svcs) == 25            # 1 generic + 24 per-printer


def test_host_ok_accepts_bracketed_ipv6():
    """v3.3.0 BUG 2 (found by the smoke): with a [::] listener live, an
    IPv6 client sends Host "[::1]" - the old split(":")[0] turned that
    into "[" and rejected every IPv6 client with 421."""
    f = advprint.Handler.__new__(advprint.Handler)
    f.headers = {"Host": "[::1]:%d" % advprint.CFG.get("port", 9235)}
    assert f._host_ok() is True
    f.headers = {"Host": "[2001:db8::10]:9235"}
    assert f._host_ok() is True          # private global unicast
    f.headers = {"Host": "[::1]"}
    assert f._host_ok() is True
    f.headers = {"Host": "192.168.1.50:9235"}
    assert f._host_ok() is True
    f.headers = {"Host": "attacker.example:9235"}
    assert f._host_ok() is False         # the DNS-rebind guard stays


# ---------------------------------------------------------------
# 4. BUG 3 - every printer gets its own active queue
# ---------------------------------------------------------------

def test_slug_unicode_names_get_distinct_slugs():
    bn = "প্রিন্টার ১"
    bn2 = "প্রিন্টার ২"
    s1 = advprint._ipp_queue_slug(bn)
    s2 = advprint._ipp_queue_slug(bn2)
    assert s1 != s2, "distinct printers must get distinct slugs"
    assert s1 != "printer"           # the old collapse is gone
    assert advprint._ipp_queue_slug("HP Laser 103") == "hp-laser-103"
    # underscore-heavy names slug deterministically and MATCH through the
    # join key (the slug itself only has to be distinct + URL-safe)
    s3 = advprint._ipp_queue_slug("HP  Laser___103!!")
    assert advprint._ipp_queue_key(s3) == \
        advprint._ipp_queue_key("HP Laser 103")


def test_ipp_queue_url_percent_encodes_unicode():
    url = advprint.ipp_queue_url("প্রিন্টার ১", host="192.168.1.101")
    assert url.startswith("ipp://192.168.1.101:%d/ipp/print/"
                          % int(advprint.CFG.get("port", 9235)))
    tail = url.rsplit("/", 1)[1]
    assert tail == urllib.parse.quote(
        advprint._ipp_queue_slug("প্রিন্টার ১"), safe="")
    # ASCII slugs pass through untouched (legacy URLs keep working)
    assert advprint.ipp_queue_url("HP Laser 103") .endswith(
        "/ipp/print/hp-laser-103")


def test_ipp_queue_uris_percent_encode_unicode():
    slug = advprint._ipp_queue_slug("প্রিন্টার ১")
    uris = advprint._ipp_queue_uris(slug)
    assert len(uris) == 2
    enc = urllib.parse.quote(slug, safe="")
    assert all(u.endswith("/ipp/print/" + enc) for u in uris)


def test_queue_match_tolerates_every_slug_style(monkeypatch):
    """Dash / underscore / space / %20 variants all resolve to the same
    printer - and old dash slugs keep working after the upgrade."""
    printers = ["HP Laser 103", "প্রিন্টার ১", "Lab_Room_A"]
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda *a, **k: printers)
    assert advprint._ipp_queue_match("hp-laser-103") == "HP Laser 103"
    assert advprint._ipp_queue_match("HP%20Laser%20103") == "HP Laser 103"
    assert advprint._ipp_queue_match("HP_Laser_103") == "HP Laser 103"
    assert advprint._ipp_queue_match("Lab-Room-A") == "Lab_Room_A"
    assert advprint._ipp_queue_match("lab_room_a") == "Lab_Room_A"
    # Unicode: the percent-encoded slug resolves back to the real name
    enc = urllib.parse.quote(advprint._ipp_queue_slug("প্রিন্টার ১"),
                             safe="")
    assert advprint._ipp_queue_match(enc) == "প্রিন্টার ১"
    # raw Bangla name also resolves (client sent it unencoded)
    assert advprint._ipp_queue_match("প্রিন্টার ১") == "প্রিন্টার ১"
    # no match stays empty
    assert advprint._ipp_queue_match("totally-unknown") == ""


def test_negative_match_forces_printer_list_refresh(monkeypatch):
    """A printer added AFTER the list was cached is found immediately:
    the negative answer triggers ONE forced re-enum (rate-limited) and
    the RETRY inside the same call already resolves the queue."""
    state = {"printers": ["Old Printer"], "refreshes": 0}

    def fake_list(max_age=30.0):
        if max_age == 0.0:
            state["refreshes"] += 1
            state["printers"] = ["Old Printer", "New Printer"]
        return list(state["printers"])

    monkeypatch.setattr(advprint, "list_printers_cached", fake_list)
    advprint._QMATCH_CACHE.clear()
    advprint._QMATCH_LAST_FORCE["t"] = 0.0
    # 1) the very first call already finds the new printer: the negative
    #    match on the stale list forces the refresh and retries at once
    assert advprint._ipp_queue_match_cached("new-printer") == "New Printer"
    assert state["refreshes"] == 1
    # 2) the forced refresh is rate-limited: a truly unknown queue inside
    #    the 3 s window does NOT spend another OS re-enum
    advprint._QMATCH_CACHE.clear()
    assert advprint._ipp_queue_match_cached("unknown-queue") == ""
    assert state["refreshes"] == 1
    # 3) after the rate-limit window passes, one more forced refresh
    import time as _time
    advprint._QMATCH_CACHE.clear()
    advprint._QMATCH_LAST_FORCE["t"] = _time.time() - 4.0
    assert advprint._ipp_queue_match_cached("unknown-queue") == ""
    assert state["refreshes"] == 2


def test_404_lists_active_queues(monkeypatch):
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda *a, **k: ["HP Laser 103", "প্রিন্টার ১"])
    hint = advprint._active_queue_hint()
    assert "Active queues right now" in hint
    assert "hp-laser-103" in hint
    assert advprint._ipp_queue_slug("প্রিন্টার ১") in hint


def test_ipp_get_printer_attrs_unicode_queue(monkeypatch):
    """The per-printer queue ECHO works for a Bangla printer name: the
    client asks for the percent-encoded URI and finds it in
    printer-uri-supported."""
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda *a, **k: ["প্রিন্টার ১"])
    monkeypatch.setattr(advprint, "lan_ip", lambda: "10.26.94.206")
    monkeypatch.setitem(advprint.CFG, "share_lan", True)
    port = advprint.CFG["port"]
    slug = advprint._ipp_queue_slug("প্রিন্টার ১")
    enc = urllib.parse.quote(slug, safe="")
    raw = advprint.ipp_handle(
        _req(0x000B, uri_path="/ipp/print/" + enc, port=port),
        "10.26.94.55", printer="প্রিন্টার ১")
    status, rid, groups = _resp_groups(raw)
    assert status == 0
    printer = groups[1]
    uris = [v[1] for v in _vals(printer, "printer-uri-supported")]
    assert "http://10.26.94.206:%d/ipp/print/%s" % (port, enc) in uris
    assert "ipp://10.26.94.206:%d/ipp/print/%s" % (port, enc) in uris
    names = [v[1] for v in _vals(printer, "printer-name")]
    assert names and names[0] == "প্রিন্টার ১"


def test_per_printer_queue_end_to_end(hub, monkeypatch):
    """HTTP end to end: a per-printer queue that exists answers its
    landing page; v3.3.2 BUG 3: an unknown queue answers with the
    GENERIC how-to landing page (HTML 200) instead of a JSON 404, so a
    mistyped name on a Windows/phone add attempt cannot break the flow."""
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda *a, **k: ["HP Laser 103"])
    monkeypatch.setitem(advprint.CFG, "ipp_printer", True)
    code, data = hub.get("/printers")
    assert code == 200
    queues = [p.get("ipp_queue") for p in data["printers"]
              if p.get("ipp_queue")]
    assert queues and any(q.endswith("/ipp/print/hp-laser-103")
                          for q in queues)
    # unknown queue -> generic landing page (HTML 200)
    code2, data2 = hub.get("/ipp/print/totally-unknown-queue")
    assert code2 == 200
    body2 = data2.decode("utf-8", "replace") if isinstance(data2, bytes) \
        else str(data2)
    assert "IPP network printer" in body2
