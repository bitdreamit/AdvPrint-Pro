"""v3.4.7 - ONE PORT FOR EVERYTHING + POPUP REMEMBERS THE LAST PRINTER.

The user asked the right question about v3.3.5: "why not [the] hub
default port only one port to handel diffrent pc to connect throug
ipp or other". Answer: because that IS enough - the v3.3.5 dedicated
per-printer ports (9236, 9237, ... + firewall 9235-9259) are removed
again. Exactly like a CUPS server, ONE TCP port serves every queue:

  * /ipp/print                 -> the default queue (hub port)
  * /ipp/print/<printer>       -> that ONE printer (hub port)
  * per-queue IDENTITY: unique printer-name, STABLE unique
    printer-uuid, the client's own URI echoed, one mDNS service per
    queue with its own rp + uuid on the SAME SRV port

FEATURE: the popup printer selector showed the FIRST printer after
every open/reload because it read "default_printer" (the hub answers
"default"); the popup now reads the real field, REMEMBERS the last
picked printer (chrome.storage advLastPrinter) and marks the OS
default in the list.

Locked here:
  - every mDNS service announces the ONE hub port (SRV per service)
  - /printers carries the path queue only (no ipp_port/ipp_dedicated)
  - Get-Printer-Attributes on the SAME port answers with the RIGHT
    printer for /ipp/print, queue A and queue B - with DIFFERENT
    printer-uuids (the identity that makes one port safe)
  - the dedicated-port machinery is gone (no ippq_*, no port map)
  - old config.json with ipp_queue_port_map still loads
  - the firewall is back to the single TCP 9235 rule
  - the popup memory + default-marker + field fix
"""
import json
import os
import re
import socket

import pytest

import advprint

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRINTERS = ["HP Laser 103", "Epson L3250"]


# ---------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------

@pytest.fixture
def printers(monkeypatch):
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda max_age=60.0: list(PRINTERS))
    return list(PRINTERS)


@pytest.fixture
def ipp_on(monkeypatch):
    monkeypatch.setitem(advprint.CFG, "ipp_printer", True)
    monkeypatch.setitem(advprint.CFG, "share_lan", True)
    monkeypatch.setattr(advprint, "lan_ip", lambda: "192.168.1.50")


def _gpa_bytes(uri):
    """Get-Printer-Attributes request for ONE printer-uri."""
    opg = advprint._ipp_group(0x01, [
        advprint._ipp_attr(0x47, "attributes-charset", "utf-8"),
        advprint._ipp_attr(0x48, "attributes-natural-language", "en"),
        advprint._ipp_attr(0x45, "printer-uri", uri),
    ])
    return (bytes((1, 1)) + (0x000B).to_bytes(2, "big") +
            (2345).to_bytes(4, "big") + opg + b"\x03")


def _ipp_attr_value(raw, name):
    """First IPP attribute VALUE for a name in a response blob."""
    i = raw.find(name.encode("utf-8"))
    if i < 0:
        return None
    p = i + len(name)
    vlen = int.from_bytes(raw[p:p + 2], "big")
    return raw[p + 2:p + 2 + vlen].decode("utf-8", "replace")


def _parse_records(packet):
    """Tiny DNS answer parser for OUR mDNS packets (no compression)."""
    i = 12
    qd = int.from_bytes(packet[4:6], "big")
    an = int.from_bytes(packet[6:8], "big")

    def _name(pos):
        labels = []
        while True:
            ln = packet[pos]
            pos += 1
            if ln == 0:
                break
            labels.append(packet[pos:pos + ln].decode("utf-8", "replace"))
            pos = pos + ln
        return ".".join(labels), pos

    for _ in range(qd):
        _, i = _name(i)
        i += 4
    out = []
    for _ in range(an):
        name, i = _name(i)
        rtype = int.from_bytes(packet[i:i + 2], "big")
        i += 2 + 2 + 4
        rdlen = int.from_bytes(packet[i:i + 2], "big")
        i += 2
        out.append((name, rtype, packet[i:i + rdlen]))
        i += rdlen
    return out


class _CaptureSock:
    def __init__(self):
        self.sent = []

    def sendto(self, pkt, addr):
        self.sent.append((bytes(pkt), addr))


# ---------------------------------------------------------------
# ONE port - mDNS
# ---------------------------------------------------------------

def test_mdns_services_all_announce_the_hub_port(printers):
    hub_port = int(advprint.CFG.get("port", 9235))
    svcs = advprint._mdns_services()
    assert len(svcs) == 3                    # central + 2 printers
    for inst, rp, ty, note, slug, port in svcs:
        assert port == hub_port, inst        # THE one port for all
    rps = [s[1] for s in svcs]
    assert rps[0] == "ipp/print"
    assert "ipp/print/hp-laser-103" in rps
    assert "ipp/print/epson-l3250" in rps
    # every instance still unique + every slug unique
    assert len(set(s[0] for s in svcs)) == 3
    slugs = [s[4] for s in svcs[1:]]
    assert len(set(slugs)) == 2


def test_mdns_rrset_one_srv_per_service_all_on_hub_port(
        printers, monkeypatch):
    advprint._mdns_state["sock"] = _CaptureSock()
    monkeypatch.setattr(advprint, "lan_ip", lambda: "192.168.1.50")
    try:
        advprint._mdns_announce("192.168.1.50")
        pkt = advprint._mdns_state["sock"].sent[0][0]
    finally:
        advprint._mdns_state["sock"] = None
    recs = _parse_records(pkt)
    srv = [(n, int.from_bytes(rd[4:6], "big"))
           for n, rt, rd in recs if rt == 33]
    hub_port = int(advprint.CFG.get("port", 9235))
    assert len(srv) == 3                     # one SRV PER service
    assert {p for _, p in srv} == {hub_port}  # ALL on the ONE port
    # the instances stay distinct so every queue is separately
    # discoverable (the rp path + uuid tell the queues apart)
    assert len({n for n, _ in srv}) == 3


def test_mdns_unicast_srv_query_answers_the_hub_port(
        printers, monkeypatch):
    advprint._mdns_state["sock"] = _CaptureSock()
    monkeypatch.setattr(advprint, "lan_ip", lambda: "192.168.1.50")
    inst = advprint._mdns_services()[1][0]
    try:
        pkt = advprint._mdns_packet(
            [], questions=advprint._mdns_encode_name(
                inst + "._ipp._tcp.local") +
            (33).to_bytes(2, "big") + (1).to_bytes(2, "big"),
            qdcount=1)
        advprint._mdns_answer_query(pkt, ("192.168.1.99", 42512),
                                    "192.168.1.50")
        assert advprint._mdns_state["sock"].sent
        out = advprint._mdns_state["sock"].sent[0][0]
    finally:
        advprint._mdns_state["sock"] = None
    recs = _parse_records(out)
    srv = [int.from_bytes(rd[4:6], "big")
           for n, rt, rd in recs if rt == 33]
    assert srv == [int(advprint.CFG.get("port", 9235))]


def test_per_queue_uuids_stay_unique_and_stable(printers):
    u_hp = advprint._ipp_printer_uuid("hp-laser-103")
    u_ep = advprint._ipp_printer_uuid("epson-l3250")
    u_gen = advprint._ipp_printer_uuid(None)
    assert len({u_hp, u_ep, u_gen}) == 3     # identity is per queue
    assert advprint._ipp_printer_uuid("hp-laser-103") == u_hp  # stable


# ---------------------------------------------------------------
# ONE port - HTTP surface
# ---------------------------------------------------------------

def test_printers_payload_carries_path_queue_only(hub, printers, ipp_on,
                                                  monkeypatch):
    monkeypatch.setattr(advprint, "default_printer_cached",
                        lambda: PRINTERS[0])
    code, j = hub.get("/printers")
    assert code == 200
    assert j["default"] == PRINTERS[0]       # popup field fix (hub side)
    items = {p["name"]: p for p in j["printers"] if not p["is_group"]}
    hub_port = int(advprint.CFG.get("port", 9235))
    for n in PRINTERS:
        assert ("/ipp/print/" in items[n]["ipp_queue"]
                and ":%d" % hub_port in items[n]["ipp_queue"])
        assert items[n]["ipp_path"] == advprint._ipp_queue_slug(n)
        # the dedicated-port fields are GONE
        assert "ipp_dedicated" not in items[n]
        assert "ipp_port" not in items[n]


def test_get_printer_attributes_one_port_three_queues(
        hub, printers, ipp_on):
    """THE core one-port proof: on the SAME host:port, the generic
    queue, queue A and queue B each answer with their OWN printer-name
    and their own DIFFERENT printer-uuid."""
    base = "ipp://hub:%d" % int(advprint.CFG.get("port", 9235))
    seen = {}
    for key, path in (("generic", "/ipp/print"),
                      ("hp", "/ipp/print/hp-laser-103"),
                      ("epson", "/ipp/print/epson-l3250")):
        code, payload = hub.req("POST", path, token=None,
                                raw=_gpa_bytes(base + path),
                                content_type="application/ipp")
        assert code == 200, key
        raw = payload if isinstance(payload, bytes) else bytes(payload)
        seen[key] = (_ipp_attr_value(raw, "printer-name"),
                     _ipp_attr_value(raw, "printer-uuid"))
    assert seen["generic"][0] == socket.gethostname()
    assert seen["hp"][0] == "HP Laser 103"
    assert seen["epson"][0] == "Epson L3250"
    uuids = [seen[k][1] for k in ("generic", "hp", "epson")]
    assert all(uuids) and len(set(uuids)) == 3


def test_unknown_queue_still_validates_on_the_one_port(hub, printers,
                                                       ipp_on):
    code, payload = hub.req(
        "POST", "/ipp/print/ghost-queue", token=None,
        raw=_gpa_bytes("ipp://hub:9235/ipp/print/ghost-queue"),
        content_type="application/ipp")
    assert code == 200
    raw = payload if isinstance(payload, bytes) else bytes(payload)
    assert _ipp_attr_value(raw, "printer-name") == "ghost-queue"


# ---------------------------------------------------------------
# the dedicated-port machinery is GONE
# ---------------------------------------------------------------

def test_dedicated_port_machinery_removed():
    for sym in ("ippq_reconcile", "ippq_stop_all", "ippq_stop_one",
                "_ippq_stop_one", "ipp_queue_port_base",
                "ipp_queue_port_allocations", "ipp_queue_dedicated_url",
                "_IPPQ_HTTPDS", "_IPPQ_MAX_QUEUES"):
        assert not hasattr(advprint, sym), sym
    assert "ipp_queue_ports" not in advprint.CONFIG_KEYS
    assert "ipp_queue_port_map" not in advprint.CONFIG_KEYS
    assert not hasattr(advprint.HubServer, "queue_binding")
    src = open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
               encoding="utf-8", errors="replace").read()
    assert "queue_binding" not in src
    # the ONE-port architecture comment is in place
    assert "ONE PORT FOR EVERYTHING" in src


def test_legacy_config_keys_are_ignored(tmp_path, monkeypatch):
    """An upgraded install may still carry the v3.3.5 keys - they must
    load without error and stay ignored."""
    monkeypatch.setitem(advprint.CFG, "data_dir", str(tmp_path))
    # init_config() applies disk values INTO the global CFG - snapshot
    # everything it can touch so no other test sees the legacy token
    for k in ("token", "token_header_only", "allowed_origins"):
        monkeypatch.setitem(advprint.CFG, k, advprint.CFG.get(k))
    (tmp_path / "config.json").write_text(json.dumps({
        "token": "legacy-token-x", "token_header_only": False,
        "ipp_queue_ports": False,
        "ipp_queue_port_map": {"X": 9236}}), encoding="utf-8")
    disk = advprint.read_config_file()
    assert disk["ipp_queue_port_map"] == {"X": 9236}   # read is tolerant
    advprint.init_config()                             # apply is silent
    assert "ipp_queue_ports" not in advprint.CFG
    assert "ipp_queue_port_map" not in advprint.CFG


def test_firewall_back_to_the_single_hub_port():
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8", errors="replace").read()
    assert "localport=9235-9259" not in nsi
    assert 'add rule name="AdvPrint Pro Queues"' not in nsi
    # the v3.3.5 leftover is still cleaned up on upgrade
    assert 'delete-rule name="AdvPrint Pro Queues"' in nsi
    assert 'add rule name="AdvPrint Pro" dir=in action=allow ' \
        'protocol=TCP localport=9235' in nsi


# ---------------------------------------------------------------
# FEATURE - popup remembers the last printer
# ---------------------------------------------------------------

def _ext(name):
    return open(os.path.join(ROOT, "extension", name),
                encoding="utf-8").read()


def test_popup_reads_the_real_default_field():
    src = _ext("popup.js")
    # the FIELD FIX: the hub answers "default" (default_printer never
    # existed - the old code ignored it and showed the FIRST printer)
    assert "r.default || r.default_printer" in src


def test_popup_remembers_and_autoselects_the_last_printer():
    src = _ext("popup.js")
    assert "advLastPrinter" in src
    # saved on every real user change ...
    assert "chrome.storage.local.set({ advLastPrinter: name })" in src
    # ... and read back with a safe fallback on every load
    assert '.get({ advLastPrinter: "" })' in src
    # the selection priority: hub default -> remembered -> first
    assert "_printerMap.includes(_printerApplied)" in src
    assert "_printerMap.includes(remembered)" in src
    # programmatic select only - no command on popup open/reload
    assert re.search(r"sel\.value = wanted;", src)
    assert 'AdvPrintI18n.t("popPrinterDefaultTag")' in src
    assert 'AdvPrintI18n.t("popPrinterLastUsed")' in src


def test_popup_i18n_keys_exist_en_and_bn():
    i18n = _ext("i18n.js")
    assert 'popPrinterDefaultTag: "default"' in i18n
    assert 'popPrinterLastUsed: "Last used:"' in i18n
    assert 'popPrinterDefaultTag: "ডিফল্ট"' in i18n
    assert 'popPrinterLastUsed: "সর্বশেষ ব্যবহৃত:"' in i18n
    assert i18n.count("3.4.7") >= 2


def test_console_cards_lead_with_the_path_queue():
    src = open(os.path.join(ROOT, "tool", "unix", "hub", "console.html"),
               encoding="utf-8").read()
    assert "var leadUrl = p.ipp_queue || \"\";" in src
    assert "p.ipp_dedicated" not in src
    assert "ONE port serves" in src
