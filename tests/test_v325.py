"""v3.2.5 - SIX USER-REPORTED BUGS, ALL FIXED AND LOCKED.

1) Set Default is REAL now (POST /printers/set-default -> OS-level
   change, Windows auto-manage disabled via LegacyDefaultPrinterMode=1,
   verified result; hub destination key kept in sync).
2) Job History selection survives the 3 s auto-refresh; per-row Cancel;
   Reprint selected / Cancel selected / Clear selected + live counter.
3) Live Queue gets the same treatment (checkbox column, select-all,
   Cancel selected, Clear selected, selection persists).
4) The per-printer IPP URL is proven workable end to end (GET landing
   page + slug resolution through a REAL hub).
5) Policy install reports its REAL failure (api() shows d.message, the
   hub adds a PowerShell fallback and an honest error field).
6) Start with Windows is honest: the UI reads the REAL /health state and
   the switch actually toggles it via POST /autostart.
"""
import json
import os
import re

import advprint
from conftest import ROOT

UI = os.path.join(ROOT, "tool", "unix", "hub", "console.html")
HUBPY = advprint.__file__
EXT = os.path.join(ROOT, "extension")


def _ui():
    return open(UI, encoding="utf-8").read()


def _hub():
    return open(HUBPY, encoding="utf-8").read()


# ------------------------------------------------------------
# BUG 1 - Set Default actually changes the OS default
# ------------------------------------------------------------
def test_v325_setdef_new_endpoint_exists_in_hub():
    s = _hub()
    assert 'route == "/printers/set-default"' in s
    assert "def os_set_default_printer(" in s
    # Windows: the auto-manage opt-out MUST happen in the same call
    assert "LegacyDefaultPrinterMode" in s
    assert "WScript.Network" in s and "SetDefaultPrinter" in s
    # Unix: per-user CUPS default
    assert '"lpoptions", "-d"' in s
    # the hub destination key stays in sync after a verified change
    assert 'CFG["printer"] = got' in s


def test_v325_setdef_result_is_verified_not_wished():
    s = _hub()
    # the endpoint returns the REAL new default plus an honest error
    assert '"ok": True, "default": got' in s
    assert '"ok": False, "default": got' in s
    assert '"error": detail' in s


def test_v325_setdef_console_calls_the_new_endpoint():
    ui = _ui()
    assert 'api("/printers/set-default"' in ui
    # the old save-only call is gone from the ONE UI and the old dashboard
    assert 'body: { printer: sd } });\n        toast(sd + " is now the default printer"' not in ui
    hub_s = _hub()
    assert 'api("/printers/set-default"' in hub_s
    # the toast shows the VERIFIED result (r5.detail), not a fixed text
    assert "r5.detail" in ui and "r5.detail" in hub_s


def test_v325_os_set_default_printer_contract():
    # on the CI sandbox (Linux without CUPS credentials) the call must
    # FAIL HONESTLY: (False, default-or-name, detail) - never raise.
    ok, got, detail = advprint.os_set_default_printer("Definitely Not A Printer")
    assert ok is False
    assert isinstance(got, str) and got
    assert isinstance(detail, str) and detail


# ------------------------------------------------------------
# BUG 2 - History selection survives the poll + per-row actions
# ------------------------------------------------------------
def test_v325_history_selection_survives_the_poll():
    ui = _ui()
    assert "var histSel = {}" in ui
    # the render applies the remembered state - the old forced-uncheck
    # line (`td[0].firstElementChild.checked = false;`) must be gone
    assert "td[0].firstElementChild.checked = false;" not in ui
    assert "td[0].firstElementChild.checked = !!histSel[j.id];" in ui


def test_v325_history_has_cancel_selected_and_clear_selected():
    ui = _ui()
    assert 'id="histCancelSel"' in ui
    assert 'id="histSelInfo"' in ui
    assert "Cancel selected</button>" in ui.split('id="p-history"')[1].split("</section>")[0]
    assert "Clear selected</button>" in ui.split('id="p-history"')[1].split("</section>")[0]
    assert 'btnLike("#p-history", /Cancel selected/i' in ui
    assert 'btnLike("#p-history", /Clear selected/i' in ui


def test_v325_history_rows_have_individual_cancel():
    ui = _ui()
    # queued / held / printing rows show Cancel, finished rows Reprint
    assert 'var canStill = ["queued", "held", "printing"].indexOf(j.status) >= 0;' in ui
    assert 'data-cancel="\' + j.id + \'"' in ui.split("/* history table */")[1].split("/* ----")[0]


def test_v325_history_header_select_all():
    ui = _ui()
    assert 'input type="checkbox" data-hall' in ui
    assert 'hasAttribute("data-hall")' in ui


# ------------------------------------------------------------
# BUG 3 - Queue checkboxes like History
# ------------------------------------------------------------
def test_v325_queue_checkbox_column_exists():
    ui = _ui()
    q = ui.split('id="p-queue"')[1].split("</section>")[0]
    assert '<input type="checkbox" data-qall>' in q, "header select-all missing"
    assert q.count("<td><input type=\"checkbox\"></td>") >= 7, \
        "every demo row needs the checkbox cell"


def test_v325_queue_selection_persists_and_actions_exist():
    ui = _ui()
    assert "var histSel = {}, queueSel" in ui
    assert "qc.checked = !!queueSel[j.id];" in ui
    q = ui.split('id="p-queue"')[1].split("</section>")[0]
    assert 'id="queueCancelSel"' in q and 'id="queueSelInfo"' in q
    assert "Cancel selected</button>" in q
    assert "Clear selected</button>" in q
    assert 'btnLike("#p-queue", /Cancel selected/i' in ui
    assert 'btnLike("#p-queue", /Clear selected/i' in ui


def test_v325_selection_engine_is_bound_at_boot():
    ui = _ui()
    assert "function bindSelections()" in ui
    assert "bindSelections();" in ui.split("async function boot()")[1].split("}")[0]
    assert "function syncSelBar()" in ui
    assert "async function cancelSelected(" in ui
    assert "function clearSelection(" in ui
    # clear selected NEVER deletes jobs - it only unticks
    c = ui.split("function clearSelection(")[1].split("async function cancelSelected")[0]
    assert "/history/clear" not in c and "/jobs/" not in c


# ------------------------------------------------------------
# BUG 4 - the per-printer IPP URL is real (live, through the hub)
# ------------------------------------------------------------
def test_v325_perprinter_ipp_url_works_live(hub):
    printers = ["HP Laser 103 107 108", "Microsoft Print to PDF"]
    advprint._LP_CACHE["v"] = list(printers)
    advprint._LP_CACHE["t"] = __import__("time").time()
    code, d = hub.get("/printers")
    assert code == 200
    by_name = {p["name"]: p for p in d["printers"]}
    for nm in printers:
        p = by_name[nm]
        url = p.get("ipp_queue", "")
        assert url.startswith("ipp://"), url
        assert "/ipp/print/" in url, url
        slug = url.rsplit("/", 1)[-1]
        # GET the landing page exactly like a client would
        c2, body = hub.get("/ipp/print/" + slug, token=None)
        assert c2 == 200, (slug, c2)
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        assert nm in body and "Add it as a printer" in body
        assert slug in body          # the page shows the SAME URL
    # v3.3.2 BUG 3: unknown queue -> the GENERIC how-to landing page
    # (HTML 200), not a JSON 404 - a browser or phone that typed a
    # slightly wrong name still sees the printer page
    c3, err = hub.get("/ipp/print/does-not-exist", token=None)
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    if not isinstance(err, str):
        err = json.dumps(err)
    assert c3 == 200 and "IPP network printer" in err


# ------------------------------------------------------------
# BUG 5 - policy install reports its real failure
# ------------------------------------------------------------
def test_v325_api_surfaces_the_server_message():
    ui = _ui()
    # error > message > status (the old line hid {ok:false,message}
    # behind a blind "HTTP 200")
    m = re.search(r"if \(!r\.ok \|\| d\.ok === false\)\s*\n\s*throw new Error\((.*?)\);", ui)
    assert m, "api() error throw not found"
    expr = m.group(1)
    assert "d.error" in expr and "d.message" in expr and "HTTP" in expr


def test_v325_reg_add_has_powershell_fallback():
    s = _hub()
    assert "New-ItemProperty" in s
    assert "PowerShell fallback" in s
    fn = s.split("def _ext_reg_add(")[1].split("def _ext_reg_delete")[0]
    assert '"reg", "add"' in fn and '"powershell"' in fn


def test_v325_policy_responses_carry_an_error_field():
    s = _hub()
    fn = s.split('elif action == "policy-install":')[1].split('elif action == "fw-allow":')[0]
    assert '"error":' in fn
    # the HKLM message explains the admin requirement
    assert "needs an admin console" in fn
    g = s.split("def ext_policy_install():")[1].split("def ext_policy_remove():")[0]
    assert '"error":' in g


# ------------------------------------------------------------
# BUG 6 - Start with Windows is honest
# ------------------------------------------------------------
def test_v325_autostart_reads_the_real_state():
    ui = _ui()
    assert "autoStartState = !!h.autostart;" in ui
    # the stale config-key READ is gone (only the explanatory comment
    # may mention it)
    assert "autoStartState = !!(cfgCache.autostart" not in ui


def test_v325_autostart_switch_really_toggles():
    ui = _ui()
    assert 'api("/autostart", { method: "POST", body: { enabled: want } })' in ui
    assert "Start with Windows is managed by the service/tray" not in ui
    hub_s = _hub()
    assert 'if route == "/autostart":' in hub_s


def test_v325_autostart_endpoint_works_live(hub, tmp_path, monkeypatch):
    # isolate the autostart file in a tmp HOME so the test never touches
    # the real Startup folder
    fake_home = tmp_path / "home"
    (fake_home / ".config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_home / ".config"))
    code, r1 = hub.post("/autostart", body={"enabled": True})
    assert code == 200 and r1["ok"] and r1["enabled"] is True
    p = fake_home / ".config" / "autostart" / "advprint-pro.desktop"
    assert p.is_file()
    code, r2 = hub.post("/autostart", body={"enabled": False})
    assert code == 200 and r2["ok"] and r2["enabled"] is False
    assert not p.exists()
    # /health mirrors the real file state
    code, h = hub.get("/health")
    assert h["autostart"] is False


# ------------------------------------------------------------
# release hygiene - the SHA256SUMS EXE-line regression (v3.2.2 bug)
# ------------------------------------------------------------
def test_v325_sums_cover_the_setup_exe():
    # v3.2.2 shipped a 3-line SHA256SUMS (the Setup EXE line was lost);
    # the v3.2.4 "one pass" fix still tested the wrong relative path.
    # v3.2.5: the check points at dist/ and the shipped sums have 4 lines.
    sh = open(os.path.join(ROOT, "scripts", "build-all.sh"),
              encoding="utf-8").read()
    assert '[ -f "$DIST/AdvPrint-Pro-Setup-$V.exe" ]' in sh, \
        "build-all.sh must look for the Setup EXE inside dist/"
    sums_path = os.path.join(ROOT, "dist", "SHA256SUMS-3.2.9.txt")
    if os.path.isfile(sums_path):   # after a build - lock the result
        lines = open(sums_path, encoding="utf-8").read().strip().splitlines()
        assert len(lines) == 4, \
            "SHA256SUMS must cover CRX + extension zip + DEB + Setup EXE"
        assert any("AdvPrint-Pro-Setup-3.3.5.exe" in l for l in lines)


# ------------------------------------------------------------
# version coherence
# ------------------------------------------------------------
def test_v325_versions_agree():
    assert advprint.VERSION == "3.3.5"
    assert advprint.VERSION_NAME.startswith("v3.3.5")
    man = json.load(open(os.path.join(EXT, "manifest.json"),
                         encoding="utf-8"))
    assert man["version"] == "3.3.5"
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert "3.3.5" in vt
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'VIProductVersion "3.3.5.0"' in nsi
    assert "AdvPrint-Pro-Setup-3.3.5.exe" in nsi
