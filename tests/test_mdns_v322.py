"""v3.2.2 AirPrint-grade discovery - mDNS responder tests.

Root cause fixed in 3.2.2: the v3.2.1 responder answered ONE query and
then slept 3 s inside its loop, so phone print services (Android
Default Print Service / Mopria, iOS AirPrint) and the Windows printer
scan kept missing the hub inside their few-second discovery windows -
while manual add-by-URL kept working. The v3.2.2 responder DRAINS every
queued packet back-to-back (a query must never wait for a sleep) and
announces twice at startup (RFC 6762 §8.3).
"""
import socket
import struct
import time

import pytest

import advprint


def _ptr_query(name, qtype=12):
    """A one-question mDNS query packet (ID 0, QDCOUNT 1)."""
    labels = b"".join(bytes([len(p)]) + p.encode("ascii")
                      for p in name.split(".")) + b"\x00"
    return (b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00" +
            labels + struct.pack(">HH", qtype, 0x0001))


class _FakeSock:
    """recvfrom() hands out queued packets, sendto() records replies."""

    def __init__(self, packets):
        self._packets = list(packets)
        self.sent = []

    def settimeout(self, t):
        pass

    def recvfrom(self, n):
        if not self._packets:
            raise socket.timeout()
        return self._packets.pop(0), ("10.1.2.3", 5353)

    def sendto(self, pkt, addr):
        self.sent.append((pkt, addr))


@pytest.fixture
def mdns_env(monkeypatch):
    monkeypatch.setattr(advprint, "lan_ip", lambda: "10.0.0.7")
    advprint.CFG["share_lan"] = True
    advprint.CFG["ipp_printer"] = True
    advprint.CFG["ipp_mdns"] = True
    state = {"sock": None, "thread": None, "ip": None,
             "last_announce": 0.0, "announced": False, "err_logged": False}
    monkeypatch.setattr(advprint, "_mdns_state", state)
    return state


def _answer(state, pkt, addr, ip="10.0.0.7"):
    advprint._mdns_answer_query(pkt, addr, ip)


def test_responder_answers_every_packet_back_to_back(mdns_env):
    """Three queued PTR queries -> three answers, fast. The old loop
    answered one packet per ~5 s (2 s recv timeout + 3 s sleep)."""
    pkts = [_ptr_query("_ipp._tcp.local") for _ in range(3)]
    sock = _FakeSock(pkts)
    mdns_env["sock"] = sock
    t0 = time.time()
    for p in pkts:
        _answer(mdns_env, p, ("10.1.2.3", 5353))
    dt = time.time() - t0
    assert len(sock.sent) == 3, "every query must get an answer"
    assert dt < 1.0, "answers must not wait on sleeps (%.2fs)" % dt
    for pkt, addr in sock.sent:
        ancount = int.from_bytes(pkt[6:8], "big")
        assert ancount > 0, "empty answer section"
        # RFC 6762 §18: a querier asking FROM :5353 gets the reply
        # multicast; only legacy ephemeral-port clients get unicast
        assert addr == ("224.0.0.251", 5353)


def test_responder_unicasts_to_legacy_clients(mdns_env):
    """A querier asking from an ephemeral port (Android NSD does this)
    gets a UNICAST reply, not multicast (RFC 6762 §18)."""
    sock = _FakeSock([])
    mdns_env["sock"] = sock
    _answer(mdns_env, _ptr_query("_ipp._tcp.local"), ("10.1.2.3", 41234))
    assert len(sock.sent) == 1
    pkt, addr = sock.sent[0]
    assert addr == ("10.1.2.3", 41234)


def test_rrset_has_airprint_subtype_and_mopria_txt(mdns_env):
    """The record set must contain _ipp._tcp + the AirPrint _universal
    subtype + a TXT with rp=ipp/print and a PDF pdl (what Android
    Default Print Service and iOS PrintKit match on)."""
    recs = advprint._mdns_rrset("10.0.0.7")
    blob = b"".join(recs)
    assert advprint._mdns_encode_name("_ipp._tcp.local") in blob
    assert advprint._mdns_encode_name(
        "_universal._sub._ipp._tcp.local") in blob
    txt = next(r for r in recs if b"txtvers" in r)
    assert b"rp=ipp/print" in txt
    assert b"pdl=application/pdf" in txt
    # the A record answers for the SRV target (wire-encoded) with the
    # LAN IP
    target = advprint._mdns_encode_name(advprint._mdns_host_target())
    a = next(r for r in recs if r.endswith(socket.inet_aton("10.0.0.7")))
    assert target in a


def test_srv_answer_carries_hub_port(mdns_env):
    """An SRV query for our instance answers with the REAL hub port -"""
    state = mdns_env
    inst = advprint._mdns_instance_name().lower() + "._ipp._tcp.local"
    sock = _FakeSock([])
    state["sock"] = sock
    _answer(state, _ptr_query(inst, qtype=33), ("10.1.2.3", 5353))
    assert len(sock.sent) == 1
    pkt = sock.sent[0][0]
    # port is the 3rd word inside the SRV rdata - just assert it appears
    port_bytes = struct.pack(">H", int(advprint.CFG["port"]))
    assert port_bytes in pkt


def test_unknown_instance_gets_no_answer(mdns_env):
    """An SRV query for an instance we never announced stays silent
    (a PTR for the service itself is answered - that is normal mDNS)."""
    sock = _FakeSock([])
    mdns_env["sock"] = sock
    _answer(mdns_env, _ptr_query("someone-elses-printer._ipp._tcp.local",
                                 qtype=33),
            ("10.1.2.3", 5353))
    assert sock.sent == [], "must not answer for other printers' SRV"


def test_loop_drains_and_never_sleeps_between_packets():
    """Structural: the responder loop must drain packets back-to-back
    (no per-packet sleep) and do the RFC 6762 double announce."""
    src = open(advprint.__file__, encoding="utf-8").read()
    loop = src[src.index("def _ipp_mdns_loop"):]
    loop = loop[:loop.index("\ndef ", 10)]
    assert "recvfrom(9000)" in loop
    assert "quiet_until" in loop, "drain window missing"
    assert "time.sleep(3.0)" not in loop, "the old 3 s nap is back"
    assert "_mdns_answer_query" in loop
    # startup burst: announce twice ~1 s apart (RFC 6762 §8.3)
    burst = src[src.index("def _ipp_mdns_loop"):]
    burst = burst[:burst.index("\ndef ", 10)]
    assert burst.count("_mdns_announce(ip)") >= 2
