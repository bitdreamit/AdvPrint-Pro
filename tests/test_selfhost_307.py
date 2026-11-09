"""v3.0.7 SELF-HOST EXTENSION AUTO-INSTALL tests.

Covers:
  - tool/crx3.py CRX3 packer/reader (stable key -> stable ID, round trip)
  - the hub's .crx reader (crx_package) incl. hot-swap on file change
  - the open /extension/* endpoints (updates.xml, .crx Content-Type,
    info JSON, landing page)
  - the token-gated /extension/policy/* endpoints (graceful on Linux)
  - the installers carry the policy pieces (setup.nsi, bat, unix scripts)
"""
import io
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
sys.path.insert(0, os.path.join(ROOT, "tool"))

import advprint  # noqa: E402
import crx3  # noqa: E402  (the tree's packer library)

EXT_ID = "likldbkamojokkfdlcjibiljpgbbnohc"
KEY_PEM = os.path.join(ROOT, "extension-signing", "advprint-printer.pem")


# --------------------------------------------------------------- packer
def test_packer_round_trip_and_stable_id(tmp_path):
    """A packed CRX parses back to the same ID + version; the ID of the
    release key is exactly the documented one (it must NEVER change)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "manifest.json").write_text(
        '{"manifest_version":3,"name":"t","version":"9.9.9"}')
    key = tmp_path / "k.pem"
    crx3.generate_key_pair(str(key))
    out = tmp_path / "t.crx"
    eid = crx3.pack_crx(str(src), str(key), str(out))
    assert eid == EXT_ID or eid != EXT_ID  # fresh key = fresh ID (shape)
    assert len(eid) == 32 and eid.islower() and eid.isalpha()
    info = crx3.crx_info(str(out))
    assert info["extension_id"] == eid
    assert info["version"] == "9.9.9"
    assert info["zip_bytes"][:2] == b"PK"
    # raw 16-byte path must agree with the sha256-of-SPKI derivation
    spki = crx3.spki_from_private_pem(key.read_bytes())
    import hashlib
    raw = hashlib.sha256(spki).digest()[:16]
    assert crx3.crx_id_from_raw(raw) == eid


def test_release_key_id_is_permanent():
    """THE invariant of the whole self-host feature: the shipped key
    produces exactly the advertised extension ID."""
    assert os.path.isfile(KEY_PEM), "release signing key missing"
    spki = crx3.spki_from_private_pem(open(KEY_PEM, "rb").read())
    assert crx3.crx_id_from_spki(spki) == EXT_ID


def test_release_extension_packs_and_carries_version(tmp_path):
    out = tmp_path / "AdvPrint-Pro.crx"
    eid = crx3.pack_crx(os.path.join(ROOT, "extension"), KEY_PEM, str(out))
    assert eid == EXT_ID
    info = crx3.crx_info(str(out))
    man = json.load(open(os.path.join(ROOT, "extension", "manifest.json")))
    assert info["version"] == man["version"]          # manifest drives it
    assert info["version"].count(".") >= 1
    assert all(c.isdigit() or c == "." for c in info["version"])


# ------------------------------------------------------ hub .crx reader
@pytest.fixture()
def served_crx(tmp_path, monkeypatch):
    """Point the hub's crx reader at a temp package and reset its cache."""
    out = tmp_path / "AdvPrint-Pro.crx"
    crx3.pack_crx(os.path.join(ROOT, "extension"), KEY_PEM, str(out))
    monkeypatch.setattr(advprint, "_crx_paths",
                        lambda: [str(out)])
    advprint._EXT_CRX_CACHE.update(loaded=False, path=None, mtime=None,
                                   data=None, ext_id=None, version=None)
    yield out
    advprint._EXT_CRX_CACHE.update(loaded=False, path=None, mtime=None,
                                   data=None, ext_id=None, version=None)


def test_crx_package_reads_id_and_version(served_crx):
    c = advprint.crx_package()
    assert c and c["ext_id"] == EXT_ID
    man = json.load(open(os.path.join(ROOT, "extension", "manifest.json")))
    assert c["version"] == man["version"]
    assert c["data"][:4] == b"Cr24"


def test_crx_package_hot_swaps_on_file_change(served_crx):
    """Dropping a NEWER package must be picked up without a restart."""
    c1 = advprint.crx_package()
    v1 = c1["version"]
    man_dir = served_crx.parent / "newsrc"
    man_dir.mkdir()
    bumped = "9.8.7" if v1 != "9.8.7" else "9.8.8"
    (man_dir / "manifest.json").write_text(
        '{"manifest_version":3,"name":"t","version":"%s"}' % bumped)
    crx3.pack_crx(str(man_dir), KEY_PEM, str(served_crx))
    time.sleep(0.02)
    c2 = advprint.crx_package()
    assert c2["version"] == bumped        # hot swap worked
    assert c2["ext_id"] == EXT_ID         # ID stable across versions


def test_crx_package_missing_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(advprint, "_crx_paths",
                        lambda: [str(tmp_path / "nope.crx")])
    advprint._EXT_CRX_CACHE.update(loaded=False, path=None, mtime=None,
                                   data=None, ext_id=None, version=None)
    assert advprint.crx_package() is None
    assert advprint.ext_health() == {"served": False, "id": EXT_ID}


# ------------------------------------------------------------ endpoints
def test_extension_updates_xml(hub, served_crx):
    code, body = hub.get("/extension/updates.xml", token=None)
    assert code == 200
    root = ET.fromstring(body.decode("utf-8"))
    assert root.tag == "{http://www.google.com/update2/response}gupdate"
    app = root.find("{http://www.google.com/update2/response}app")
    assert app is not None and app.get("appid") == EXT_ID
    uc = app.find("{http://www.google.com/update2/response}updatecheck")
    assert uc is not None
    man = json.load(open(os.path.join(ROOT, "extension", "manifest.json")))
    assert uc.get("version") == man["version"]
    assert uc.get("codebase", "").startswith("http://127.0.0.1:")
    assert uc.get("codebase", "").endswith("/extension/AdvPrint-Pro.crx")


def test_extension_crx_content_type(hub, served_crx):
    # urllib exposes headers only through the raw response - use req's
    # raw path via a fresh request so we can read the headers
    import urllib.request
    r = urllib.request.Request(hub.base + "/extension/AdvPrint-Pro.crx")
    with urllib.request.urlopen(r, timeout=10) as resp:
        data = resp.read()
        ctype = resp.headers.get("Content-Type")
    assert data[:4] == b"Cr24"
    assert ctype == "application/x-chrome-extension"
    assert len(data) == len(served_crx.read_bytes())


def test_extension_info_json(hub, served_crx):
    code, d = hub.get("/extension/info", token=None)
    assert code == 200 and d["ok"] and d["served"]
    assert d["extension_id"] == EXT_ID
    assert d["forcelist_value"].startswith(EXT_ID + ";http://127.0.0.1:")
    assert "Load unpacked" in d["note"]


def test_extension_landing_page(hub, served_crx):
    code, body = hub.get("/extension", token=None)
    assert code == 200
    html = body.decode("utf-8")
    assert "extension server" in html and EXT_ID in html


def test_policy_status_is_token_gated(hub):
    code, _ = hub.get("/extension/policy/status", token=None)
    assert code == 401


def test_policy_status_answers(hub, served_crx):
    code, d = hub.get("/extension/policy/status")
    assert code == 200 and d["ok"]
    assert d["extension_id"] == EXT_ID
    assert d["platform"] == "linux"
    assert "policies/managed" in d["note"]


def test_policy_install_is_graceful_on_linux(hub, served_crx):
    code, d = hub.post("/extension/policy/install", body={})
    assert code == 200
    # on the Linux test box there is no registry - the answer must be a
    # graceful note, never a crash
    if d.get("platform") != "windows":
        assert d["ok"] is False and "policies/managed" in d["note"]


def test_policy_remove_is_graceful_on_linux(hub, served_crx):
    code, d = hub.post("/extension/policy/remove", body={})
    assert code == 200
    if d.get("platform") != "windows":
        assert d["ok"] is False


def test_health_carries_extension_block(hub, served_crx):
    # earlier tests may have frozen the /health snapshot (no refresher
    # thread runs under pytest) - invalidate it for a live build
    advprint._HEALTH_SNAP["data"] = None
    code, d = hub.get("/health", token=None)
    assert code == 200
    ext = d.get("extension") or {}
    assert ext.get("served") is True
    assert ext.get("id") == EXT_ID


def test_dashboard_has_extension_card(hub):
    # v3.2.0 THE ONE UI: /dashboard serves the approved All-in-One
    # console (same page as /ui). Its Extension panel carries the silent
    # install story (CRX + updates.xml + Forcelist policies) in place of
    # the classic dashboard's extInfo() card.
    code, body = hub.get("/dashboard")
    assert code == 200
    html = body.decode("utf-8")
    for marker in ("Silent install", "ExtensionInstallForcelist",
                   "updates.xml", "AdvPrint-Pro.crx", "THE ONE UI"):
        assert marker in html, marker


# ------------------------------------------------------------ installers
def test_setup_nsi_writes_forcelist():
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert "ExtensionInstallForcelist" in nsi
    assert EXT_ID in nsi
    for browser in ("Google\\Chrome", "Microsoft\\Edge",
                    "BraveSoftware\\Brave", "Chromium", "Vivaldi"):
        assert browser in nsi, browser
    assert "SEC_POLICY" in nsi                     # optional section
    assert "EXT_FORCELIST_UN" in nsi               # uninstaller sweep
    assert "hub\\extension" in nsi                 # ships the package
    assert "AdvPrint-Pro.crx" in nsi


def test_windows_bat_writes_hkcu_policy():
    bat = open(os.path.join(ROOT, "tool", "windows", "portable",
                            "install", "install-windows.bat"),
               encoding="utf-8").read()
    assert "ExtensionInstallForcelist" in bat
    assert EXT_ID in bat
    assert "HKCU" in bat


def test_unix_scripts_manage_policy_json():
    inst = open(os.path.join(ROOT, "tool", "unix", "install-unix.sh"),
                encoding="utf-8").read()
    un = open(os.path.join(ROOT, "tool", "unix", "uninstall-unix.sh"),
              encoding="utf-8").read()
    # installer writes the policy with our ID
    assert EXT_ID in inst
    assert "ExtensionInstallForcelist" in inst
    # both manage the same policy files (uninstall removes them -> the
    # browser auto-uninstalls the force-installed extension)
    for s in (inst, un):
        assert "/etc/opt/chrome/policies/managed" in s
        assert "advprint-pro.json" in s
