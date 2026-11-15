"""v3.5.2 - DASHBOARD DATA YOU CAN TRUST (success rate + save-password
fix + history tools) on the working v3.5.1 live-data base.

The user reported: "3.5.1 fine - need update dashboard success rate
also, now fake", "search anything and the browser offers to save a
password (search text as user name, token as password)", "in history
need date and time both", "any option button to view file in history",
"extra filter date wise also add". These tests lock all five:

A. REAL SUCCESS RATE - db_stats counts printed + saved as success,
   canceled excluded, /stats publishes every count, the KPI tile shows
   "7d N ok / M fail" + a full breakdown tooltip;
B. SAVE-PASSWORD FIX - zero type=password fields in the console, the
   token boxes are CSS-masked text inputs, the real token auto-fills,
   every input gets autocomplete=off;
C. DATE + TIME - history rows, dashboard recent, audit/visitor rows,
   LAN visitor hits, DropZone activity and /debug problems all show
   "YYYY-MM-DD HH:MM:SS";
D. VIEW FILE - history rows with a stored file get a per-row View
   button -> /jobs/<id>/file?view=1 (Content-Disposition: inline);
E. DATE-WISE FILTER - From/To date inputs query
   /jobs?date_from=&date_to= over the WHOLE database (db_list grew
   date_from/date_to, strict YYYY-MM-DD validation, bad values
   ignored);
F. the embedded CONSOLE_HTML in advprint.py is the SAME fresh console;
G. the three console.html + three advprint.py copies stay
   byte-identical (stage copy optional - it is a build artifact);
H. the usual version coherence 3.5.2 across hub / extension /
   installer;
I. v3.5.1 live dashboard + v3.5.0 theme engine untouched.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONSOLE_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "console.html"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "console.html"),
    os.path.join(ROOT, "installer", "stage", "hub", "console.html"),
]
ADV_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "advprint.py"),
    os.path.join(ROOT, "installer", "stage", "hub", "advprint.py"),
]
V = "3.5.2"


def console():
    return open(CONSOLE_PATHS[0], encoding="utf-8").read()


def adv():
    return open(ADV_PATHS[0], encoding="utf-8").read()


# ---------------- A. real success rate ----------------

def test_db_stats_saved_counts_as_success():
    src = adv()
    assert "SELECT COUNT(*) n FROM jobs WHERE status='saved' AND created_at >= ?" in src
    assert "SELECT COUNT(*) n FROM jobs WHERE status='canceled' AND created_at >= ?" in src
    assert "ok7 = printed7 + saved7" in src          # saved IS a delivery
    assert 'total7 = ok7 + bad7              # canceled stays out' in src
    # the old single-status success count is gone
    assert '''        ok7 = int(row["n"])
        row = conn.execute(
            "SELECT COUNT(*) n FROM jobs WHERE status IN ('failed','dead')''' not in src


def test_db_stats_publishes_every_count():
    src = adv()
    for key in ('"printed_7d": printed7', '"saved_7d": saved7',
                '"failed_7d": bad7', '"canceled_7d": canc7',
                '"total_7d": total7', '"success_rate": round(100.0 * ok7 / total7, 1)'):
        assert key in src, key


def test_kpi_tile_shows_counts_behind_percentage():
    s = console()
    # the tile label is written live from /stats counts...
    assert 'stats[1].querySelector(".d").textContent = "7d " + ok7 + " ok / " + bad7 + " fail";' in s
    # ...and the tooltip explains the full math (printed + saved = ok)
    assert 'stats[1].title = "last 7 days: " + pr7 + " printed + " + sv7 + " saved = " + ok7 +' in s
    assert 'var ok7 = (st.printed_7d || 0) + (st.saved_7d || 0),' in s
    assert '" canceled not counted)" : "");' in s
    # the static demo label is gone from the KPI markup
    assert '<div class="stat g"><div class="d">7 days</div>' not in s
    assert '<div class="stat g"><div class="d">7d 17 ok / 1 fail</div>' in s


# ---------------- B. save-password fix ----------------

def test_no_password_fields_anywhere():
    for p in CONSOLE_PATHS:
        if not os.path.exists(p):
            continue
        s = open(p, encoding="utf-8").read()
        assert 'type="password"' not in s, p
    # the old /dashboard page never grows one either
    a = adv()
    dash = a[a.index('DASHBOARD_HTML = r"""'):].split('"""')[0]
    assert 'type="password"' not in dash


def test_token_boxes_are_css_masked_text_inputs():
    s = console()
    assert ".tok-mask{-webkit-text-security:disc}" in s
    assert 'id="selfTokenInp"' in s
    assert 'class="inp mono tok-mask" type="text" id="selfTokenInp" autocomplete="off"' in s
    assert 'id="lanPcToken" type="text" autocomplete="off"' in s
    # the CONNECTIONS token box (the save-password bait) no longer ships
    # a static demo token - JS fills the REAL one
    assert '<input class="inp mono tok-mask" type="text" id="selfTokenInp" autocomplete="off" spellcheck="false" placeholder="hub token (filled automatically)"' in s
    assert 'var inp = $("selfTokenInp");' in s          # Detect token
    assert 'if (sti && !sti.value) sti.value = TOKEN;' in s  # boot autofill
    # the remaining pre-poll sample token values are OVERWRITTEN positionally
    # on every render: extension panel shows a MASKED token, settings fills
    # the real one (assert the overwrite code exists)
    assert 'tkv[0].textContent = TOKEN ? TOKEN.slice(0, 6) + "\\u2026" + TOKEN.slice(-6) : "(none)";' in s
    assert 'if (document.activeElement !== ins[1] && !dirtyKeys.token) ins[1].value = TOKEN || "";' in s
    assert 'input[type=password]' not in s


def test_autocomplete_off_everywhere():
    s = console()
    # history search + the modal token box + both date inputs
    assert '<input class="inp" type="text" autocomplete="off" placeholder="Search title / printer / #id"' in s
    assert 'id="tokInp" autocomplete="off"' in s
    assert 'id="histFrom" autocomplete="off"' in s
    assert 'id="histTo" autocomplete="off"' in s
    # the boot sweep covers every text / search / date box on the page
    assert "qsa('input[type=\"text\"],input[type=\"search\"],input[type=\"date\"]').forEach(function(i){" in s
    # old /dashboard search box
    a = adv()
    assert '<input type="search" id="hSearch" autocomplete="off"' in a


def test_self_token_autofills_real_token():
    s = console()
    assert 'var sti = $("selfTokenInp");' in s
    assert 'if (sti && !sti.value) sti.value = TOKEN;' in s


# ---------------- C. date + time everywhere ----------------

def test_full_datetime_in_every_row_render():
    s = console()
    new = '.replace("T", " ").slice(0, 19)'
    old = '.replace("T", " ").slice(11, 19)'
    # history rows
    assert 'td[2].textContent = (j.created_at || "")' in s
    # dashboard recent
    assert 'td[6].textContent = (j.created_at || "")' in s
    # audit / visitor rows
    assert 'td[0].textContent = (a.created_at || "")' in s
    assert s.count(new) >= 3 and old not in s
    # LAN visitor first/last hit + DropZone activity + /debug problems
    assert 'esc(String(h.first).slice(0, 19))' in s
    assert 'esc(String(h.last).slice(0, 19))' in s
    assert 'td[3].textContent = (a.created_at || "").slice(0, 19);' in s
    assert 'td[0].textContent = (p.created_at || "").slice(0, 19)' in s
    # old /dashboard visitor hits too
    a = adv()
    assert 'esc(String(h.last).slice(0,19))' in a


# ---------------- D. view file ----------------

def test_view_file_button_and_url():
    s = console()
    assert 'function viewFileUrl(j){' in s
    assert 'BASE + "/jobs/" + j.id + "/file?view=1&token=" + encodeURIComponent(TOKEN)' in s
    assert '&#128065; View</a> ' in s
    assert 'var vw = (j.file_path && j.kind !== "raw")' in s
    assert "target=\"_blank\" rel=\"noopener\"" in s


def test_send_file_inline_disposition():
    a = adv()
    assert "def _send_file(self, path, download_name, ctype=\"application/pdf\",\n                   inline=False):" in a
    assert '_disp = "inline" if inline else "attachment"' in a
    assert "'%s; filename=\"%s\"' % (_disp, safe)" in a
    # the /jobs/<id>/file route parses ?view=1 and passes it through
    assert '_view = ((q.get("view") or [""])[0] == "1")' in a
    assert 'inline=_view)' in a


# ---------------- E. date-wise filter ----------------

def test_history_date_inputs_and_js():
    s = console()
    assert 'id="histFrom"' in s and 'id="histTo"' in s and 'id="histDateClear"' in s
    assert "function histDateFetch(){" in s
    assert 'var qq = "/jobs?limit=200";' in s
    assert '"&date_from=" + encodeURIComponent(histDateFrom)' in s
    assert '"&date_to=" + encodeURIComponent(histDateTo)' in s
    assert "function histDateClear(){" in s
    # while a date is set the table renders the server answer
    assert "var histSrc = (histDateFrom || histDateTo) ? (histDateJobs || []) : jobs;" in s
    assert "var hlist = histSrc.filter(function(j){" in s
    # the caption spells the active range
    assert '"date filter " + (histDateFrom || "beginning") + " \\u2192 " + (histDateTo || "today") +' in s
    # the change/clear bindings exist
    assert 'hf.addEventListener("change", histDateFetch)' in s
    assert 'ht2.addEventListener("change", histDateFetch)' in s
    assert 'hc.addEventListener("click", histDateClear)' in s


def test_jobs_route_date_params():
    a = adv()
    assert 'date_from = _day((q.get("date_from") or [""])[0])' in a
    assert 'date_to = _day((q.get("date_to") or [""])[0])' in a
    assert 'return v if re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}", v) else None' in a
    assert 'db_list(limit, status=status,\n                                                    date_from=date_from,\n                                                    date_to=date_to)' in a


def test_db_list_accepts_date_range():
    a = adv()
    assert "def db_list(limit=HISTORY_DEFAULT, status=None, date_from=None, date_to=None):" in a
    assert 'where.append("substr(created_at,1,10)>=?")' in a
    assert 'where.append("substr(created_at,1,10)<=?")' in a
    assert 'sql += " WHERE " + " AND ".join(where)' in a


# ---------------- F. embedded console is fresh ----------------

def test_embedded_console_matches_standalone():
    a = adv()
    m = re.search(r'CONSOLE_HTML = r"""(.*?)"""', a, re.S)
    emb = m.group(1)
    std = console()
    assert emb == std + "\n"
    # the embedded copy carries THIS release's fixes, not a stale one
    assert "v3.5.2" in emb
    assert ".tok-mask{-webkit-text-security:disc}" in emb
    assert "histDateFetch" in emb


# ---------------- G. copies byte-identical ----------------

def test_console_copies_byte_identical():
    blobs = [open(p, "rb").read() for p in CONSOLE_PATHS if os.path.exists(p)]
    assert len(blobs) >= 2
    assert len(set(blobs)) == 1


def test_advprint_copies_byte_identical():
    blobs = [open(p, "rb").read() for p in ADV_PATHS if os.path.exists(p)]
    assert len(blobs) >= 2
    assert len(set(blobs)) == 1


# ---------------- H. version coherence 3.5.2 ----------------

def test_version_everywhere():
    a = adv()
    assert 'VERSION = "' + V + '"' in a
    assert 'VERSION_NAME = ("v' + V + ' (DASHBOARD DATA YOU CAN TRUST' in a
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert V in vt
    man = json.load(open(os.path.join(ROOT, "extension", "manifest.json"),
                         encoding="utf-8"))
    assert man["version"] == V
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    assert 'id="ver">v' + V + "</span>" in popup
    i18n = open(os.path.join(ROOT, "extension", "i18n.js"), encoding="utf-8").read()
    assert i18n.count("Version " + V) == 1
    assert i18n.count("\u09b8\u0982\u09b8\u09cd\u0995\u09b0\u09a3 " + V) == 1
    api = open(os.path.join(ROOT, "extension", "content", "api.js"),
               encoding="utf-8").read()
    assert 'var _apVerFallback = "' + V + '";' in api
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"), encoding="utf-8").read()
    assert 'OutFile "../dist/AdvPrint-Pro-Setup-' + V + '.exe"' in nsi
    assert 'VIProductVersion "' + V + '.0"' in nsi
    assert '"DisplayVersion" "' + V + '"' in nsi
    deb = open(os.path.join(ROOT, "installer", "deb", "DEBIAN", "control"),
               encoding="utf-8").read()
    assert "Version: " + V in deb
    # the boot-json version fallbacks inside the embedded console (3 of them)
    assert a.count('(BOOT.version || "' + V + '")') == 3
    # the embedded title + KPI tile
    assert "ALL-IN-ONE Console v" + V in a
    assert '<div class="stat"><div class="d">hub</div><div class="v">v' + V + '</div>' in console()


# ---------------- I. v3.5.1 / v3.5.0 features untouched ----------------

def test_dashboard_live_data_cards_still_wired():
    s = console()
    for i in ("dashSub", "dashUptime", "dashService", "dashListen", "dashLan",
              "dashIpp", "dashRaw", "dashDrop", "dashConn", "dashToken",
              "dpName", "dpStatus", "dpHold", "dashRecentCap"):
        assert 'id="%s"' % i in s, i
    assert "function renderDashboard(h, st, q, pr){" in s


def test_theme_engine_still_present():
    s = console()
    assert "AdvPrint theme engine" in s
    assert "window.AdvTheme" in s
    assert 'id="themeGrid"' in s
    assert s.count('data-theme-set="') >= 7


def test_console_embed_safe():
    s = console()
    assert '"""' not in s.replace('r"""', "")  # no triple quotes in the UI source


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "--no-header", "-p", "no:cacheprovider"]))
