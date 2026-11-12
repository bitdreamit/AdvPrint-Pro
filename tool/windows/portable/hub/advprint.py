#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
#  AdvPrint Pro v2.8.0  -  Print from any web page to any printer
#  by Bit Dream IT  -  MIT licensed, 100% local & open source
#  AdvPrint Pro - Version 2.7.0 - by Bit Dream IT - MIT license
#  100% local - no cloud, no tracking.
# ------------------------------------------------------------
#  Chrome extension <-> this hub (localhost) -> ANY printer
#  NO print dialog. NO subscription. NO cloud. NO data collection.
#
#  * ZERO pip dependencies - pure Python 3.8+ standard library
#  * Cross-platform: Windows (SumatraPDF) / Linux & macOS (CUPS lp)
#  * Any printer: thermal, receipt, label, A4 - hub sees it, you print
#  * Print queue: priority, exponential retry, scheduled prints,
#    dead-letter list, duplicate blocking, printer groups + fallback
#  * Printer status (ready / offline / paper-out / error) - jobs wait
#    while the printer is offline and print automatically when back
#  * Raw printing: ESC/POS (cut, cash drawer, barcode, QR) + ZPL
#  * Print profiles (paper, tray, duplex, copies) + page ranges
#  * Security: random token on new install, header-only tokens,
#    origin allowlist, SSRF-guarded pdf_url, IP lockout, token rotate
#  * Audit log (who / site / document hash / printer / time), REPRINT
#    watermark, log rotation, diagnostics export, CSV export, dashboard
#  * Job history: SQLite, reprint anytime, survives restarts
#  * Token auth, CORS + Private-Network headers, localhost by default
#
#  Quick start:   python advprint.py serve
#  Health check:  http://127.0.0.1:9235/health
#  Dashboard:     http://127.0.0.1:9235/dashboard?token=...
#  Full check:    python advprint.py doctor
#  Help:          python advprint.py help
# ============================================================

import base64
import csv
# v2.6.5 FIX: glob is used by the SumatraPDF folder scans (portable zips
# that keep the exe in a subfolder) and by the ALL-USERS profile scan
# (C:\Users\*\AppData\Local\SumatraPDF\SumatraPDF.exe) that makes PDF
# printing work when the hub runs as a SERVICE under a different account.
# The import was missing - the scan raised NameError, find_sumatra()
# swallowed it as "not found" and service-mode PDF printing silently
# lost its last-resort detection. Imported once here, at the top.
import glob
import hashlib
import hmac
import html
from html import escape as _html_escape
import io
import ipaddress
import itertools
import json
import os
import pathlib
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, parse_qsl, quote, urlsplit

# v2.6.4 CRITICAL FIX: winreg is the Windows-only registry module (stdlib).
# v2.6.3 used `winreg` in _winreg_lookup_sumatra() but NEVER imported it -
# on Windows that raised NameError inside find_sumatra(), which is called
# by the /health snapshot builder (so /health answered with the 6-key
# "starting": true fallback forever), by /debug + /diagnostics (those
# requests died with ERR_EMPTY_RESPONSE) and by the PDF print path itself
# (every print job failed). Linux/macOS never execute that code, which is
# why the sandbox smoke tests looked green while the user's Windows PC
# was broken. The import is now guarded: present on Windows, None
# elsewhere (the Sumatra registry lookup is simply skipped).
try:
    import winreg
except ImportError:                       # non-Windows platform
    winreg = None

# v2.6.1 FIX: the bundled Windows runtime (AdvPrintPro.exe = embedded
# pythonw with a ._pth file) runs in ISOLATED mode - it does NOT add
# this script's folder to sys.path. Sibling modules (tray_windows, ...)
# could then not import -> the hub ran but the TRAY ICON WAS MISSING in
# the portable layout. Insert the hub folder ourselves (idempotent,
# harmless in every other layout).
_HUB_DIR = os.path.dirname(os.path.abspath(__file__))
if _HUB_DIR not in sys.path:
    sys.path.insert(0, _HUB_DIR)


VERSION = "3.3.3"
VERSION_NAME = ("v3.3.3 (SHARE SEND POPUP-FIX + PEERS-ONLINE RELEASE. "
    "BUG 1 - the false \"Connect the LAN PC first\" popup when flipping "
    "Share Send Mode ON: the console blocked the flip while lanPeerState "
    "was still null - which is EVERY page load until the first /peer/"
    "status answer lands behind seven sequential poll calls (printers "
    "alone can take seconds on Windows WMI) - even though the pairing "
    "was persisted and the server would have accepted it. The client no "
    "longer blocks: the POST goes out, the server (the persisted truth) "
    "decides, and an in-flight flip is guarded against the 3 s poll. BUG "
    "2 - the Other PCs (peers) table showed EVERY peer OFFLINE forever "
    "and its Shift queue buttons stayed disabled: /peers answers with "
    "`alive` while the table read `p.up` (undefined). The hub now sends "
    "`up` AND `alive`, plus the entry's name/label (rows said \"PC\" for "
    "every peer), and the table refreshes on every poll instead of only "
    "at page load. BUG 3 - the SAME PC listed twice in the peers table: "
    "peer_hubs entries are now deduped by normalized URL on every write "
    "path (pair, invite-connect, /config), /peers dedupes defensively, "
    "and an invite link for an ALREADY-PAIRED PC updates the lan-pc "
    "entry in place instead of silently unpairing Share Send Mode. BUG 4 "
    "- Shift queue was doubly broken: the console sent {peer: url} while "
    "the endpoint read `target`, and \"Shift all waiting\" read the SELF "
    "PC token field as the peer URL (the LAN PC card had shifted the "
    "qsa() indexes); the input kept its static demo value http://10.26."
    "94.77:9235 forever. The input now has id=shiftTarget, is prefilled "
    "with the LAN PC's URL, both sides agree on `target` (peer accepted "
    "as alias) and the demo value is gone. On top: Share Send switch "
    "mirrors cfgCache.share_send at boot (no OFF-rendered-while-ON).")
FULL_BRAND = ("AdvPrint Pro (Advanced Printer) by "
              "Bit Dream IT - Innovative Healthcare Solutions")
BRANDING = ("AdvPrint Pro (Advanced Printer) - Version %s - by "
            "Bit Dream IT - Innovative Healthcare Solutions - "
            "MIT license - 100%% local - no cloud, no tracking" % VERSION)
APP_NAME = "AdvPrint Pro"
VENDOR = "Bit Dream IT"
ORG_NAME = "Innovative Healthcare Solutions"
GITHUB_REPO = "bitdreamit/AdvPrint-Pro"
GITHUB_RELEASES = "https://github.com/%s/releases" % GITHUB_REPO
SERVICE_NAME = "AdvPrint"          # optional Windows service (services.msc)
SERVICE_DISPLAYNAME = "AdvPrint Pro Service"
FIREWALL_RULE_NAME = "AdvPrint Pro"   # netsh rule (added by the installer
                                      # AND by the one-click allow button)
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
HIDE = 0x08000000 if IS_WIN else 0          # no console window flash on Windows

class HubServer(ThreadingHTTPServer):
    # v2.6.3 SINGLE-INSTANCE GUARANTEE. The stock ThreadingHTTPServer sets
    # allow_reuse_address = 1; on Windows SO_REUSEADDR lets a SECOND hub
    # process silently bind the SAME port (two hubs fighting over one
    # socket - the "running but not answering" chaos in hub.log with two
    # BOOT lines 47 s apart). POSIX SO_REUSEADDR is safe there (it can
    # never double-bind a live listener, only beats TIME_WAIT), so it is
    # kept for quick restarts on Linux/macOS; on Windows we bind
    # exclusively, so a second instance always gets a clean EADDRINUSE
    # and exits with a clear message.
    allow_reuse_address = not IS_WIN
    # v3.2.9 BUG 2 - MANY PCS ONE HUB: the socketserver default accept
    # backlog is 5. With several PCs/phones printing over IPP + LAN each
    # client keeps a few parallel connections (status poll + print job
    # + UI poll) and the overflow connect was REFUSED (SYN retry ~2 s)
    # - the "works alone, breaks when more than one PC prints" report.
    # A 128-deep backlog absorbs the bursts on every listener.
    request_queue_size = 128

    def server_bind(self):
        if IS_WIN:
            try:
                self.socket.setsockopt(
                    socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()
MAX_BODY = 40 * 1024 * 1024                 # 40 MB hard cap on request body
MAX_PDF = 25 * 1024 * 1024                  # 25 MB cap for downloaded pdf_url
HISTORY_DEFAULT = 100                       # Ultraprint-style: last 100 jobs
LEGACY_TOKEN = "PrintHub-2024"              # pre-2.0 default (old installs)
LEGACY_DATA_DIR = ".printhub"               # pre-2.6 data folder (migrated)


def _env(name, default=""):
    """Environment variable with legacy alias: ADVPRINT_* wins,
    PRINTHUB_* (pre-2.6 name) still works for old scripts."""
    v = os.environ.get("ADVPRINT_" + name)
    if v is None:
        v = os.environ.get("PRINTHUB_" + name, default)
    return v

# ------------------------------------------------------------
# Configuration:  defaults <- config.json <- environment variables
# ------------------------------------------------------------
# config.json lives in the data dir and PERSISTS settings between runs.
# New settings (allowed_origins, printer_groups, profiles, retries,
# audit, watermark, peers ...) go here and on the extension Options page.
# Defaults intentionally keep the pre-2.0 behaviour wherever possible:
#   allowed_origins []      = allow all origins (as before)
#   token_header_only False = query/body tokens still accepted (old installs)
#   reprint_reason_required False = reprint needs no reason (as before)
#   peer_forwarding False   = never forward jobs to peer hubs (as before)
CFG = {
    "host": _env("HOST", "127.0.0.1"),                        # localhost by default
    "port": int(_env("PORT", "9235")),
    "token": _env("TOKEN", LEGACY_TOKEN),
    "printer": _env("PRINTER", ""),                           # empty = OS default
    "data_dir": _env(
        "DATA",
        os.path.join(os.path.expanduser("~"), ".advprint")),
    # destination "file": save the rendered PDF here instead of printing
    "file_dir": _env("FILE_DIR", ""),
    "keep_files": True,   # keep printed files so /reprint works

    # ---- v2.0 settings (config.json + /config API + Options page) ----
    "token_header_only": False,       # False = accept token in query/body too
    "allowed_origins": [],            # [] = allow every origin (old behaviour)
    "pdf_url_allowed_hosts": [],      # hosts exempt from the private-IP block
    "max_auth_failures": 10,          # failed tokens before ...
    "lockout_minutes": 5,             # ... the IP is locked this many minutes
    "lockout_exempt_loopback": True,  # 127.0.0.1/::1 are NEVER locked
                                      # (every Chrome window/profile shares
                                      #  that ONE IP - v2.0.1: a stale token
                                      #  in one window must not lock out
                                      #  the dashboard, tray and extension)
    "printer_groups": {},             # {"Front Desk": ["A", "B"]} fallback order
    "profiles": {},                   # {"Invoice": {"paper": "a4", "duplex": True}}
    "max_retries": 2,                 # exponential retry (0 = off, 1.7.2 style)
    "retry_base_seconds": 30,         # backoff: 30s, 60s, 120s ...
    "dedupe_minutes": 5,              # block identical jobs inside this window
    "hold_offline": True,             # hold jobs while the printer is offline
    "audit_enabled": True,
    "reprint_watermark": False,       # stamp "REPRINT" on reprinted pages
    "reprint_reason_required": False,
    "peer_hubs": [],                  # [{"url": "http://ip:9235", "token": "..."}]
    "peer_forwarding": False,         # forward jobs to a live peer hub
    "share_send": False,              # v3.3.2 SHARE SEND MODE: send EVERY
                                      #  new print job to the paired LAN PC
                                      #  (the peer_hubs entry the Connections
                                      #  panel pairs with) instead of
                                      #  printing on this PC. OFF (default)
                                      #  prints on the Self PC.
    "show_remote_printers": False,    # v3.3.2: printers panel also lists the
                                      #  paired LAN PC's devices (badged
                                      #  "LAN PC" / "IPP", different IP)
    "share_lan": False,               # v2.1: listen on 0.0.0.0 so OTHER PCs
                                      #  on the LAN can print through this
                                      #  PC's printers (token always required)
    "ipp_printer": True,              # v2.9: expose this hub as an IPP
                                      #  network printer at /ipp/print so
                                      #  Windows 10/11 ("add a printer by
                                      #  URL") and phone print services can
                                      #  add it like a normal IP printer
    "ipp_mdns": True,                 # v3.0.8: mDNS/Bonjour announce so the
                                      #  printer appears BY ITSELF in the
                                      #  printer list of phones (AirPrint /
                                      #  Mopria), Windows 10/11 and macOS
                                      #  while LAN sharing is on
    "ipp_standard_port": 631,         # v3.2.2: ALSO answer IPP on the
                                      #  STANDARD printer port on the LAN IP
                                      #  (what Android's Default Print
                                      #  Service tries first on manual add,
                                      #  and what many printer dialogs
                                      #  assume). Windows needs no admin
                                      #  for ports < 1024; on macOS/Linux
                                      #  the hub logs a hint when the bind
                                      #  is refused. 0 = off.
    "raw_printer_port": 9100,         # v2.9: JetDirect RAW listener port for
                                      #  Windows "Standard TCP/IP port"
                                      #  printers (0 = off)
    "dest_mode": "",                  # v2.9: where jobs print. "" = auto
                                      #  (old behaviour: the selected
                                      #  printer when one is set, otherwise
                                      #  the OS default). ANY printer works:
                                      #  "default" | "selected" | "ip"
    "ip_printer_host": "",            # v2.9: upstream network printer IP /
                                      #  hostname (dest_mode "ip" forwards
                                      #  every job there)
    "ip_printer_port": 0,             # v2.9: 0 = protocol default
                                      #  (raw -> 9100, ipp -> 631)
    "ip_printer_proto": "raw",        # v2.9: "raw" (JetDirect) or
                                      #  "ipp" (IPP Print-Job)
    "escpos_codepage": "cp437",       # v2.1: raw ESC/POS text codepage
                                      #  (cp437/cp850/cp866/... - Bangla is
                                      #  NOT in any codepage: the hub auto-
                                      #  routes such text via headless Chrome)
    "thermal_text_engine": "auto",    # v2.1: auto|builtin|browser - "auto"
                                      #  renders non-Latin text (Bangla etc.)
                                      #  through headless Chrome so complex
                                      #  scripts shape correctly on rolls
    "log_max_mb": 5,                  # hub.log rotates after this size
    "log_backups": 3,                 # ... keeping this many old logs

    # ---- v2.3 settings ----
    "debug": False,                   # Debug mode: verbose [DEBUG] logs +
                                      #  GET /debug collects CLIENT error
                                      #  reports (extension JS / desktop
                                      #  tool) so "nothing prints" can be
                                      #  answered with WHEN / WHY / WHERE
    "instant_auto_queue": True,       # Instant print (queue OFF) + the
                                      #  printer is NOT active -> the job
                                      #  is auto-queued instead of failing
                                      #  and prints when the printer is back
    "sumatra_path": "",               # v2.5: manual override - full path to
                                      #  SumatraPDF.exe (dashboard Settings /
                                      #  config.json / ADVPRINT_SUMATRA).
                                      #  Empty = auto-find (dynamic per user).

    # ---- v2.8 settings ----
    "drop_enabled": True,             # v2.8 DROP ZONE: watch a folder and
                                      #  print every PDF that lands in it -
                                      #  "MS Word style" printing from ANY
                                      #  app WITHOUT the extension: print to
                                      #  "Microsoft Print to PDF", save into
                                      #  the DropZone, AdvPrint prints it
    "drop_dir": "",                   # folder to watch (empty =
                                      #  <data dir>/DropZone)
    "drop_delete": False,             # True = delete the PDF after pickup,
                                      #  False = move it into DropZone/done

    # ---- v3.2.0 THE ONE UI - central rule manager + extension mirror ----
    "rules_mirror": [],               # central auto-print rules edited in the
                                      #  ONE UI (Rules panel) and adopted by
                                      #  the browser extension automatically;
                                      #  the extension pushes its local rules
                                      #  back here on every save. Entries:
                                      #  {id,name,pattern,match,kind,printer,
                                      #   action,copies,paper,on,runs}
    "ext_api_sites": [],              # mirror of the extension's Website API
                                      #  whitelist (default ["*"] = ALL
                                      #  domains) - shown live in the ONE UI
    "ext_sync_at": "",                # ISO stamp of the last extension sync
    "ext_prefs": {},                  # v3.2.1 ONE UI Power/Browser switches +
                                      #  default print options, mirrored to
                                      #  every paired browser on its next sync
    "allowed_ips": ["*"],             # v3.2.3 ALLOWED IPS - who may reach
                                      #  this hub from the network.
                                      #  ["*"] = EVERY device on the LAN
                                      #  (factory default). Once real
                                      #  entries are added (exact IP like
                                      #  10.26.94.100, a CIDR like
                                      #  10.26.94.0/24, or a wildcard like
                                      #  10.26.*) ONLY those may connect:
                                      #  console, send portal, API, IPP
                                      #  9235 + 631 mirror, RAW 9100. The
                                      #  hub PC itself (127.0.0.1) is
                                      #  ALWAYS allowed. Edit in THE ONE
                                      #  UI > LAN Sharing > Allowed IPs.
    "history_days": 30,               # v3.2.1 Settings tab: keep jobs (days)
    "log_level": "info",              # v3.2.1 Settings tab: info|debug|warn|error
}

# env overrides that win over config.json (back-compat for 1.x users)
for _k in ("token", "printer", "file_dir"):
    pass  # already applied above; config.json is applied in init_config()

CONFIG_KEYS = ("token", "token_header_only", "allowed_origins",
               "pdf_url_allowed_hosts", "max_auth_failures",
               "lockout_minutes", "lockout_exempt_loopback",
               "printer_groups", "profiles",
               "max_retries", "retry_base_seconds", "dedupe_minutes",
               "hold_offline", "audit_enabled", "reprint_watermark",
               "reprint_reason_required", "peer_hubs", "peer_forwarding",
               "share_send", "show_remote_printers",
               "share_lan", "escpos_codepage", "thermal_text_engine",
               "log_max_mb", "log_backups", "debug", "instant_auto_queue",
               "printer", "file_dir", "sumatra_path",
               "dest_mode", "ip_printer_host", "ip_printer_port",
               "ip_printer_proto",
               "ipp_printer", "ipp_mdns", "ipp_standard_port",
               "keep_files",           # v3.2.0 gap fix: the ONE UI
                                       #  switch writes it back now
               "drop_enabled", "drop_dir", "drop_delete",
               "rules_mirror", "ext_api_sites", "ext_sync_at",
               "ext_prefs", "history_days", "log_level",
               "allowed_ips")
CONFIG_TYPES = {"token_header_only": bool, "allowed_origins": list,
                "pdf_url_allowed_hosts": list, "max_auth_failures": int,
                "lockout_minutes": int, "lockout_exempt_loopback": bool,
                "printer_groups": dict,
                "profiles": dict, "max_retries": int,
                "retry_base_seconds": int, "dedupe_minutes": int,
                "hold_offline": bool, "audit_enabled": bool,
                "share_lan": bool, "ipp_printer": bool,
                "ipp_mdns": bool, "ipp_standard_port": int,
                "raw_printer_port": int,
                "reprint_watermark": bool, "reprint_reason_required": bool,
                "peer_hubs": list, "peer_forwarding": bool,
                "share_send": bool, "show_remote_printers": bool,
                "log_max_mb": int, "log_backups": int,
                "debug": bool, "instant_auto_queue": bool,
                "sumatra_path": str,   # v2.5: manual SumatraPDF.exe override
                "dest_mode": str, "ip_printer_host": str,
                "ip_printer_port": int, "ip_printer_proto": str,
                "drop_enabled": bool, "drop_dir": str,
                "drop_delete": bool,   # v2.8 DropZone settings
                "rules_mirror": list, "ext_api_sites": list,
                "ext_sync_at": str,    # v3.2.0 ONE UI mirrors
                "ext_prefs": dict,     # v3.2.1 ONE UI -> browsers mirror
                "history_days": int,   # v3.2.1 Settings tab
                "log_level": str,      # v3.2.1 Settings tab
                "printer": str,        # v3.2.0: default printer via /config
                "keep_files": bool,
                # v3.2.3: the Hub panel posts these two with every switch
                # save - they were MISSING here, so every Hub-panel switch
                # save died with 400 'unknown config key' and none of the
                # Hub switches ever persisted (THE switch bug the user hit)
                "escpos_codepage": str,
                "thermal_text_engine": str,
                "allowed_ips": list}   # v3.2.3 ALLOWED IPS (LAN Sharing tab)

DEFAULT_TOKEN_WARNING = False   # True while the legacy default token is active
BOUND_LAN = False               # True once the listener actually bound 0.0.0.0


def cli_cmd(args):
    """v2.6.1: a copy/paste-ready command with the REAL advprint.py path,
    so 'python advprint.py ...' hints never fail with 'can't open file'
    just because the user is in another folder."""
    py = sys.executable or "python"
    try:
        script = os.path.join(_HUB_DIR, "advprint.py")
    except NameError:
        script = "advprint.py"
    return 'python "%s" %s' % (script, args)


def config_path():
    return os.path.join(CFG["data_dir"], "config.json")


def read_config_file():
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_config_file(data):
    """Persist settings to config.json (atomic enough for a local hub)."""
    ensure_dirs()
    tmp = config_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, config_path())


def migrate_legacy_data_dir():
    """v2.6 rebrand: move an existing ~/.printhub to ~/.advprint so the
    brand-new data folder keeps config.json + history.db + logs.
    Only runs when the NEW folder does not exist yet and the OLD one
    does. The old folder is left untouched (safe rollback)."""
    try:
        new_dir = CFG["data_dir"]
        old_dir = os.path.join(os.path.expanduser("~"), LEGACY_DATA_DIR)
        if (os.path.isdir(old_dir) and not os.path.isdir(new_dir)
                and os.path.normpath(old_dir) != os.path.normpath(new_dir)):
            import shutil
            shutil.copytree(old_dir, new_dir)
            ensure_dirs()
            log("[MIGRATE] moved data folder %s -> %s "
                "(old folder kept as backup)" % (old_dir, new_dir))
    except Exception as e:          # never block startup on migration
        log("[MIGRATE] skipped: %r" % (e,))


def init_config():
    """Merge config.json into CFG (env vars keep winning) and bootstrap the
    v2.0 token policy:
      * brand-new install -> RANDOM token saved to config.json
        (the old shared default 'PrintHub-2024' is gone) + header-only auth
      * old install (existing history.db / explicit env token) -> keeps
        working exactly as before, but /health raises
        default_token_warning so the UI can ask the user to change it.
    Called from db_init() and every CLI command - always safe to re-run."""
    global DEFAULT_TOKEN_WARNING
    migrate_legacy_data_dir()
    ensure_dirs()
    disk = read_config_file()
    fresh = not os.path.isfile(db_path()) and not disk
    for key in CONFIG_KEYS:
        if key in disk:
            want = CONFIG_TYPES.get(key)
            v = disk[key]
            try:
                if want is bool:
                    v = bool(v)
                elif want is int:
                    v = int(v)
                elif want is list:
                    v = list(v) if isinstance(v, list) else []
                elif want is dict:
                    v = dict(v) if isinstance(v, dict) else {}
            except (TypeError, ValueError):
                continue
            CFG[key] = v
    env_token = _env("TOKEN") or None
    if "token" not in disk and not env_token:
        if fresh:
            # NEW INSTALL: generate a private random token, persist it
            CFG["token"] = secrets.token_urlsafe(24)
            disk = {k: CFG[k] for k in CONFIG_KEYS}
            disk["token_header_only"] = True   # strict mode for new installs
            CFG["token_header_only"] = True
            write_config_file(disk)
            # v2.9.1 (audit M2 fix): the PLAIN token no longer goes into
            # hub.log (anyone who can read the log could read the token).
            # The token lives in config.json; print WHERE it is instead.
            log("[TOKEN] new install - generated a private random token and"
                " saved it to %s" % config_path())
            log("[TOKEN] read it from the tray menu (Open dashboard), from"
                " %s, or run: %s" % (config_path(), cli_cmd("token")))
            log("[TOKEN] enter this token once in the extension Options page.")
        else:
            # OLD INSTALL (1.x): keep the legacy default so nothing breaks
            CFG["token"] = LEGACY_TOKEN
    else:
        CFG["token"] = env_token or str(CFG["token"])
    DEFAULT_TOKEN_WARNING = (CFG["token"] == LEGACY_TOKEN)
    if DEFAULT_TOKEN_WARNING:
        log("[SECURITY] the default token '%s' is still in use - rotate it"
            " with:  %s" % (LEGACY_TOKEN, cli_cmd("token-rotate")))
    return CFG

def default_file_dir():
    """Preferred save-as-PDF folder: ~/Downloads/AdvPrint, with a safe
    fallback to ~/.advprint/files when Downloads is not writable."""
    if CFG.get("file_dir"):
        return CFG["file_dir"]
    dl = os.path.join(os.path.expanduser("~"), "Downloads", "AdvPrint")
    try:
        os.makedirs(dl, exist_ok=True)
        return dl
    except OSError:
        return os.path.join(CFG["data_dir"], "files")
SUMATRA_HINT = "winget install SumatraPDF.SumatraPDF   (or download from kjkpub.sf.net/sumatrapdf)"

def ensure_dirs():
    os.makedirs(CFG["data_dir"], exist_ok=True)
    os.makedirs(os.path.join(CFG["data_dir"], "jobs"), exist_ok=True)
    try:
        os.makedirs(default_file_dir(), exist_ok=True)
    except OSError:
        pass

def db_path():
    return os.path.join(CFG["data_dir"], "history.db")

def rotate_log_if_needed(path):
    """v2.0 log rotation: hub.log -> hub.log.1 -> ... (CFG['log_backups'])."""
    try:
        if os.path.getsize(path) < CFG["log_max_mb"] * 1024 * 1024:
            return
        keep = max(1, int(CFG["log_backups"]))
        for i in range(keep - 1, 0, -1):
            src, dst = "%s.%d" % (path, i), "%s.%d" % (path, i + 1)
            if os.path.isfile(src):
                os.replace(src, dst)
        os.replace(path, path + ".1")
    except OSError:
        pass


def log(msg):
    """Console + file log with timestamp and automatic size rotation."""
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        ensure_dirs()
        path = os.path.join(CFG["data_dir"], "hub.log")
        rotate_log_if_needed(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ------------------------------------------------------------
# v2.3 DEBUG: client error reports (extension JS / desktop tool)
# The extension with Debug mode ON POSTs every print error to
# POST /debug/report; the hub keeps the last 100 in memory AND in
# debug_reports.json, so GET /debug can answer "why does nothing
# print" with facts instead of guesses - including problems that
# happen in the browser and never reach hub.log.
# ------------------------------------------------------------
_DBG_REPORTS = []               # newest last, capped at 100
_DBG_LOADED = [False]

def _dbg_reports_path():
    return os.path.join(CFG["data_dir"], "debug_reports.json")

def load_debug_reports():
    """Read persisted reports once per process (survives restarts)."""
    if _DBG_LOADED[0]:
        return
    _DBG_LOADED[0] = True
    try:
        with open(_dbg_reports_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            _DBG_REPORTS[:] = [r for r in data[-100:] if isinstance(r, dict)]
    except Exception:
        pass

def save_debug_reports():
    try:
        ensure_dirs()
        tmp = _dbg_reports_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_DBG_REPORTS[-100:], f, ensure_ascii=False)
        os.replace(tmp, _dbg_reports_path())
    except Exception:
        pass

def add_debug_report(source="client", level="error", message="",
                     context=None, job_id=None, ip="-", site="-"):
    """Store one client error report (never raises, never logs raw)."""
    load_debug_reports()
    try:
        job_id = int(job_id)
    except (TypeError, ValueError):
        job_id = None
    if isinstance(context, (dict, list)):
        try:
            context = json.dumps(context, ensure_ascii=False)[:2000]
        except Exception:
            context = str(context)[:2000]
    else:
        context = str(context or "")[:2000] or None
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "source": str(source or "client")[:40],
        "level": str(level or "error").lower()[:10],
        "message": str(message or "")[:1000],
        "context": context,
        "job_id": job_id,
        "ip": str(ip or "-")[:64],
        "site": str(site or "-")[:200],
    }
    _DBG_REPORTS.append(entry)
    del _DBG_REPORTS[:-100]
    if CFG.get("debug"):
        log("[DEBUG] client report %s/%s: %s"
            % (entry["source"], entry["level"], entry["message"][:160]))
    save_debug_reports()
    return entry

# ------------------------------------------------------------
# Print history + queue state (SQLite) - thread-safe via one lock
# v2.0: the v1.x schema is MIGRATED in place (ALTER TABLE) so old
# databases keep working untouched - no export/import, no re-init.
# ------------------------------------------------------------
_DB_LOCK = threading.Lock()

# extra columns added on top of the v1.x jobs table (missing ones are
# appended automatically at startup; existing rows keep their values)
JOB_COLUMNS = {
    "priority":       "INTEGER DEFAULT 5",    # 1 = urgent ... 9 = low
    "attempts":       "INTEGER DEFAULT 0",    # retry counter
    "next_attempt_at": "TEXT",                # ISO - retry backoff / schedule
    "run_at":         "TEXT",                 # ISO - scheduled print time
    "dedupe_key":     "TEXT",                 # duplicate-blocking fingerprint
    "content_hash":   "TEXT",                 # sha256 of the document bytes
    "site":           "TEXT",                 # which site/origin requested it
    "reason":         "TEXT",                 # reprint reason (audit)
    "profile":        "TEXT",                 # print profile applied
    "pages":          "TEXT",                 # page range "1-3,5"
    "duplex":         "TEXT",
    "paper_size":     "TEXT",
    "tray":           "TEXT",
    "per_sheet":      "INTEGER DEFAULT 1",    # v2.1 n-up (CUPS)
    "quality":        "TEXT",                 # v2.1 draft|normal|high (CUPS)
    "watermarked":    "INTEGER DEFAULT 0",
    "held_reason":    "TEXT",                 # why the job is on hold
    "peer":           "TEXT",                 # peer hub the job was sent to
}

AUDIT_EVENTS = ("print.submitted", "print.completed", "print.failed",
                "print.held", "print.requeued", "print.auto_queued",
                "reprint", "job.canceled",
                "job.dead", "job.forwarded", "auth.failed", "auth.locked",
                "token.rotated", "config.changed", "queue.paused",
                "queue.resumed", "queue.cleared", "audit.purged",
                "debug.report")


def db():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def db_tune(conn):
    """v2.9.1 (audit P1 fix): WAL journal + NORMAL sync. The old rollback
    journal made every write an exclusive lock and every read of the
    worker's queue an fsync-heavy round trip on slow Windows disks; WAL
    lets readers and the single writer proceed concurrently. Called once
    at startup (the pragmas are persistent per database file)."""
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass

def db_init():
    ensure_dirs()
    init_config()
    with _DB_LOCK, db() as conn:
        db_tune(conn)              # v2.9.1 (P1): WAL + synchronous=NORMAL
        conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                   id         INTEGER PRIMARY KEY AUTOINCREMENT,
                   created_at TEXT NOT NULL,
                   kind       TEXT NOT NULL,            -- a4 | thermal | image | page
                   title      TEXT,
                   printer    TEXT,
                   copies     INTEGER DEFAULT 1,
                   status     TEXT NOT NULL,            -- queued|printing|printed|failed|canceled|saved
                   error      TEXT,
                   file_path  TEXT,
                   source     TEXT DEFAULT 'api',      -- extension | website | api | cli
                   origin_ip  TEXT,
                   duration_ms INTEGER DEFAULT 0
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS audit (
                   id        INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts        TEXT NOT NULL,
                   event     TEXT NOT NULL,
                   job_id    INTEGER,
                   actor     TEXT,
                   site      TEXT,
                   ip        TEXT,
                   doc_hash  TEXT,
                   printer   TEXT,
                   reason    TEXT,
                   details   TEXT
               )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        # v1.x -> v2.0 migration: add any missing columns, never touch data
        have = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
        for col, decl in JOB_COLUMNS.items():
            if col not in have:
                conn.execute("ALTER TABLE jobs ADD COLUMN %s %s" % (col, decl))
                log("[MIGRATE] jobs.%s column added (v2.0 schema)" % col)

def db_add(kind, title, printer, copies, file_path, source, origin_ip,
           status="queued", **extra):
    """Insert a job. Extra v2.0 fields ride along as kwargs (whitelisted
    against the schema so old callers stay source-compatible)."""
    allowed = {"priority", "attempts", "next_attempt_at", "run_at",
               "dedupe_key", "content_hash", "site", "reason", "profile",
               "pages", "duplex", "paper_size", "tray", "per_sheet",
               "quality", "watermarked",
               "held_reason", "peer", "duration_ms", "error"}
    cols = ["created_at", "kind", "title", "printer", "copies", "status",
            "file_path", "source", "origin_ip"]
    vals = [datetime.now().isoformat(timespec="seconds"), kind, title,
            printer, copies, status, file_path, source, origin_ip]
    for k, v in (extra or {}).items():
        if k in allowed and v is not None:
            cols.append(k)
            vals.append(v)
    with _DB_LOCK, db() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (%s) VALUES (%s)" % (",".join(cols),
                                                   ",".join("?" * len(cols))),
            vals)
        return cur.lastrowid

def db_update(job_id, **fields):
    sets = ", ".join("%s=?" % k for k in fields)
    with _DB_LOCK, db() as conn:
        conn.execute("UPDATE jobs SET %s WHERE id=?" % sets, (*fields.values(), job_id))

def db_get(job_id):
    with _DB_LOCK, db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

def db_list(limit=HISTORY_DEFAULT, status=None):
    with _DB_LOCK, db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY id DESC LIMIT ?",
                (status, int(limit))).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]

# v2.7.0: history management - job states grouped the way the new
# dashboard History tab and the bulk endpoints think about them.
JOB_ACTIVE_STATES = ("queued", "printing", "held", "scheduled")
JOB_TERMINAL_STATES = ("printed", "failed", "dead", "canceled",
                       "forwarded", "saved")
JOB_NOT_PRINTED_STATES = ("failed", "dead", "canceled")

def db_clear_history():
    """v2.7.0: wipe FINISHED jobs (printed / failed / dead / canceled /
    forwarded / saved) from the history. Jobs that still mean something
    (queued / printing / held / scheduled) are NEVER touched, so a
    "Clear ALL history" can never eat a waiting print job.
    Returns the number of rows removed."""
    with _DB_LOCK, db() as conn:
        cur = conn.execute(
            "DELETE FROM jobs WHERE status IN (%s)" %
            ",".join("?" * len(JOB_TERMINAL_STATES)), JOB_TERMINAL_STATES)
        return cur.rowcount or 0

def db_clear_queue():
    """v3.2.6 BUG FIX 1 - "History and Queue clear but not clean": the
    old /queue/clear only flipped queued jobs to canceled, so the queue
    AND the history stayed full of rows. NOW one call:
      1. cancels every live job (queued / held / scheduled / printing),
      2. DELETES every terminal row (the fresh cancels included), so
         the queue view is actually EMPTY afterwards.
    A job actively printing is canceled the same way the per-row Cancel
    button cancels it. Returns (canceled, removed)."""
    live = ("queued", "held", "scheduled", "printing")
    with _DB_LOCK, db() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status='canceled', "
            "error='queue cleared by user' WHERE status IN (%s)" %
            ",".join("?" * len(live)), live)
        canceled = cur.rowcount or 0
        cur = conn.execute(
            "DELETE FROM jobs WHERE status IN (%s)" %
            ",".join("?" * len(JOB_TERMINAL_STATES)), JOB_TERMINAL_STATES)
        removed = cur.rowcount or 0
    return canceled, removed

def db_list_not_printed(limit=500):
    """v2.7.0: every finished job that did NOT reach the printer
    (failed / dead / canceled) - the "Reprint all non-printed" source."""
    with _DB_LOCK, db() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status IN (%s) "
            "ORDER BY id DESC LIMIT ?" %
            ",".join("?" * len(JOB_NOT_PRINTED_STATES)),
            (*JOB_NOT_PRINTED_STATES, int(limit))).fetchall()
        return [dict(r) for r in rows]

def db_count_status():
    """v2.7.0: {status: n} map for the History tab filter badges."""
    with _DB_LOCK, db() as conn:
        return {r["status"]: int(r["n"]) for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")}

def db_next_queued():
    """Next printable job: priority first (1 = urgent), then FIFO, and
    only jobs whose retry backoff / scheduled time has come due."""
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, db() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status='queued' AND "
            "(next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY priority ASC, id ASC LIMIT 1", (now,)
        ).fetchone()
        return dict(row) if row else None

def db_promote_scheduled():
    """Move due scheduled jobs into the live queue (and clear their
    future retry timestamp so the worker picks them up). Returns count."""
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, db() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status='queued', next_attempt_at=NULL "
            "WHERE status='scheduled' AND run_at IS NOT NULL AND run_at <= ?",
            (now,))
        return cur.rowcount or 0

def db_find_duplicate(dedupe_key, minutes):
    """Recent alive job with the same fingerprint -> duplicate blocked."""
    if not dedupe_key or minutes <= 0:
        return None
    cutoff = (datetime.now() - timedelta(minutes=minutes)) \
        .isoformat(timespec="seconds")
    with _DB_LOCK, db() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE dedupe_key=? AND created_at >= ? AND "
            "status NOT IN ('failed','canceled','dead') "
            "ORDER BY id DESC LIMIT 1", (dedupe_key, cutoff)).fetchone()
        return dict(row) if row else None

def db_count_pending():
    with _DB_LOCK, db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','printing')"
        ).fetchone()
        return int(row["n"])

def db_count_today():
    today = datetime.now().strftime("%Y-%m-%d")
    with _DB_LOCK, db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE created_at LIKE ?",
            (today + "%",)).fetchone()
        return int(row["n"])

def db_count_held():
    with _DB_LOCK, db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE status='held'").fetchone()
        return int(row["n"])

def db_stats():
    """Success rate + queue size for the dashboard (last 7 days + today)."""
    week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    with _DB_LOCK, db() as conn:
        by = {}
        for r in conn.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status"):
            by[r["status"]] = int(r["n"])
        row = conn.execute(
            "SELECT COUNT(*) n FROM jobs WHERE status='printed' AND created_at >= ?",
            (week,)).fetchone()
        ok7 = int(row["n"])
        row = conn.execute(
            "SELECT COUNT(*) n FROM jobs WHERE status IN ('failed','dead') AND created_at >= ?",
            (week,)).fetchone()
        bad7 = int(row["n"])
    total7 = ok7 + bad7
    return {
        "by_status": by,
        "queue_size": db_count_pending() + db_count_held(),
        "jobs_today": db_count_today(),
        "success_rate": round(100.0 * ok7 / total7, 1) if total7 else None,
        "printed_7d": ok7,
        "failed_7d": bad7,
    }

# ------------------------------------------------------------
# Audit log (v2.0): who / which site / document hash / printer / time
# ------------------------------------------------------------
def db_audit(event, job_id=None, actor=None, site=None, ip=None,
             doc_hash=None, printer=None, reason=None, details=None):
    if not CFG.get("audit_enabled", True):
        return
    try:
        with _DB_LOCK, db() as conn:
            conn.execute(
                "INSERT INTO audit (ts, event, job_id, actor, site, ip,"
                " doc_hash, printer, reason, details)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), event,
                 job_id, actor, site, ip, doc_hash, printer, reason,
                 details))
    except Exception as e:
        log("[WARN] audit write failed: %s" % e)

def audit_list(limit=50, event=None):
    q = "SELECT * FROM audit"
    args = []
    if event:
        q += " WHERE event=?"
        args.append(event)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    with _DB_LOCK, db() as conn:
        return [dict(r) for r in conn.execute(q, args)]

def audit_purge(days):
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with _DB_LOCK, db() as conn:
        cur = conn.execute("DELETE FROM audit WHERE ts < ?", (cutoff,))
        n = cur.rowcount or 0
    if n:
        db_audit("audit.purged", details="%d entries older than %dd removed" % (n, days))
    return n

# ------------------------------------------------------------
# Printer + browser discovery (best effort, pure stdlib)
# ------------------------------------------------------------
# ------------------------------------------------------------
# SumatraPDF discovery (v2.5 - fully dynamic, service-safe)
# ------------------------------------------------------------
SUMATRA_LAST = {"found": None, "tried": []}   # last search report -> /debug

def _winreg_lookup_sumatra():
    """SumatraPDF registers its location for BOTH per-user (%LOCALAPPDATA%)
    and per-machine installs. HKLM works even when the hub runs as a
    Windows SERVICE (where %LOCALAPPDATA% points at the service account)."""
    if not winreg:
        return []
    out = []
    APP = r"Software\Microsoft\Windows\CurrentVersion\App Paths\SumatraPDF.exe"
    UNI = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SumatraPDF"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            for sub, name in ((APP, ""), (UNI, "InstallPath")):
                try:
                    with winreg.OpenKey(hive, sub, 0,
                                        winreg.KEY_READ | view) as k:
                        val, _ = winreg.QueryValueEx(k, name)
                except OSError:
                    continue
                if not val:
                    continue
                val = str(val)
                out.append(val if val.lower().endswith(".exe")
                           else os.path.join(val, "SumatraPDF.exe"))
    return out

def find_sumatra():
    """Locate SumatraPDF.exe. The user name is NEVER hardcoded:
    %LOCALAPPDATA% / ~ resolve to the CURRENT Windows user's profile
    (e.g. C:\\Users\\<whatever>\\AppData\\Local\\SumatraPDF). As a last
    resort every profile is globbed (C:\\Users\\*\\...) so the hub finds
    SumatraPDF even when running as a SERVICE under a different account.
    Detection is re-run fresh on every call - installing SumatraPDF takes
    effect on the NEXT print job, no hub restart needed. Manual override:
    dashboard Settings (config.json "sumatra_path") or ADVPRINT_SUMATRA.
    v2.6.4: the whole body is crash-proof - this function is on the
    /health snapshot path, /debug, /diagnostics AND the print path, so
    ANY problem (registry, glob, environment) must degrade to 'not
    found', never raise."""
    try:
        return _find_sumatra_inner()
    except Exception as e:                # never break health/debug/print
        try:
            log("[WARN] SumatraPDF lookup failed (%s) - treated as not"
                " found" % e)
        except Exception:
            pass
        SUMATRA_LAST["found"] = None
        return None


def _find_sumatra_inner():
    tried = []
    if not IS_WIN:
        SUMATRA_LAST["found"] = None
        SUMATRA_LAST["tried"] = []
        return None
    la = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local")
    pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
    pfx86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    roots = [
        CFG.get("sumatra_path"),                     # Settings override wins
        _env("SUMATRA"),
        # v2.6.3: the Setup exe bundles a portable SumatraPDF.exe in the
        # install tree (<install>\tools\SumatraPDF.exe) - PDF printing
        # works with zero user setup, no separate download.
        os.path.join(os.path.dirname(_HUB_DIR), "tools", "SumatraPDF.exe"),
        os.path.join(_HUB_DIR, "tools", "SumatraPDF.exe"),
        os.path.join(la, "SumatraPDF", "SumatraPDF.exe"),   # per-user install
        # v2.6.5: newer SumatraPDF installers also use %LOCALAPPDATA%\Programs
        os.path.join(la, "Programs", "SumatraPDF", "SumatraPDF.exe"),
        os.path.join(os.path.expanduser("~"), "AppData", "Local",
                     "SumatraPDF", "SumatraPDF.exe"),
        os.path.join(pf, "SumatraPDF", "SumatraPDF.exe"),   # per-machine
        os.path.join(pfx86, "SumatraPDF", "SumatraPDF.exe"),
        r"C:\Tools\SumatraPDF.exe",
    ]
    roots += _winreg_lookup_sumatra()
    roots.append(shutil.which("SumatraPDF.exe"))
    for c in roots:
        if not c:
            continue
        c = os.path.expandvars(os.path.expanduser(str(c)))
        tried.append(c)
        if os.path.isfile(c):
            SUMATRA_LAST["found"] = c
            SUMATRA_LAST["tried"] = tried
            return c
    # last resort 1: portable zips sometimes keep the exe in a subfolder
    for base in (os.path.join(la, "SumatraPDF"), os.path.join(pf, "SumatraPDF"),
                 os.path.join(pfx86, "SumatraPDF"), r"C:\Tools"):
        if base and os.path.isdir(base):
            for pat in ("Sumatra*.exe", "*\\Sumatra*.exe"):
                for hit in sorted(glob.glob(os.path.join(base, pat))):
                    if os.path.basename(hit).lower().endswith("sumatrapdf.exe"):
                        tried.append(hit + "  (found by folder scan)")
                        SUMATRA_LAST["found"] = hit
                        SUMATRA_LAST["tried"] = tried
                        return hit
    # last resort 2 (v2.5): hub running as a SERVICE? %LOCALAPPDATA% then
    # belongs to the service account, not the logged-in user - scan ALL
    # user profiles so 'Admin is dynamic for every pc own user name'.
    for hit in glob.glob(os.path.join("C:\\", "Users", "*", "AppData",
                                      "Local", "SumatraPDF",
                                      "SumatraPDF.exe")):
        tried.append(hit + "  (found by all-users profile scan)")
        SUMATRA_LAST["found"] = hit
        SUMATRA_LAST["tried"] = tried
        return hit
    SUMATRA_LAST["found"] = None
    SUMATRA_LAST["tried"] = tried
    return None

# v2.6.7: "File (PDF)" is the hub's own virtual save-as-PDF
# destination. It was MISSING here, so a QUEUED job with printer
# "File (PDF)" went to the SumatraPDF backend as a Windows printer
# name that does not exist - SumatraPDF exited 1 with no output
# ("print backend exit 1: ", job dead-lettered).
VIRTUAL_PDF_PRINTERS = ("Microsoft Print to PDF", "File (PDF)")

def is_virtual_pdf_printer(name):
    """A virtual PDF printer needs no renderer and would pop a Save-As
    dialog - the hub saves the PDF directly instead (status 'saved')."""
    n = (name or "").lower()
    return any(v.lower() in n for v in VIRTUAL_PDF_PRINTERS)

def find_browser():
    """Locate a Chromium browser for headless HTML->PDF (Chrome, Edge, Chromium)."""
    if IS_WIN:
        cands = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for c in cands:
            if c and os.path.exists(c):
                return c
        return None
    if IS_MAC:
        cands = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for c in cands:
            if os.path.exists(c):
                return c
        return None
    for name in ("google-chrome", "google-chrome-stable", "microsoft-edge",
                 "microsoft-edge-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    return None

def list_printers():
    """Return list of installed printer names (best effort)."""
    try:
        if IS_WIN:
            ps = "Get-CimInstance Win32_Printer | Select-Object -ExpandProperty Name"
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=10,
                                 creationflags=HIDE)
            names = [l.strip() for l in (out.stdout or "").splitlines() if l.strip()]
            return names
        else:
            out = subprocess.run(["lpstat", "-e"], capture_output=True,
                                 text=True, timeout=10)
            names = [l.strip() for l in (out.stdout or "").splitlines() if l.strip()]
            if not names:  # older CUPS: try -p and strip state
                out = subprocess.run(["lpstat", "-p"], capture_output=True,
                                     text=True, timeout=10)
                for l in (out.stdout or "").splitlines():
                    if l.startswith("printer "):
                        names.append(l.split()[1])
            return names
    except Exception as e:
        log("[WARN] list_printers failed: %s" % e)
        return []


# ------------------------------------------------------------
# v3.0.9 PER-PRINTER IPP QUEUES - every LOCAL printer also gets its
# own queue on the hub, so ONE center PC serves the whole LAN:
#     ipp://<lan-ip>:9235/ipp/print/<printer>
# The hub stays the central IPP middleware: child PCs and phones
# print to exactly the printer the queue names - no local tool
# needed on the client. The queue name accepts BOTH the raw
# Windows printer name (URL-encoded, "HP%20Laser%20103%20107%20108")
# and a slug form ("HP-Laser-103-107-108") - matching is case-
# insensitive and ignores spaces/punctuation, so whatever the
# client typed after Add Printer just works.
# ------------------------------------------------------------
def _ipp_queue_slug(name):
    """URL path form of a printer name. v3.3.0 BUG 3: UNICODE-aware -
    the old [^a-z0-9] slug folded EVERY non-ASCII printer name (Bangla,
    Arabic, CJK - common in real labs and shops) to the single slug
    "printer", so all those printers shared ONE queue and none of them
    was separately addressable. Word characters (\\w, Unicode letters
    included) are kept now
    ("\u09aa\u09cd\u09b0\u09bf\u09a8\u09cd\u099f\u09be\u09b0 \u09e7" -> "\u09aa\u09cd\u09b0\u09bf\u09a8\u09cd\u099f\u09be\u09b0-\u09e7"),
    while ASCII names slug exactly as before ("HP Laser 103" ->
    hp-laser-103) so queues added by older releases keep resolving."""
    return re.sub(r"[^\w]+", "-", (name or "").strip().lower(),
                  flags=re.UNICODE).strip("-") or "printer"


def _ipp_queue_key(name):
    """Collision-tolerant compare key for queue resolution: EVERY
    non-word character AND underscores are removed (spaces, dashes,
    punctuation), Unicode word characters kept, lowercased.
    "HP Laser 103", "hp-laser-103", "hp_laser_103" and "HP  Laser___103!"
    all key to hplaser103 - so a queue the client added under the OLD
    dash slug keeps resolving after the v3.3.0 slug change, and
    whatever slug style the client sends (Windows %20-spaces, CUPS
    dashes, phones typing freely) all lands on the same printer."""
    return re.sub(r"[\W_]+", "", str(name or "").strip().lower(),
                  flags=re.UNICODE)


def _ipp_queue_match(name):
    """Resolve a per-printer queue name (raw name, URL-encoded, dash slug
    or Unicode slug) back to the REAL local printer name. Returns ''
    (empty string) for no match. v3.3.0 BUG 3: the compare runs through
    _ipp_queue_key so the slug STYLE does not matter - only the letters
    and digits of the name do."""
    name = urllib.parse.unquote(str(name or "")).strip()
    want = _ipp_queue_key(name)
    if not want:
        return ""
    for n in list_printers_cached(max_age=30.0):
        if _ipp_queue_key(n) == want:
            return n
    return ""


# v3.2.9 BUG 2: MEMOIZED queue resolution. EVERY IPP request from EVERY
# PC resolves its queue name through the printer list (Windows alone
# sends Get-Printer-Attributes + Validate-Job + Print-Job for one
# add-printer run); with several PCs adding/printing at the same time
# the OS enumeration ran again and again. The memo answers repeated
# slugs from cache (one OS refresh per TTL window); unknown slugs are
# cached SHORTER so a printer that appears later is found quickly.
_QMATCH_CACHE = {}
_QMATCH_LOCK = threading.Lock()
_QMATCH_TTL_OK = 10.0            # resolved slug -> printer name
_QMATCH_TTL_NEG = 5.0            # unknown slug
_QMATCH_LAST_FORCE = {"t": 0.0}  # v3.3.0 BUG 3: last forced refresh


def _ipp_queue_match_cached(name):
    """Thread-safe memo wrapper around _ipp_queue_match (v3.2.9).
    v3.3.0 BUG 3: a NEGATIVE answer force-refreshes the OS printer list
    ONCE (rate-limited to one refresh per 3 s) before the negative memo
    is stored - a printer added on the hub PC gets its own queue within
    seconds, instead of waiting out the 30 s list cache AND the 5 s
    negative memo. 'Any printer that exists' is separately active
    immediately, which is exactly what the per-printer queue promise
    means."""
    key = _ipp_queue_key(urllib.parse.unquote(str(name or "")))
    if not key:
        return ""
    now = time.time()
    with _QMATCH_LOCK:
        hit = _QMATCH_CACHE.get(key)
        if hit is not None:
            ts, val = hit
            if now - ts <= (_QMATCH_TTL_OK if val else _QMATCH_TTL_NEG):
                return val
    got = _ipp_queue_match(name)
    if not got:
        try:
            if now - _QMATCH_LAST_FORCE["t"] >= 3.0:
                _QMATCH_LAST_FORCE["t"] = now
                list_printers_cached(max_age=0.0)   # forced OS re-enum
                got = _ipp_queue_match(name)
        except Exception:
            pass
    with _QMATCH_LOCK:
        _QMATCH_CACHE[key] = (now, got)
        if len(_QMATCH_CACHE) > 256:
            for k in sorted(_QMATCH_CACHE, key=lambda k: _QMATCH_CACHE[k][0])[:-128]:
                _QMATCH_CACHE.pop(k, None)
    return got


def _active_queue_hint(limit=6):
    """v3.3.0 BUG 3: a 404 for an unknown per-printer queue lists the
    queues that ARE live right now - 'any printer that exists' becomes
    discoverable from the error itself instead of a dead end."""
    try:
        names = [n for n in list_printers_cached(max_age=30.0) if n][:limit]
    except Exception:
        names = []
    if not names:
        return ""
    try:
        return " Active queues right now: " + \
            ", ".join(_ipp_queue_slug(n) for n in names) + "."
    except Exception:
        return ""


def ipp_queue_url(printer, host=None):
    """ipp:// URL a client adds for ONE local printer (per-printer queue).
    v3.2.9: optional host override - when a LAN PC asks for the queue
    list (or opens the queue landing page) the URL uses the address
    THAT device reached the hub with (Host header), so every PC sees
    its own reachable ip:port instead of one global lan_ip().
    v3.3.0 BUG 3: the slug is percent-encoded, so a Unicode printer name
    produces a valid URL (ipp://ip:9235/ipp/print/%E0%A6%AA...) instead
    of an invalid bare-Unicode path. ASCII slugs are left untouched."""
    ip = str(host) if host else (lan_ip() if CFG.get("share_lan")
                                 else "127.0.0.1")
    return "ipp://%s:%d/ipp/print/%s" % (ip, int(CFG.get("port", 9235)),
                                         quote(_ipp_queue_slug(printer),
                                               safe=""))

def default_printer():
    """Return the OS default printer name (best effort)."""
    try:
        if IS_WIN:
            ps = ("(Get-CimInstance Win32_Printer | Where-Object Default)"
                  ".Name")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=10,
                                 creationflags=HIDE)
            name = (out.stdout or "").strip()
            return name or None
        else:
            out = subprocess.run(["lpstat", "-d"], capture_output=True,
                                 text=True, timeout=10)
            for l in (out.stdout or "").splitlines():
                if "system default destination" in l:
                    return l.split(":")[-1].strip()
            return None
    except Exception:
        return None


# ------------------------------------------------------------
# v3.2.5 BUG FIX 1: SET THE OS DEFAULT PRINTER FOR REAL.
# The user report: "Always Default Printer of windows selected even
# set selected printer as default - why auto change to windows default
# when hub set other printer as default, why not save it."
# Root cause: the old "Set Default" button only wrote the hub config
# key "printer" (the hub's preferred DESTINATION) - the WINDOWS default
# printer was never touched, and with Windows' "let Windows manage my
# default printer" enabled (the factory setting on Win10/11) the OS
# silently re-points the default at the last-printed printer anyway.
# The fix performs the OS-level change AND opts out of the auto-manage
# feature in the same call:
#   1. HKCU\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows
#        -> LegacyDefaultPrinterMode = 1 (DWORD, 1 = legacy user-managed
#           mode: Windows stops re-pointing the default behind the
#           user's back; this is exactly the "Let Windows manage my
#           default printer" toggle in Settings, per-user, no UAC)
#   2. WScript.Network.SetDefaultPrinter("<name>")  (COM, per-user)
#   3. read the default back via Win32_Printer and return it so the
#      console toast reports the VERIFIED result
# Unix/CUPS: lpoptions -d <name> sets the per-user default (no root
# needed); the system default stays lpadmin territory.
# ------------------------------------------------------------
def os_set_default_printer(name):
    """Set the OS default printer. Returns (ok, actual_default, detail)."""
    name = str(name or "").strip()
    if not name:
        return False, default_printer() or "", "no printer name given"
    known = list_printers_cached(max_age=5.0)
    if known and name not in known:
        # resolve by slug so a card-copied name always matches
        for n in known:
            if re.sub(r"[^a-z0-9]+", "-", (n or "").strip().lower()
                      ).strip("-") == re.sub(r"[^a-z0-9]+", "-",
                                             name.lower()).strip("-"):
                name = n
                break
    if IS_WIN:
        safe = name.replace("'", "''")
        ps = ("try { Set-ItemProperty -Path "
              "'HKCU:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"
              "\\Windows' -Name LegacyDefaultPrinterMode -Value 1 "
              "-Type DWord -ErrorAction SilentlyContinue } catch {};"
              "(New-Object -ComObject WScript.Network).SetDefaultPrinter"
              "('" + safe + "');"
              "(Get-CimInstance Win32_Printer | Where-Object Default).Name")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=HIDE)
            lines = [l.strip() for l in (out.stdout or "").splitlines()
                     if l.strip()]
            got = lines[0] if lines else ""
            # multi-line output = several printers flagged Default (rare
            # WMI artefact); take the one that matches the request
            for l in lines:
                if l.lower() == name.lower():
                    got = l
                    break
            ok = bool(got) and got.lower() == name.lower()
            if ok:
                detail = ("Windows default printer is now '%s' "
                          "(auto-manage disabled: LegacyDefaultPrinter"
                          "Mode=1)" % got)
            else:
                detail = ("SetDefaultPrinter ran (rc %s) but the OS "
                          "default reads '%s' - printer name mismatch?"
                          % (out.returncode, got or "none"))
            log("[SETDEF] requested '%s' -> %s" % (name, detail))
            return ok, got or name, detail
        except Exception as e:
            log("[SETDEF] error: %s" % e)
            return False, default_printer() or name, str(e)
    try:
        out = subprocess.run(["lpoptions", "-d", name],
                             capture_output=True, text=True, timeout=10)
        got = default_printer() or name
        ok = out.returncode == 0 and (got or "").lower() == name.lower()
        detail = ("CUPS default printer is now '%s' (lpoptions -d)" % got
                  if ok else
                  (out.stderr or "lpoptions -d failed").strip())
        log("[SETDEF] requested '%s' -> %s" % (name, detail))
        return ok, got or name, detail
    except Exception as e:
        return False, default_printer() or name, str(e)

# ------------------------------------------------------------
# Printer STATUS (v2.0): ready / offline / paper-out / error
# Windows: Win32_Printer via PowerShell; Unix: lpstat -p states.
# Cached 20 s so the worker loop can poll it freely.
# ------------------------------------------------------------
_PS_CACHE = {"t": 0.0, "v": {}}

def _printer_status_windows():
    ps = ("Get-CimInstance Win32_Printer | ForEach-Object {"
          "\"{0}|{1}|{2}|{3}\" -f $_.Name,$_.PrinterStatus,"
          "$_.DetectedErrorState,[int]([bool]$_.WorkOffline) }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, timeout=8,
                         creationflags=HIDE)
    res = {}
    for line in (out.stdout or "").splitlines():
        parts = (line or "").strip().split("|")
        if len(parts) != 4 or not parts[0]:
            continue
        name = parts[0]
        try:
            pstat, derr, woff = int(parts[1] or 0), int(parts[2] or 0), int(parts[3] or 0)
        except ValueError:
            pstat, derr, woff = 0, 0, 0
        if woff or pstat == 7 or derr == 8:
            st = "offline"
        elif derr in (3, 4):
            st = "paper-out"
        elif derr in (5, 6, 7, 9, 10) or pstat == 6:
            st = "error"
        elif pstat in (3, 4, 5) or derr == 2 or pstat == 0:
            st = "ready"
        else:
            st = "unknown"
        res[name] = st
    return res

def _printer_status_unix():
    out = subprocess.run(["lpstat", "-p"], capture_output=True,
                         text=True, timeout=10)
    res = {}
    for line in (out.stdout or "").splitlines():
        m = re.match(r"^printer (\S+) (.+)$", line or "")
        if not m:
            continue
        name, state = m.group(1), m.group(2)
        if "disabled" in state:
            res[name] = "offline"
        elif "printing" in state or "idle" in state or "processing" in state:
            res[name] = "ready"
        else:
            res[name] = "unknown"
    return res

def printers_status(force=False):
    """{printer_name: 'ready'|'offline'|'paper-out'|'error'|'unknown'}."""
    # v2.6.3: the freshness check no longer requires a NON-EMPTY cache -
    # an empty (failed) scan is stamped too, so one broken scan costs at
    # most one PowerShell run per interval instead of one per request.
    if not force and time.time() - _PS_CACHE["t"] < 20:
        return _PS_CACHE["v"]
    try:
        res = _printer_status_windows() if IS_WIN else _printer_status_unix()
    except Exception as e:
        log("[WARN] printer status check failed: %s" % e)
        res = {}
    # v2.6.3: stamp the cache EVEN when the scan came back empty or
    # failed. The old code only stamped on success, so a slow or
    # AV-blocked PowerShell re-ran on EVERY caller - /health could hang
    # for its full timeout again and again while the hub looked
    # "listening but dead". One failed scan now costs at most one retry
    # per interval, never a request-path hang (see the *_cached wrappers).
    _PS_CACHE["t"] = time.time()
    if res:
        _PS_CACHE["v"] = res
    return res


# ------------------------------------------------------------
# v2.6.3: NON-BLOCKING CACHE LAYER FOR ALL HTTP/HEALTH PATHS
# ------------------------------------------------------------
# The v2.6.2 incident: hub.log said "listening on http://127.0.0.1:9235"
# but the console tool reported "did not answer within 20 seconds" and
# the extension showed OFFLINE, while the desktop tool (TCP-only check)
# said RUNNING. Root cause: /health ran up to THREE PowerShell/WMI scans
# on the request path (default_printer + printers_status + list), each
# with a 20 s timeout - a cold WMI or an AV-slowed powershell.exe made
# every probe outlive its client timeout. Everything below serves stale
# data instantly and refreshes in the background instead.
_SWR_LOCK = threading.Lock()
_SWR_BUSY = {}


def _swr_refresh(key, fn):
    """Run fn() once in a daemon thread (single-flight per key)."""
    with _SWR_LOCK:
        if _SWR_BUSY.get(key):
            return
        _SWR_BUSY[key] = True

    def _bg():
        try:
            fn()
        except Exception:
            pass
        finally:
            with _SWR_LOCK:
                _SWR_BUSY[key] = False

    threading.Thread(target=_bg, daemon=True,
                     name="advprint-refresh-" + key).start()


_LP_CACHE = {"t": 0.0, "v": []}      # printer NAMES
_DP_CACHE = {"t": 0.0, "v": None}    # default printer name


def _lp_refresh():
    _LP_CACHE["t"] = time.time()
    _LP_CACHE["v"] = list_printers()


def _dp_refresh():
    _DP_CACHE["t"] = time.time()
    _DP_CACHE["v"] = default_printer()


def list_printers_cached(max_age=60.0):
    """Instant read of the printer-name cache; refreshes in background."""
    if not _LP_CACHE["v"] or time.time() - _LP_CACHE["t"] > max_age:
        _swr_refresh("printers-list", _lp_refresh)
    return list(_LP_CACHE["v"])


def default_printer_cached(max_age=60.0):
    """Instant read of the default-printer cache; refreshes in background."""
    if _DP_CACHE["v"] is None or time.time() - _DP_CACHE["t"] > max_age:
        _swr_refresh("default-printer", _dp_refresh)
    return _DP_CACHE["v"]


def printers_status_cached(max_age=20.0):
    """Instant read of the printer-status cache; refreshes in background.
    NEVER spawns PowerShell/WMI on the calling thread."""
    if time.time() - _PS_CACHE["t"] > max_age:
        _swr_refresh("printers-status",
                     lambda: printers_status(force=True))
    return dict(_PS_CACHE["v"])


# ------------------------------------------------------------
# v2.6.3: /health SNAPSHOT - instant answers, zero blocking
# ------------------------------------------------------------
# Built every 3 s by a background thread (and once at boot). The HTTP
# route only hands out the finished dict, so /health answers in
# microseconds even while WMI/PowerShell is slow or blocked.
_HEALTH_SNAP = {"t": 0.0, "data": {}}
_HEALTH_LOCK = threading.Lock()
_HEALTH_THREAD = [None]


# ------------------------------------------------------------
# v3.2.3 ALLOWED IPS - who may reach the hub from the network
# ------------------------------------------------------------
_ACL_AUDIT_TS = {}        # ip -> last acl.denied audit write (1 per 10 s)

def ip_allowed_by_list(ip, rules):
    """True when client IP `ip` matches the allowed_ips rule list
    (v3.2.3 ALLOWED IPS). Rule entries (string list):
      "*"              every address (factory default, all-LAN open hub)
      "10.26.94.100"   exact IPv4 / IPv6 address
      "10.26.94.0/24"  CIDR network (a whole subnet)
      "10.26.*"        simple wildcard (matches the dotted text prefix)
    Matching is lenient by design: an unparsable entry falls back to a
    plain text comparison against the normalised address, so a typo can
    only make the hub STRICTER (deny), never silently open it."""
    rules = rules or ["*"]
    if "*" in rules:
        return True
    if not ip:
        return False
    ip = str(ip).strip()
    if ip.startswith("::ffff:") and "." in ip:
        ip = ip[len("::ffff:"):]              # IPv4-mapped IPv6 -> plain IPv4
    ip = ip.split("%")[0]                     # drop an IPv6 zone suffix
    for raw in rules:
        rule = str(raw).strip()
        if not rule:
            continue
        if rule == "*":
            return True
        if rule.startswith("::ffff:") and "." in rule:
            rule = rule[len("::ffff:"):]
        if "/" in rule:                       # CIDR network (10.26.94.0/24)
            try:
                import ipaddress as _ipa
                if _ipa.ip_address(ip) in _ipa.ip_network(rule,
                                                          strict=False):
                    return True
                continue
            except ValueError:
                pass                          # bad CIDR -> text compare
        if "*" in rule:                       # simple wildcard (10.26.*)
            import fnmatch as _fn
            if _fn.fnmatchcase(ip, rule):
                return True
            continue
        if rule == ip:                        # exact address
            return True
    return False

# ------------------------------------------------------------
# v3.2.6 UI SECURITY GATE - "only own IP or loopback IP can show UI"
# ------------------------------------------------------------
# The user report: "currently any one can change different HUB UI
# setting it very dangerous. One security reason any same LAN can
# access and change value - this is bad. Only own IP or loopback IP
# can show UI. But LAN Sharing & Other PCs related Send/IPP etc
# different IP can call or access, otherwise can't view or connect.
# Print not blocked if all IP *, or given IP allow list."
#
# Rule, in two layers:
#   LAYER 1 (unchanged) _ip_gate(): allowed_ips decides WHO may talk to
#   the hub at all - ["*"] (factory default) or a real allow list.
#   LAYER 2 (NEW) _mgmt_locked(): from a NON-LOCAL address only the
#   PRINT SURFACE answers. Everything else - the console UI, the docs,
#   every settings / management endpoint, /config POST, /token/*,
#   /queue control, /history/clear, /tool, /qr, /stats, /audit,
#   /export, /debug, /peers, /dropzone - is answered with a branded
#   403 that points the visitor at the print URLs.
#
# PRINT SURFACE (open to every allowed IP, token rules unchanged):
#   GET  /health /jobs /printers /testprint /connect /send /qr?NO
#   GET  /ipp/* (landing + per-printer queues)  /extension/* (updates.xml,
#        CRX, info - child-PC extensions self-update from here)
#   POST /print /send /ipp/* /jobs/<id>/cancel /jobs/<id>/print-now
#        /jobs/bulk-reprint /client/report /debug/report /peer-connect
#   The 631 IPP mirror and the RAW 9100 port are print surface too and
#   keep their own ACL logic.
#
# The hub PC itself (loopback 127.0.0.1/::1 AND any of the machine's
# own IPs - so http://<own-lan-ip>:9235/ui still works ON the hub PC)
# always passes BOTH layers: the owner can never lock themselves out.

_OWN_IPS_CACHE = {"ips": None, "t": 0.0}

def own_ip_set():
    """Every IP address that belongs to THIS machine (loopback + all
    LAN addresses). Cached 5 s so DHCP changes are picked up without
    hammering getaddrinfo on every request."""
    now = time.time()
    if _OWN_IPS_CACHE["ips"] is not None and now - _OWN_IPS_CACHE["t"] < 5.0:
        return _OWN_IPS_CACHE["ips"]
    ips = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
    try:
        lip = lan_ip()
        if lip:
            ips.add(lip)
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ips.add(str(info[4][0]))
    except Exception:
        pass
    ips.discard("")
    _OWN_IPS_CACHE["ips"] = ips
    _OWN_IPS_CACHE["t"] = now
    return ips

# Routes a REMOTE (non-local) client may still call - the print surface.
MGMT_OPEN_GET_EXACT = frozenset((
    "/health",      # extension + child PCs poll it
    "/jobs",        # popup queue list / reprint picker
    "/printers",    # destination picker on child PCs
    "/testprint",   # a test page IS a print job
    "/connect",     # the one-click invite landing (opens on the other PC)
    "/send",        # the phones' send portal page
))
MGMT_OPEN_GET_PREFIX = ("/ipp", "/extension/")
MGMT_OPEN_POST_EXACT = frozenset((
    "/print",           # THE print API
    "/send",            # print upload (portal + curl -F)
    "/peer-connect",    # invite landing POST (still loopback-checked inside)
    "/client/report",   # write-only extension error reports
    "/debug/report",    # ditto
))
MGMT_OPEN_POST_PREFIX = ("/ipp", "/jobs/")   # /jobs/<id>/cancel, print-now,
                                             # bulk-reprint = print actions
# ...but queue CONTROL stays local even under an open prefix:
MGMT_POST_DENY = frozenset(("/jobs/release_all",))

def build_health_snapshot():
    """Compute the /health body off the request path."""
    have_db = False
    try:
        have_db = os.path.isfile(db_path())
    except Exception:
        pass
    st = db_stats() if have_db else {}
    ps = printers_status_cached()
    try:
        ready = sum(1 for v in ps.values() if v == "ready")
    except Exception:
        ready = 0
    try:
        paused = not RESUME_EVENT.is_set()
    except Exception:
        paused = False
    snap = {
        "ok": True, "app": APP_NAME, "version": VERSION,
        "host": socket.gethostname(),
        "branding": BRANDING,
        "os": "windows" if IS_WIN else ("macos" if IS_MAC else "linux"),
        "default_printer": default_printer_cached(),
        "sumatra_found": (find_sumatra() is not None) if IS_WIN else None,
        "browser_found": find_browser() is not None,
        "paused": paused,
        "pending": db_count_pending() if have_db else 0,
        "held": db_count_held() if have_db else 0,
        "jobs_today": st.get("jobs_today", 0),
        "file_dir": default_file_dir(),
        "token_set": bool(CFG["token"]),
        # v2.6.5: last 4 characters only - enough for the user to SEE that
        # the hub token matches the one pasted in the extension Options
        # (the 401 / auth.failed family), never enough to guess or reuse.
        "token_hint": (CFG["token"][-4:] if CFG["token"] else ""),
        "default_token_warning": DEFAULT_TOKEN_WARNING,
        "token_header_only": bool(CFG.get("token_header_only")),
        "autostart": autostart_enabled(),
        "service": service_state(),
        "queue_bypass": True,
        "hold_offline": bool(CFG.get("hold_offline", True)),
        "worker_alive": bool(_WORKER_THREAD[0]
                             and _WORKER_THREAD[0].is_alive()),
        "debug": bool(CFG.get("debug")),
        "instant_auto_queue": bool(
            CFG.get("instant_auto_queue", True)),
        "share_lan": bool(CFG.get("share_lan")),
        # v3.2.3 ALLOWED IPS: live state for the LAN tab card
        "allowed_ips": list(CFG.get("allowed_ips") or ["*"]),
        "acl_restricted": "*" not in (CFG.get("allowed_ips") or ["*"]),
        "ipp_printer": bool(CFG.get("ipp_printer", True)),
        "ipp_url": ("http://%s:%d/ipp/print" % (lan_ip(), CFG["port"]))
                   if CFG.get("share_lan") else None,
        "raw_printer_port": int(CFG.get("raw_printer_port") or 0),
        "raw_active": bool(_RAW_SOCKS),
        # v3.3.0 BUG 2: the sockets the RAW port actually listens on
        # (every interface, IPv4 + IPv6) - the LAN panel shows the truth
        "raw_addrs": list(_RAW_BINDS),
        # v2.9: print destination - ANY printer (default / selected / IP)
        "dest_mode": (CFG.get("dest_mode")
                      or ("selected" if CFG.get("printer")
                          else "default")),
        "selected_printer": CFG.get("printer") or "",
        "dest_display": dest_display(),
        "ip_printer": {"host": CFG.get("ip_printer_host") or "",
                       "port": int(CFG.get("ip_printer_port") or 0),
                       "proto": CFG.get("ip_printer_proto") or "raw"},
        # v2.9: IP PRINTER MODE - the hub IS a network printer (any PC
        # or phone can add it at /ipp/print or the RAW port) and every
        # incoming job prints to the configured destination
        "ip_printer_mode": bool((CFG.get("share_lan") or
            CFG.get("ipp_printer", True)) and (
            CFG.get("ipp_printer", True) or
            int(CFG.get("raw_printer_port") or 0) > 0)),
        # v3.2.2: IPP URLS + discovery state for the LAN tab chips
        "ipp_urls": {"ipp": lan_share_url("ipp"),
                     "http": "http://%s:%d/ipp/print"
                             % (lan_ip(), int(CFG.get("port", 9235))),
                     "std": ("http://%s:%d/ipp/print"
                             % (lan_ip(), int(CFG.get("ipp_standard_port") or 0)))
                            if int(CFG.get("ipp_standard_port") or 0) > 0 else None},
        "ipp_mdns_up": bool(_mdns_state.get("sock") is not None),
        "ipp_std": {"up": bool(_IPP631_STATE.get("up")),
                    "port": int(_IPP631_STATE.get("port") or 0),
                    "err": _IPP631_STATE.get("err") or "",
                    # v3.3.0 BUG 2: the bound sockets (IPv4 + IPv6)
                    "addrs": list(_IPP631_BINDS)},
        "lan_active": bool(BOUND_LAN),
        "lan_url": ("http://%s:%d" % (lan_ip(), CFG["port"]))
                   if CFG.get("share_lan") else None,
        # v2.8.2: diagnostics for "the other PC cannot connect"
        "lan_ip": lan_ip(),
        # v3.2.9 BUG 3: EVERY interface IP - the LAN panel lists them all
        # so each PC/phone can pick its own reachable address
        "lan_ips": list_lan_ips()[:8],
        # v3.3.0 BUG 2: the IPv6 half + the sockets the LAN listener is
        # actually bound on (one per interface, v4 + v6)
        "lan_ips6": list_lan_ips6()[:6],
        "lan_bind_addrs": list(_LAN_BINDS),
        "lan_bind_ip": (_LAN_BINDS[0] if _LAN_BINDS else None),
        "firewall_ok": firewall_rule_ok(),
        "hostname": socket.gethostname(),
        "success_rate": st.get("success_rate") if st else None,
        "printers_ready": ready,
        "audit": bool(CFG.get("audit_enabled", True)),
        "loopback_lock_exempt": True,
        "extension": ext_health(),
        "v2": True,
    }
    with _HEALTH_LOCK:
        _HEALTH_SNAP["t"] = time.time()
        _HEALTH_SNAP["data"] = snap
    return snap


def health_snapshot():
    """Instant read for the /health route. Falls back to a one-shot
    synchronous build (cheap: cached printer data only) when the
    refresher has not filled the snapshot yet."""
    with _HEALTH_LOCK:
        snap = _HEALTH_SNAP["data"]
    if snap:
        return dict(snap)
    try:
        return dict(build_health_snapshot())
    except Exception:
        return {"ok": True, "app": APP_NAME, "version": VERSION,
                "branding": BRANDING, "starting": True, "v2": True}


def start_health_refresher():
    """Background thread keeping the /health snapshot warm (every 3 s)."""
    if _HEALTH_THREAD[0] and _HEALTH_THREAD[0].is_alive():
        return

    def _loop():
        while True:
            try:
                build_health_snapshot()
            except Exception:
                pass
            # v2.8.2: keep the LAN listener aligned with the config AND
            # with DHCP IP changes - no user action, no restart ever.
            try:
                lan_listen_ensure()
            except Exception:
                pass
            # v2.9.0: same for the RAW JetDirect printer port (9100).
            try:
                raw_listen_ensure()
            except Exception:
                pass
            # v3.2.2: standard-port IPP mirror (631) - Android's Default
            # Print Service tries port 631 first on manual add.
            try:
                ipp631_listen_ensure()
            except Exception:
                pass
            # v3.0.8: AirPrint-grade mDNS discovery (phones/PCs see the
            # printer by itself when LAN sharing is on).
            try:
                ipp_mdns_ensure()
            except Exception:
                pass
            time.sleep(3.0)

    t = threading.Thread(target=_loop, daemon=True,
                         name="advprint-health")
    _HEALTH_THREAD[0] = t
    t.start()

def printer_ready(name=""):
    """'ready' | 'offline' | 'paper-out' | 'error' | 'unknown'.
    Empty name = the OS default printer. Unknown printers never block."""
    st = printers_status()
    target = name or CFG["printer"] or default_printer() or ""
    if not target:
        return "unknown"
    if target in st:
        return st[target]
    # CUPS may report the class/member differently - stay permissive
    return "unknown"

def printer_group_members(name):
    """Members of a configured printer group (ordered fallback list)."""
    groups = CFG.get("printer_groups") or {}
    members = groups.get(name)
    if isinstance(members, dict):
        members = members.get("members")
    return [str(m) for m in members] if isinstance(members, list) else []

def pick_group_printer(name):
    """First group member whose status is not offline/paper-out/error.
    Falls back to the first member when nothing is confirmed ready."""
    members = printer_group_members(name)
    if not members:
        return None
    st = printers_status()
    for m in members:
        if st.get(m, "unknown") not in ("offline", "paper-out", "error"):
            return m
    return members[0]

def _glob_to_regex(pat):
    """Simple glob -> regex ('*' matches anything; used for origins/hosts)."""
    rx = "".join(".*" if c == "*" else re.escape(c) for c in (pat or ""))
    return re.compile("^" + rx + "$", re.I)

def origin_allowed(origin):
    """allowed_origins: [] = allow all (old behaviour). Patterns like
    '*.htncr.org' or 'https://intranet.example.com' otherwise."""
    rules = CFG.get("allowed_origins") or []
    if not rules:
        return True
    if not origin:
        return False
    o = str(origin).strip().lower()
    for pat in rules:
        p = str(pat).strip().lower()
        if p and _glob_to_regex(p if "://" in p else "*://" + p).match(o):
            return True
    return False

def host_allowed(host):
    """pdf_url allowlist (overrides the private-IP block)."""
    host = (host or "").lower()
    for pat in (CFG.get("pdf_url_allowed_hosts") or []):
        p = str(pat).strip().lower()
        if p and (_glob_to_regex(p).match(host) or p == host):
            return True
    return False

def pdf_url_guard(url):
    """SSRF guard for pdf_url (v2.0):
      * file://, ftp:// and every non-http(s) scheme are blocked
      * hosts resolving to private/loopback/link-local addresses are
        blocked unless listed in pdf_url_allowed_hosts (config.json)
    Raises ValueError with a friendly message; returns the url when OK."""
    try:
        p = urlparse(str(url))
    except Exception:
        raise ValueError("pdf_url is not a valid URL")
    if p.scheme not in ("http", "https"):
        raise ValueError(
            "pdf_url scheme '%s:' is blocked - only http/https URLs are"
            " allowed (file:// and ftp:// are disabled for security)" % p.scheme)
    host = p.hostname or ""
    if not host:
        raise ValueError("pdf_url has no host name")
    if host_allowed(host):
        return url
    ip_raw = host.strip("[]")
    try:
        candidates = [ipaddress.ip_address(ip_raw)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                       proto=socket.IPPROTO_TCP)
            candidates = [ipaddress.ip_address(i[4][0]) for i in infos]
        except socket.gaierror as e:
            raise ValueError("pdf_url host '%s' cannot be resolved (%s)" % (host, e))
    for ip in candidates:
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(
                "pdf_url host '%s' resolves to a private/local address"
                " (%s) - blocked. Add it to 'pdf_url_allowed_hosts' in"
                " config.json if this is intentional." % (host, ip))
    return url

# ------------------------------------------------------------
# Minimal PDF builders (pure Python): text receipts/pages + JPEG images
# ------------------------------------------------------------
def _pdf_escape(s):
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

def jpeg_size(data):
    """Scan JPEG markers for SOF0..SO F15 to get (width, height). Pure stdlib."""
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h = (data[i + 5] << 8) | data[i + 6]
            w = (data[i + 7] << 8) | data[i + 8]
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD9:
            i += 2
            continue
        seg_len = (data[i + 2] << 8) | data[i + 3]
        i += 2 + seg_len
    return None, None

def image_pdf_bytes(jpeg, title="screenshot", paper="a4", landscape=None):
    """
    Wrap a JPEG image into a single-page PDF (pure Python, DCTDecode).
    paper="a4" (default) or "thermal" (80mm roll, image scaled to width).
    landscape=True forces A4 landscape for wide screenshots.
    Returns (pdf_bytes, suggested_filename).
    """
    MM = 72 / 25.4
    w, h = jpeg_size(jpeg)
    if not w or not h:
        raise ValueError("not a valid JPEG image (sender must use image/jpeg)")
    landscape = bool(landscape) if landscape is not None else (w > h)
    if paper == "thermal":
        PW, PH = 80 * MM, 297 * MM
        margin = 2 * MM
    elif landscape:
        PW, PH = 297 * MM, 210 * MM
        margin = 8 * MM
    else:
        PW, PH = 210 * MM, 297 * MM
        margin = 10 * MM
    avail_w, avail_h = PW - 2 * margin, PH - 2 * margin
    scale = min(avail_w / w, avail_h / h)
    dw, dh = w * scale, h * scale
    x, y = (PW - dw) / 2.0, (PH - dh) / 2.0

    img_id, page_id, cont_id, pages_id, cat_id = 1, 2, 3, 4, 5
    content = ("q %.2f 0 0 %.2f %.2f %.2f cm /Im0 Do Q" % (dw, dh, x, y)).encode()
    objs = {
        img_id: ("<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                 "/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                 "/Length %d >>\nstream\n" % (w, h, len(jpeg))).encode()
                 + jpeg + b"\nendstream",
        cont_id: b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        page_id: ("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.1f %.1f] "
                  "/Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
                  % (pages_id, PW, PH, img_id, cont_id)).encode(),
        pages_id: ("<< /Type /Pages /Kids [%d 0 R] /Count 1 >>" % page_id).encode(),
        cat_id: ("<< /Type /Catalog /Pages %d 0 R >>" % pages_id).encode(),
    }
    out = bytearray()
    out += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = {}
    for idx in sorted(objs):
        offsets[idx] = len(out)
        out += ("%d 0 obj\n" % idx).encode() + objs[idx] + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % (cat_id + 1)).encode()
    out += b"0000000000 65535 f \n"
    for idx in sorted(objs):
        out += ("%010d 00000 n \n" % offsets[idx]).encode()
    out += ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (cat_id + 1, cat_id, xref)).encode()
    fname = "%s-%s.pdf" % (title or "image", datetime.now().strftime("%Y%m%d%H%M%S"))
    return bytes(out), sanitize_fname(fname, maxlen=80, extra="-._",
                                      fallback="download.pdf")

def pdf_page_count(data):
    """Count /Type /Page objects in a PDF (v2.1). Best effort - None when
    the structure is not recognisable."""
    try:
        if not data or data[:5] != b"%PDF-":
            return None
        return len(re.findall(rb"/Type\s*/Page\b", data)) or None
    except Exception:
        return None

def text_needs_browser(text):
    """True when text cannot be represented in Latin-1 (Bangla, Hindi,
    CJK ...) - the builtin receipt renderer would replace it with '?'."""
    try:
        str(text or "").encode("latin-1")
        return False
    except UnicodeEncodeError:
        return True

def inject_page_css(html_src, margin_mm=None, scale_pct=None, landscape=None):
    """v2.1: apply margin/scale/orientation to html/page_url jobs by
    injecting @page + zoom CSS at render time (headless Chrome)."""
    css = ""
    if margin_mm not in (None, ""):
        css += "@page{margin:%smm !important;}" % re.sub(r"[^0-9.]", "", str(margin_mm))
    if landscape in (True, "1", "true", "yes", "on"):
        css += "@page{size:A4 landscape !important;}"
    if scale_pct not in (None, ""):
        css += "body{zoom:%s%%;}" % re.sub(r"[^0-9.]", "", str(scale_pct))
    if not css:
        return html_src
    style = "<style data-advprint=\"v21\">%s</style>" % css
    m = re.search(r"<head[^>]*>", html_src or "", re.I)
    if m:
        i = m.end()
        return html_src[:i] + style + html_src[i:]
    return style + (html_src or "")

def printer_capabilities(name=""):
    """v2.1: what THIS printer + backend actually supports - drives the
    extension/API so only supported options are offered. Windows uses the
    SumatraPDF backend (driver-level extras noted); Linux queries CUPS
    `lpoptions -p <name> -l` for the REAL capability list."""
    if IS_WIN:
        return {
            "ok": True, "backend": "sumatra", "printer": name or None,
            "pages": {"type": "ranges", "odd_even": True,
                      "example": "1-3,5 | odd | even"},
            "copies": {"min": 1, "max": 50},
            "duplex": ["simplex", "duplex", "duplexlong", "duplexshort"],
            "paper": ["A4", "A5", "A3", "Letter", "Legal", "Tabloid",
                      "Executive", "Folio", "Statement"],
            "tray": None,          # SumatraPDF cannot select a tray
            "per_sheet": None,     # n-up needs CUPS
            "quality": {"presets": ["draft", "normal", "high"],
                        "dpi": None,
                        "note": "the Windows driver decides the real"
                                " DPI - both presets and dpi values are"
                                " accepted and logged"},
            "scale": ["noscale", "shrinkfit"],
            "margins": "render",   # honoured when the hub renders the PDF
            "orientation": ["portrait", "landscape"],
            "color": ["color", "monochrome"],
            "note": "SumatraPDF backend - tray / n-up / DPI follow the"
                    " Windows driver settings",
        }
    caps = {"ok": True, "backend": "cups", "printer": name or None,
            "pages": {"type": "ranges", "odd_even": True},
            "copies": {"min": 1, "max": 50},
            "duplex": ["one-sided", "two-sided-long-edge",
                       "two-sided-short-edge"],
            "per_sheet": [1, 2, 4, 6, 9, 16],
            "quality": {"presets": ["draft", "normal", "high"],
                        "dpi": [300, 600, 1200]},
            "margins": "render", "orientation": ["portrait", "landscape"],
            "tray": [], "paper": [], "raw_options": {}}
    try:
        exe = shutil.which("lpoptions")
        if exe:
            cmd = [exe] + (["-p", name] if name else []) + ["-l"]
            out = subprocess.run(cmd, capture_output=True, timeout=10
                                 ).stdout.decode("utf-8", "replace")
            for line in out.splitlines():
                m = re.match(r"^([A-Za-z0-9_\-]+)/[^:]*:\s*(.*)$", line)
                if not m:
                    continue
                key = m.group(1)
                choices = [c.rstrip("*") for c in m.group(2).split()]
                caps["raw_options"][key] = choices
                if key in ("media", "PageSize"):
                    caps["paper"] = choices[:24]
                elif key in ("InputSlot", "MediaSource"):
                    caps["tray"] = choices[:12]
                elif key == "Duplex":
                    caps["duplex"] = choices
                elif key == "number-up":
                    nums = [int(v) for v in choices if v.isdigit()]
                    if nums:
                        caps["per_sheet"] = nums
                elif key == "print-quality":
                    caps["quality"]["presets"] = [
                        c for c in choices
                        if c in ("draft", "normal", "high")] or choices[:6]
                elif key in ("Resolution", "printer-resolution"):
                    dpis = [int(re.sub(r"[^0-9]", "", c))
                            for c in choices if re.search(r"\d{3,4}", c)]
                    if dpis:
                        caps["quality"]["dpi"] = sorted(set(dpis))[:8]
                elif key == "page-set":
                    caps["pages"] = {"type": "ranges",
                                     "odd_even": bool(set(choices) &
                                                      {"odd", "even"})}
    except Exception as e:
        caps["error"] = str(e)[:120]
    return caps

def thermal_pdf_bytes(text, title="receipt", paper="thermal",
                      margin_mm=None, scale_pct=None, landscape=None):
    """
    Build a minimal PDF from plain text (pure Python, no dependencies):
      paper="thermal" -> 80mm receipt roll, Courier 8pt
      paper="a4"      -> 210x297mm page, Courier 11pt
    v2.1 options: margin_mm (page margins), scale_pct (25-400%),
    landscape (a4 only). Absent parameters keep the exact old layout.
    Markers: #big <line> = large bold heading, |center| <line> = centered.
    Returns (bytes, filename).
    """
    MM = 72 / 25.4
    if paper == "a4":
        W = 210 * MM
        PAGE_H = 297 * MM
        font_pt, lead, max_cols = 11, 5.5 * MM, 95
        big_pt, big_lead = 18, 9 * MM
        top_mm, bottom_pad = 15, 40
    else:
        W = 80 * MM                        # 80mm paper
        PAGE_H = None                      # auto height (receipt roll)
        font_pt, lead, max_cols = 8, 3.6 * MM, 40
        big_pt, big_lead = 13, 6.5 * MM
        top_mm, bottom_pad = 8, 10
    LM = 4 * MM
    # v2.1: optional landscape / scale / margin overrides (old layout when
    # the parameters are absent)
    if landscape in (True, "1", "true", "yes", "on") and paper == "a4":
        W, PAGE_H = PAGE_H, W
    if scale_pct not in (None, "", 1, "1", "100", 100):
        try:
            sc = max(25, min(400, int(float(scale_pct)))) / 100.0
            font_pt, lead = font_pt * sc, lead * sc
            big_pt, big_lead = big_pt * sc, big_lead * sc
            max_cols = max(10, int(max_cols / sc))
        except (TypeError, ValueError):
            pass
    if margin_mm not in (None, ""):
        try:
            LM = max(0.0, min(40.0, float(margin_mm))) * MM
        except (TypeError, ValueError):
            pass
    lines = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith("#big"):
            lines.append(("big", raw[4:].strip()))
        elif raw.startswith("|center|"):
            lines.append(("center", raw[8:].strip()))
        else:
            lines.append(("normal", raw))
    # paginate every N lines
    per_page = 70 if PAGE_H is None else int((PAGE_H - 2 * top_mm * MM) / lead) - 2
    pages, cur = [], []
    for ln in lines:
        cur.append(ln)
        if len(cur) >= per_page:
            pages.append(cur); cur = []
    pages.append(cur or [("normal", "")])

    out = bytearray()
    n = len(pages)
    objs = {}

    def add_obj(idx, body):
        objs[idx] = body

    # fonts: F1 Courier, F2 Courier-Bold
    add_obj(1, b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    add_obj(2, b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold >>")

    page_ids = []
    next_id = 3
    content_ids = []
    for pi, page in enumerate(pages):
        H = pages_h(page) if PAGE_H is None else PAGE_H
        stream = []
        y = H - top_mm * MM
        for style, txt in page:
            if style == "big":
                stream.append("BT /F2 %d Tf %d %.1f Td (%s) Tj ET" %
                              (big_pt, int(LM), y, _pdf_escape(txt[:max_cols])))
                y -= big_lead
            else:
                t = txt[:max_cols]
                if style == "center":
                    pad = max(0, (max_cols - len(t)) // 2)
                    t = " " * pad + t
                stream.append("BT /F1 %d Tf %d %.1f Td (%s) Tj ET" %
                              (font_pt, int(LM), y, _pdf_escape(t)))
                y -= lead
        data = ("\n".join(stream)).encode("latin-1", "replace")
        cid = next_id; next_id += 1
        content_ids.append(cid)
        add_obj(cid, b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")

    pages_id = next_id; next_id += 1
    for pi in range(n):
        pid = next_id; next_id += 1
        page_ids.append(pid)
        H = pages_h(pages[pi]) if PAGE_H is None else PAGE_H
        add_obj(pid,
                ("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.1f %.1f] "
                 "/Resources << /Font << /F1 1 0 R /F2 2 0 R >> >> "
                 "/Contents %d 0 R >>" % (pages_id, W, H, content_ids[pi])
                 ).encode())
    kids = " ".join("%d 0 R" % p for p in page_ids)
    add_obj(pages_id,
            ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n)).encode())
    cat_id = next_id; next_id += 1
    add_obj(cat_id, ("<< /Type /Catalog /Pages %d 0 R >>" % pages_id).encode())

    # serialize
    out += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = {}
    for idx in sorted(objs):
        offsets[idx] = len(out)
        out += ("%d 0 obj\n" % idx).encode() + objs[idx] + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % (next_id)).encode()
    out += b"0000000000 65535 f \n"
    for idx in sorted(objs):
        out += ("%010d 00000 n \n" % offsets[idx]).encode()
    out += ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (next_id, cat_id, xref)).encode()
    fname = "%s-%s.pdf" % (title or "receipt", datetime.now().strftime("%Y%m%d%H%M%S"))
    return bytes(out), sanitize_fname(fname, maxlen=80, extra="-._",
                                      fallback="download.pdf")

def pages_h(page_lines):
    MM = 72 / 25.4
    h = 10 * MM + len(page_lines) * 3.6 * MM
    return max(60 * MM, h)

# ------------------------------------------------------------
# HTML / web page -> PDF via headless Chrome or Edge (zero pip)
# ------------------------------------------------------------
# v2.9.1 (audit H2/P4 fix): at most TWO headless-browser renders run at
# the same time - each render is a full Chrome instance (~200 MB RAM) and
# an unbounded number of concurrent /print html|page_url requests used to
# spawn one each (memory exhaustion, and two requests even shared the same
# temp file name -> one request could read/delete the other's PDF).
_BROWSER_SEM = threading.BoundedSemaphore(2)

def _kill_proc_tree(proc):
    """v2.9.1 (audit P4 fix): kill a timed-out headless browser AND its
    grandchild renderer processes. subprocess.run(timeout=) only kills the
    direct child, so Chrome's renderer children used to linger forever.
    """
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=HIDE)
        else:
            try:
                os.killpg(os.getpgid(proc.pid), 15)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

def html_to_pdf_bytes(source, is_url=True, title="page"):
    """
    Render an HTML string or a URL to PDF using headless Chrome/Edge.
    Uses a throwaway profile dir so it never fights the user's browser.
    Returns (pdf_bytes, suggested_filename).
    v2.9.1 (audit H2/P4 fix): every render gets its OWN temp directory for
    the output PDF and the local HTML copy (the old code named them by
    PID only in the SHARED temp dir, so concurrent requests overwrote /
    deleted each other's files), builds file: URLs with pathlib (no more
    hand-built "file:///" strings that broke on paths with spaces or '#'),
    runs under a 2-slot semaphore, and kills the whole process tree on
    timeout.
    """
    exe = find_browser()
    if not exe:
        raise RuntimeError(
            "No Chrome/Edge found for page printing. Install Google Chrome"
            " (or print PDFs instead - SumatraPDF handles those directly).")
    workdir = tempfile.mkdtemp(prefix="advprint-page-")
    profile = os.path.join(workdir, "profile")
    out_path = os.path.join(workdir, "out.pdf")
    with _BROWSER_SEM:
        try:
            if is_url:
                target = source
            else:
                html_path = os.path.join(workdir, "page.html")
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(source)
                target = pathlib.Path(html_path).as_uri()

            def attempt(headless_flag):
                cmd = [exe, headless_flag, "--disable-gpu", "--no-first-run",
                       "--disable-extensions", "--user-data-dir=" + profile,
                       "--no-pdf-header-footer",
                       "--print-to-pdf=" + out_path, target]
                if IS_WIN:
                    return subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE,
                                            creationflags=HIDE)
                # POSIX: own process group so a timeout can kill every
                # renderer grandchild with one killpg
                return subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        start_new_session=True)

            pdf = None
            try:
                for flag in ("--headless=new", "--headless"):
                    proc = attempt(flag)
                    try:
                        proc.communicate(timeout=120)
                    except subprocess.TimeoutExpired:
                        _kill_proc_tree(proc)      # v2.9.1 P4: tree kill
                        proc.communicate(timeout=10)
                        continue
                    if os.path.exists(out_path) and \
                            os.path.getsize(out_path) > 100:
                        with open(out_path, "rb") as f:
                            pdf = f.read()
                        break
                if not pdf or not pdf[:5].startswith(b"%PDF"):
                    raise RuntimeError(
                        "headless browser did not produce a PDF (page blocked,"
                        " login required, or browser too old)")
            finally:
                # the browser is gone - clean the whole work dir (no more
                # out_path deletes racing a concurrent reader: this dir is
                # private to this call)
                shutil.rmtree(workdir, ignore_errors=True)
            fname = "%s-%s.pdf" % (title or "page",
                                   datetime.now().strftime("%Y%m%d%H%M%S"))
            return pdf, sanitize_fname(fname, maxlen=80, extra="-._",
                                       fallback="page.pdf")
        except BaseException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

# ------------------------------------------------------------
# Silent printing back-end (cancellable: keeps a handle to the process)
# ------------------------------------------------------------
_CURRENT_LOCK = threading.Lock()
_CURRENT = {"id": None, "proc": None}

def fix_printer_name(name, st):
    """v2.6.8: self-heal a printer name that cannot match any installed
    printer but maps to one after a SAFE repair. Real-world case (live
    install, job #2): the stored name was 'Canon LBP6230/6240Canon
    LBP6230/6240' - the exact name twice in a row (typed/pasted twice
    or saved from a stale field). Instead of killing the job with
    "printer not found", the doubled name is collapsed to its half and
    printed. Also matches when only case / double spaces differ.
    Returns (fixed_name_or_None, note_or_None). Never raises."""
    if not name or not st:
        return None, None
    if name in st:
        return name, None
    half = len(name) // 2
    if (half > 0 and name[:half] == name[half:]
            and name[:half].strip()):
        cand = name[:half].strip()
        if cand in st:
            return cand, "name was doubled - corrected"
    norm = re.sub(r"\s+", "", name).lower()
    if norm:
        for p in st:
            if p and re.sub(r"\s+", "", str(p)).lower() == norm:
                return p, "matched ignoring case/spaces"
    return None, None


# ------------------------------------------------------------
# v2.9: print DESTINATION routing - ANY printer.
# Every PC or phone can add THIS hub as their IP printer; the hub then
# delivers every incoming job to the destination configured here: the
# OS default printer, ANY installed printer ("selected"), or an
# upstream IP printer (a real network printer at IP:port - JetDirect
# RAW or IPP Print-Job). A per-job printer name always wins.
# ------------------------------------------------------------


def resolve_dest(explicit=""):
    """WHERE does a print job go? Returns ("local", name) - name ""
    means the OS default printer - or ("ip", (host, port, proto)).
    A per-job printer name always wins and is always local."""
    if explicit:
        return "local", str(explicit)
    mode = str(CFG.get("dest_mode") or "")
    if mode not in ("default", "selected", "ip"):
        # legacy behaviour: an empty dest_mode follows the old chain -
        # the selected printer when one is set, otherwise the default
        mode = "selected" if CFG.get("printer") else "default"
    if mode == "ip":
        host = str(CFG.get("ip_printer_host") or "").strip()
        if host:
            proto = str(CFG.get("ip_printer_proto") or "raw").lower()
            if proto not in ("raw", "ipp"):
                proto = "raw"
            try:
                port = int(CFG.get("ip_printer_port") or 0)
            except (TypeError, ValueError):
                port = 0
            if port <= 0:
                port = 631 if proto == "ipp" else 9100
            return "ip", (host, port, proto)
        return "local", ""          # not configured - OS default
    if mode == "selected":
        return "local", CFG.get("printer") or ""
    return "local", ""              # OS default printer


def dest_display():
    """Human name of the configured destination (no per-job override)."""
    kind, dest = resolve_dest()
    if kind == "ip":
        return "IP printer %s:%d (%s)" % (dest[0], dest[1], dest[2])
    return dest or "(default printer)"


def ip_printer_probe(dest, timeout=3.0):
    """TCP reachability of the upstream IP printer: 'ready'|'offline'."""
    host, port, _proto = dest
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        try:
            s.close()
        except OSError:
            pass
        return "ready"
    except Exception:
        return "offline"


def _raw_client_send(host, port, data):
    """JetDirect: connect, stream the bytes, drain the silent ACK."""
    s = socket.create_connection((host, port), timeout=20)
    try:
        view = memoryview(data)
        while view:
            sent = s.send(view[:65536])
            if sent <= 0:
                raise RuntimeError("IP printer closed the connection")
            view = view[sent:]
        try:                        # most printers never answer - just wait
            s.settimeout(4)
            while s.recv(4096):
                pass
        except (socket.timeout, OSError):
            pass
    finally:
        try:
            s.close()
        except OSError:
            pass


def _ipp_client_print(host, port, data, title, docformat, copies=1):
    """Minimal IPP 1.1 Print-Job CLIENT for the upstream IP printer.
    Raises RuntimeError on any transport or IPP error."""
    path = "/ipp/print"
    rid = (int(time.time() * 1000) & 0x7FFFFFFF) or 1
    opg = _ipp_group(0x01, [
        _ipp_attr(0x47, "attributes-charset", "utf-8"),
        _ipp_attr(0x48, "attributes-natural-language", "en"),
        _ipp_attr(0x45, "printer-uri", "ipp://%s:%d%s" % (host, port, path)),
        _ipp_attr(0x42, "requesting-user-name", "AdvPrint Pro"),
        _ipp_attr(0x42, "job-name", (title or "AdvPrint Pro job")[:80]),
        _ipp_attr(0x49, "document-format", docformat),
    ])
    jobg = b""
    if copies > 1:                  # copies is a job-template integer
        jobg = _ipp_group(0x02, [
            _ipp_attr(0x21, "copies",
                      int(copies).to_bytes(4, "big", signed=True))])
    body = (bytes((1, 1)) + (0x0002).to_bytes(2, "big") +
            int(rid).to_bytes(4, "big") + opg + jobg + b"\x03" + data)
    req = urllib.request.Request(
        "http://%s:%d%s" % (host, port, path), data=body, method="POST",
        headers={"Content-Type": IPP_MIME,
                 "User-Agent": "AdvPrint-Pro/%s" % VERSION})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            code = r.getcode()
            payload = r.read(65536)
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            payload = e.read(65536)
        except Exception:
            payload = b""
    except Exception as e:
        raise RuntimeError("IP printer %s:%d unreachable: %s"
                           % (host, port, e))
    if code != 200:
        raise RuntimeError("IP printer answered HTTP %s" % code)
    if len(payload) >= 4 and payload[0] == 1:
        st = int.from_bytes(payload[2:4], "big")
        if st >= 0x0400:            # client-/server-error band
            raise RuntimeError("IP printer IPP error 0x%04X" % st)
    else:
        log("[IPP] printer reply not IPP-shaped (HTTP %s) -"
            " assuming accepted" % code)


def ip_printer_send(data, title, dest=None, docformat="application/pdf",
                    copies=1):
    """Push bytes to the upstream IP printer (dest_mode "ip").
    Returns a display name like 'IP printer 192.168.1.50:9100 (raw)'."""
    if dest is None:
        kind, dest = resolve_dest()
        if kind != "ip":
            raise RuntimeError("no IP printer destination is configured"
                               " (Settings > Print destination)")
    host, port, proto = dest
    host = str(host).strip()
    if not host:
        raise RuntimeError("IP printer host is empty")
    copies = max(1, min(int(copies or 1), 50))
    if proto == "ipp":
        _ipp_client_print(host, port, data, title, docformat, copies)
    else:
        for _i in range(copies):
            _raw_client_send(host, port, data)
    return "IP printer %s:%d (%s)" % (host, port, proto)


def _print_file_to_ip(path, _kind, dest, copies, job_id=None):
    """Print a stored file (PDF) straight to the upstream IP printer.
    Modern network printers accept PDF directly on the JetDirect port;
    IPP receives it as application/pdf."""
    title = os.path.splitext(os.path.basename(path))[0] or "AdvPrint Pro job"
    with open(path, "rb") as f:
        data = f.read()
    name = ip_printer_send(data, title, dest,
                           docformat="application/pdf", copies=copies)
    if job_id:
        log("[PRINT] job #%d -> %s (%s)" % (job_id, name, title))
    else:
        log("[PRINT] -> %s (%s)" % (name, title))
    return name


def print_file(path, kind="a4", printer="", copies=1, job_id=None,
               pages=None, duplex=None, paper_size=None, tray=None,
               per_sheet=None, quality=None, dpi=None):
    """
    Print a PDF file SILENTLY (no dialog) to the given printer
    or the OS default. Raises RuntimeError with a friendly message.
    The spawned process is registered so /jobs/{id}/cancel can kill it.
    v2.0 options: pages ("1-3,5"), duplex ("simplex"|"duplex"|"long"|"short"),
    paper_size ("A4", "Letter"...), tray ("Tray2" - CUPS only; SumatraPDF
    cannot select trays, logged as a warning).
    v2.2 options: quality accepts BOTH presets (draft|normal|high) AND a
    DPI number - quality="dpi:600" (the /print endpoint normalises
    "600", "600dpi" or dpi=600 into that form before calling us).
    """
    copies = max(1, min(int(copies or 1), 50))
    # v2.9: destination routing - ANY printer. A per-job name always
    # wins; otherwise the hub destination (default / selected / IP).
    dkind, dtarget = resolve_dest(printer)
    if dkind == "ip":
        return _print_file_to_ip(path, kind, dtarget, copies, job_id)
    target = dtarget or default_printer() or ""

    def register(proc):
        with _CURRENT_LOCK:
            _CURRENT["id"] = job_id
            _CURRENT["proc"] = proc
        return proc

    def duplex_flag():
        d = (duplex or "").lower()
        if d in ("long", "long-edge", "twosided-long-edge"):
            return "duplexlong"
        if d in ("short", "short-edge", "twosided-short-edge"):
            return "duplexshort"
        if d in ("1", "true", "on", "yes", "duplex"):
            return "duplex"
        if d in ("0", "false", "off", "no", "one", "simplex"):
            return "simplex"
        return None

    try:
        # v2.6.7: two guards that turn silent backend deaths into
        # CLEAR error messages (the "print backend exit 1: " case):
        # v2.6.8: before refusing an unknown name, try to SELF-HEAL it
        # (doubled name 'XxX' -> 'X', case/space differences) so the job
        # prints instead of dying on a typo in a stored setting.
        if target and not is_virtual_pdf_printer(target):
            st = printers_status()
            if st and target not in st:
                fixed, note = fix_printer_name(target, st)
                if fixed:
                    log("[PRINT] printer '%s' corrected to '%s' (%s)"
                        " - printing on the real printer"
                        % (target, fixed, note))
                    if job_id:
                        try:
                            db_update(job_id, printer=fixed)
                            db_audit("printer.corrected", job_id=job_id,
                                     printer=fixed,
                                     details="was '%s' (%s)"
                                             % (target, note))
                        except Exception:
                            pass
                    target = fixed
                else:
                    raise RuntimeError(
                        "printer '%s' not found on this PC (installed: %s)"
                        " - pick the exact name in Settings > Printer"
                        % (target, ", ".join(sorted(st))[:150]))
        if os.path.isfile(path):
            _wait_readable(path)  # AV lock window - see _read_locked
        if IS_WIN:
            sumatra = find_sumatra()
            if not sumatra:
                raise RuntimeError(
                    "SumatraPDF not found. Install it first: %s" % SUMATRA_HINT)
            parts = []
            if pages:
                ps = str(pages).strip().lower()
                if ps in ("odd", "even"):
                    parts.append(ps)      # SumatraPDF supports odd/even
                else:
                    parts.append(re.sub(r"[^0-9,\-]", "", str(pages)))
            df = duplex_flag()
            if df:
                parts.append(df)
            if paper_size:
                # v2.9.1 (audit L1 fix): parentheses - "paper=%s" % x or "A4"
                # parsed as ("paper=%s" % x) or "A4", so the A4 fallback was
                # dead and a value like "А4" (non-ASCII) sanitized to an
                # empty "paper=" flag that SumatraPDF rejected.
                parts.append("paper=%s" % (re.sub(r"[^A-Za-z0-9]", "",
                                                  str(paper_size)) or "A4"))
            if tray:
                log("[PRINT] note: SumatraPDF cannot select a paper tray"
                    " ('%s' ignored) - tray printing needs CUPS" % tray)
            if per_sheet and int(per_sheet) > 1:
                log("[PRINT] note: per-sheet %s is not supported by the"
                    " SumatraPDF backend (needs CUPS) - ignored" % per_sheet)
            if quality:
                if str(quality).startswith("dpi:"):
                    log("[PRINT] note: DPI '%s' is controlled by the Windows"
                        " driver - SumatraPDF has no resolution switch;"
                        " the driver default is used" % quality)
                else:
                    log("[PRINT] note: quality '%s' is controlled by the"
                        " Windows driver - SumatraPDF has no quality switch"
                        " (draft/normal/high maps to the driver default)"
                        % quality)
            parts.append("noscale" if kind in ("thermal", "image-thermal")
                         else "shrinkfit")
            if copies > 1:
                parts.append("%dx" % copies)
            cmd = [sumatra, "-silent", "-exit-when-done",
                   "-print-settings", ",".join(parts)]
            if target:
                cmd += ["-print-to", target]
            else:
                # v2.9.1 (audit L2 fix): without an explicit target Sumatra
                # used to open its GUI and sit there until the 180 s timeout
                # killed it - now the OS default printer is used.
                cmd += ["-print-to-default"]
            cmd.append(path)
            if CFG.get("debug"):
                log("[DEBUG] command: %s" % " ".join(cmd))
            log("[PRINT] SumatraPDF -> %s (%s, %d copy/copies%s%s)"
                % (target or "OS default", kind, copies,
                   (", pages %s" % pages) if pages else "",
                   (", %s" % df) if df else ""))
            proc = register(subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE,
                                             creationflags=HIDE))
        else:
            if shutil.which("lp") is None:
                raise RuntimeError("CUPS 'lp' command not found."
                                   " Install cups / cups-client first.")
            cmd = ["lp"]
            if target:
                cmd += ["-d", target]
            if copies > 1:
                cmd += ["-n", str(copies)]
            if pages:
                ps = str(pages).strip().lower()
                if ps in ("odd", "even"):
                    cmd += ["-o", "page-set=%s" % ps]
                else:
                    cmd += ["-o", "page-ranges=%s" %
                            re.sub(r"[^0-9,\-]", "", str(pages))]
            if per_sheet and int(per_sheet) > 1:
                cmd += ["-o", "number-up=%d" % max(1, min(16, int(per_sheet)))]
            if quality:
                qv = {"draft": "3", "normal": "4",
                      "high": "5"}.get(str(quality).lower())
                if qv:
                    cmd += ["-o", "print-quality=%s" % qv]
                elif str(quality).startswith("dpi:"):
                    # v2.2: numeric DPI -> CUPS printer-resolution
                    cmd += ["-o", "printer-resolution=%sdpi" %
                            str(quality).split(":")[1]]
            df = duplex_flag()
            if df:
                cmd += ["-o", {"duplex": "two-sided-long-edge",
                               "duplexlong": "two-sided-long-edge",
                               "duplexshort": "two-sided-short-edge",
                               "simplex": "one-sided"}[df]]
            media = ",".join(x for x in (paper_size, tray) if x)
            if media:
                cmd += ["-o", "media=%s" % re.sub(r"[^A-Za-z0-9,]", "", media)]
            cmd += ["-o", "fit-to-page" if kind in ("a4", "image") else "noscale",
                    path]
            if CFG.get("debug"):
                log("[DEBUG] command: %s" % " ".join(cmd))
            log("[PRINT] lp -> %s (%s, %d copy/copies%s%s%s)"
                % (target or "OS default", kind, copies,
                   (", pages %s" % pages) if pages else "",
                   (", %s" % df) if df else "",
                   (", media %s" % media) if media else ""))
            proc = register(subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE))
        try:
            out, err = proc.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError("printer did not respond within 180 s")
        if proc.returncode != 0:
            # v2.6.7: SumatraPDF reports problems on STDOUT and often
            # leaves stderr EMPTY - "print backend exit 1: " with no
            # reason. Collect both streams so the history shows WHY.
            detail = ((err or b"") + (out or b"")).decode(
                "utf-8", "ignore").strip()[:300]
            if not detail:
                detail = ("backend gave no output - usually the printer"
                          " name does not exist or the file was locked"
                          " by another program")
            raise RuntimeError("print backend exit %d: %s"
                               % (proc.returncode, detail))
    finally:
        with _CURRENT_LOCK:
            if _CURRENT["id"] == job_id:
                _CURRENT["id"] = None
                _CURRENT["proc"] = None
    return target or "OS default"

def cancel_current_print():
    """Kill the in-flight print process, if any. Returns job id or None."""
    with _CURRENT_LOCK:
        proc = _CURRENT["proc"]
        jid = _CURRENT["id"]
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        _CURRENT["proc"] = None
        _CURRENT["id"] = None
    return jid

# ------------------------------------------------------------
# Print queue: DB-driven worker with global pause
# v2.0: priority (urgent first), exponential retry with backoff,
# dead-letter after the final attempt, HOLD while the printer is
# offline / out of paper, scheduled prints, printer-group fallback
# and optional forwarding to a live peer hub.
# ------------------------------------------------------------
RESUME_EVENT = threading.Event()   # set = queue running, clear = paused
RESUME_EVENT.set()
_UNHOLD_TS = [0.0]                 # periodic printer re-check throttle

def _job_print_args(job):
    """(file bytes path, kind, printer) with printer-group resolution."""
    printer = job.get("printer") or ""
    if printer_group_members(printer):
        member = pick_group_printer(printer)
        if member:
            log("[GROUP] '%s' -> member '%s'" % (printer, member))
            printer = member
    return job.get("file_path"), job.get("kind", "a4"), printer

def _hold_job(job, why):
    db_update(job["id"], status="held", held_reason=why[:200], error=None)
    db_audit("print.held", job_id=job["id"], printer=job.get("printer"),
             details=why[:200])
    log("[HOLD] job #%d: %s" % (job["id"], why))

def _read_locked(path, attempts=5, first_delay=0.2):
    """v2.6.7: read a freshly written file that a real-time antivirus,
    search indexer or sync filter may hold EXCLUSIVELY for a few hundred
    milliseconds right after it is closed. On Windows that answers the
    read with [Errno 13] Permission denied - one unlucky read used to
    kill the whole job ("save-as-PDF failed: [Errno 13] Permission
    denied" in the history). Retries with backoff (~4 s in total); the
    lock window always clears. Missing files raise immediately."""
    last = None
    for i in range(attempts):
        try:
            with open(path, "rb") as f:
                return f.read()
        except PermissionError as e:
            last = e
        except OSError:
            raise                        # not found / bad path - no retry
        if i < attempts - 1:
            time.sleep(first_delay * (2 ** i))    # 0.2 0.4 0.8 1.6 s
    raise last


_ATOMIC_SEQ = itertools.count(1)

def _write_atomic(path, data, attempts=4):
    """v2.6.7: write bytes via a .part file + os.replace so readers never
    see a partial PDF, retrying while the destination folder is briefly
    locked (antivirus / OneDrive / sync tools).
    v3.2.9 BUG 2: the temp name was path+pid only - when TWO PCs (or
    two jobs) wrote the same target in the same second, both threads
    shared ONE .part file: the first os.replace() moved it away and the
    second thread died with [Errno 2] -> the job was marked failed.
    Every call now gets a unique temp name; same-target writers can
    never collide again."""
    tmp = "%s.part%d.%d" % (path, os.getpid(), next(_ATOMIC_SEQ))
    last = None
    for i in range(attempts):
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)        # atomic on the same volume
            return
        except PermissionError as e:
            last = e
            try:
                os.unlink(tmp)
            except OSError:
                pass
            if i < attempts - 1:
                time.sleep(0.2 * (2 ** i))
    raise last


def _wait_readable(path, attempts=5, first_delay=0.2):
    """v2.6.7: probe-read a job file before handing it to a print
    backend (SumatraPDF / lp), so an antivirus lock window cannot make
    the BACKEND fail either (SumatraPDF would just exit 1 silently)."""
    _read_locked(path, attempts=attempts, first_delay=first_delay)


_VPDF_LOCK = threading.Lock()          # v3.2.9: serialize virtual-PDF saves


def _save_virtual_pdf(job):
    """v2.5: write the job's PDF straight into the save-as-PDF folder
    (Downloads\\AdvPrint by default). Status 'saved' - no Save-As dialog,
    works even with NO physical printer installed.
    v3.2.9 BUG 2: the free-name check + write are serialized - with one
    hub serving MANY PCs, two jobs for the virtual PDF printer in the
    same second picked the SAME filename and one of them failed to
    save. Under the lock the second job simply gets a -2 name."""
    jid = job["id"]
    try:
        fdir = default_file_dir()
        os.makedirs(fdir, exist_ok=True)
        safe = sanitize_fname(job.get("title") or "document", maxlen=50,
                              extra="-_ ", fallback="document")
        base = "%s-%s" % (safe.replace(" ", "_"),
                          datetime.now().strftime("%Y%m%d-%H%M%S"))
        data = _read_locked(job["file_path"])
        with _VPDF_LOCK:
            fpath = os.path.join(fdir, base + ".pdf")
            n = 1
            while os.path.exists(fpath):
                fpath = os.path.join(fdir, "%s-%d.pdf" % (base, n)); n += 1
            # v2.6.7: the fresh PDF is sometimes held exclusively for a
            # few 100 ms by the real-time antivirus / indexer right
            # after the hub writes it. The plain copyfile read then
            # failed instantly with "[Errno 13] Permission denied" and
            # the job was lost. Retry-read + atomic write ride out the
            # lock window instead.
            _write_atomic(fpath, data)
        db_update(jid, status="saved", printer="File (PDF)",
                  held_reason=None, error=None, file_path=fpath)
        db_audit("print.saved", job_id=jid,
                 printer=job.get("printer") or "File (PDF)",
                 details="virtual printer -> PDF saved to %s" % fpath)
        log("[FILE] job #%d: virtual printer -> saved %s" % (jid, fpath))
    except Exception as e:
        msg = str(e)
        if isinstance(e, PermissionError):
            msg = ("PDF still locked by antivirus / another program"
                   " after retries - Retry from the history; if it"
                   " repeats add '%s' to your antivirus exclusions (%s)"
                   % (CFG["data_dir"], e))
        db_update(jid, status="failed",
                  error=("save-as-PDF failed: %s" % msg)[:500])
        log("[FAIL] job #%d save-as-PDF: %s" % (jid, msg))

def _release_held_jobs():
    """Every ~15 s: printers that came back online release their held jobs."""
    if time.time() - _UNHOLD_TS[0] < 15:
        return
    _UNHOLD_TS[0] = time.time()
    held = db_list(limit=200, status="held")
    if not held:
        return
    st = printers_status()
    for j in held:
        target = j.get("printer") or CFG["printer"] or default_printer() or ""
        cur = st.get(target, "unknown") if target else "unknown"
        if cur not in ("offline", "paper-out", "error"):
            db_update(j["id"], status="queued", held_reason=None,
                      error=None, next_attempt_at=None)
            db_audit("print.requeued", job_id=j["id"], printer=target,
                     details="printer back %s - job released" % (cur or "ready"))
            log("[RELEASE] job #%d back in queue (%s ready)" % (j["id"], target))

def _retry_or_dead(job, err):
    """Exponential retry: requeue with backoff, or dead-letter after the
    final attempt (visible in the dead-letter list, retryable).
    v2.9.1 (audit M3/M7 fixes): (1) a missing/deleted job row no longer
    crashes the caller with KeyError - it just logs. (2) RAW (ESC/POS /
    ZPL) jobs and 'printer did not respond' timeouts do NOT auto-retry:
    a raw stream may already be partially printed, and a timeout usually
    means the paper IS in the tray - silently reprinting duplicated
    medical receipts and labels. Both land in the dead-letter list where
    one click reprints them on purpose."""
    if not job or not job.get("id"):
        log("[RETRY] job row vanished - nothing to update (%s)"
            % str(err)[:120])
        return
    attempts = int(job.get("attempts") or 0) + 1
    maxr = max(0, int(CFG.get("max_retries", 2)))
    msg = str(err)
    no_auto_retry = (str(job.get("kind") or "") == "raw"
                     or "did not respond within" in msg
                     or "timed out" in msg.lower())
    if attempts <= maxr and not no_auto_retry:
        delay = int(CFG.get("retry_base_seconds", 30)) * (2 ** (attempts - 1))
        nxt = (datetime.now() + timedelta(seconds=delay)).isoformat(timespec="seconds")
        db_update(job["id"], status="queued", attempts=attempts,
                  next_attempt_at=nxt,
                  error="retry %d/%d in %ds: %s" % (attempts, maxr, delay,
                                                    str(err)[:120]))
        db_audit("print.requeued", job_id=job["id"],
                 printer=job.get("printer"),
                 details="retry %d/%d in %ds - %s" % (attempts, maxr, delay,
                                                      str(err)[:120]))
        log("[RETRY] job #%d failed (%s) - attempt %d/%d in %ds"
            % (job["id"], str(err)[:80], attempts, maxr, delay))
    else:
        db_update(job["id"], status="dead", attempts=attempts,
                  error=str(err)[:500])
        db_audit("job.dead", job_id=job["id"], printer=job.get("printer"),
                 details=str(err)[:200])
        log("[DEAD] job #%d moved to the dead-letter list: %s"
            % (job["id"], str(err)[:120]))

# v2.9.1 (audit M4 fix): remember the last failed probe per peer so a dead
# peer is not hammered with 3×3 s timeouts on EVERY queued job - one fail
# puts the peer on a 60 s skip list.
_PEER_FAIL_TS = {}

def _try_peer_forward(job, force=False):
    """Offline/unknown printer + peer_forwarding on: send the document to
    the first ALIVE peer hub that has the printer. Dead peers are skipped
    (with a 60 s negative cache so a down peer costs at most one probe
    cycle). Returns True when the job was handed over.
    v3.3.2 SHARE SEND MODE: force=True (share_send switch) forwards to
    the PAIRED LAN PC (the 'lan-pc' peer_hubs entry) even when the
    printer is fine here and peer_forwarding is off - that is the
    switch's whole contract. The paired PC must still actually HAVE the
    requested printer (otherwise the job would come out of the wrong
    device there); when it does not, the job prints locally like before.
    The 60 s dead-peer skip list applies in both modes."""
    if not force and not CFG.get("peer_forwarding"):
        return False
    if force:
        # Share Send forwards ONLY to the paired LAN PC card entry
        peers = [p for p in (CFG.get("peer_hubs") or [])
                 if str(p.get("name") or "") == LAN_PC_PEER_NAME] or \
            (CFG.get("peer_hubs") or [])
    else:
        peers = CFG.get("peer_hubs") or []
    peers = _dedupe_peer_hubs(peers)   # v3.3.3: same-URL entries never
                                       # get the job twice
    if not peers:
        return False
    try:
        with open(job["file_path"], "rb") as f:
            data = f.read()
    except OSError:
        return False
    want = job.get("printer") or ""
    for peer in peers:
        url = (peer.get("url") or "").rstrip("/")
        if not url:
            continue
        if time.time() - _PEER_FAIL_TS.get(url, 0) < 60:
            continue                       # recently dead - skip this cycle
        headers = {"X-AdvPrint-Token": peer.get("token") or "",
                   "User-Agent": "AdvPrintPro/%s" % VERSION}
        try:
            req = urllib.request.Request(url + "/health", headers=headers)
            with urllib.request.urlopen(req, timeout=3) as r:
                if not (r.getcode() == 200):
                    continue
            if want:
                req = urllib.request.Request(url + "/printers", headers=headers)
                with urllib.request.urlopen(req, timeout=3) as r:
                    names = [p.get("name") for p in
                             json.loads(r.read().decode("utf-8", "replace"))
                             .get("printers", [])]
                if want not in names:
                    if force:
                        # Share Send: the paired PC does not have this
                        # printer - say so once and print locally
                        log("[SHARE-SEND] peer %s has no printer %r - "
                            "job #%d prints locally" % (url, want,
                                                        job["id"]))
                        db_audit("peer.share_send.skipped",
                                 job_id=job["id"], printer=want,
                                 details="paired PC %s has no printer %s"
                                         % (url, want))
                    continue     # peer alive but no such printer - next peer
            payload = json.dumps({
                "pdf_base64": base64.b64encode(data).decode("ascii"),
                "title": job.get("title") or "peer",
                "printer": want, "copies": job.get("copies") or 1,
                "kind": job.get("kind") or "a4",
                "source": ("share-send:%s" if force else "peer:%s")
                          % CFG["port"]}).encode()
            req = urllib.request.Request(
                url + "/print", data=payload, headers=dict(
                    headers, **{"Content-Type": "application/json"}))
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read().decode("utf-8", "replace"))
            if resp.get("ok"):
                _PEER_FAIL_TS.pop(url, None)
                db_update(job["id"], status="forwarded", peer=url,
                          error=None,
                          held_reason=None,
                          duration_ms=None)
                db_audit("job.forwarded", job_id=job["id"], printer=want,
                         details="%sforwarded to peer %s (job %s)" %
                                 ("share-send: " if force else "",
                                  url, resp.get("job_id")))
                log("[PEER] job #%d %sforwarded to %s (remote job %s)"
                    % (job["id"], "share-send " if force else "",
                       url, resp.get("job_id")))
                return True
        except Exception as e:
            _PEER_FAIL_TS[url] = time.time()   # v2.9.1 M4: 60 s skip list
            log("[PEER] %s skipped (%s)" % (url, str(e)[:80]))
            continue
    return False

def _execute_job(job, t0):
    """Print one job - the status-aware group pick goes first, the other
    group members follow as real fallback, then history + audit + retry.
    v3.3.2 SHARE SEND MODE: when the Connections LAN PC switch is ON,
    EVERY job goes to the paired PC first (its /print with the same
    printer name); the job prints locally only when the share hand-off
    did not happen (no pairing / peer down / peer lacks the printer)."""
    # v3.3.2 SHARE SEND MODE - all jobs to the paired LAN PC
    if CFG.get("share_send"):
        try:
            if _try_peer_forward(job, force=True):
                return True
        except Exception as e:
            log("[SHARE-SEND] forward failed (%s) - printing locally"
                % str(e)[:80])
    path, kind, printer = _job_print_args(job)
    members = printer_group_members(job.get("printer") or "")
    if members:
        first = pick_group_printer(job.get("printer") or "") or members[0]
        candidates = [first] + [m for m in members if m != first]
    else:
        candidates = [printer] if printer else [""]
    last_err = None
    for cand in candidates:
        # v2.9.1 (audit M3 fix): the canceled check now runs BEFORE every
        # group member attempt. The old code checked only AFTER the whole
        # loop, so Cancel on a group job still fired every remaining
        # member - and a successful print unconditionally overwrote
        # status "canceled" with "printed".
        if (db_get(job["id"]) or {}).get("status") == "canceled":
            log("[CANCELED] job #%d killed before '%s'"
                % (job["id"], cand or "default"))
            return False
        try:
            target = print_file(path, kind, cand, job.get("copies") or 1,
                                job_id=job["id"], pages=job.get("pages"),
                                duplex=job.get("duplex"),
                                paper_size=job.get("paper_size"),
                                tray=job.get("tray"),
                                per_sheet=job.get("per_sheet"),
                                quality=job.get("quality"))

            ms = int((time.time() - t0) * 1000)
            # v2.9.1 (audit M3 fix): a print that FINISHED after the user
            # pressed Cancel keeps the canceled verdict - no silent
            # overwrite of the user's decision
            if (db_get(job["id"]) or {}).get("status") == "canceled":
                log("[CANCELED] job #%d was canceled while printing"
                    % job["id"])
                return False
            db_update(job["id"], status="printed", error=None,
                      duration_ms=ms, printer=target)
            db_audit("print.completed", job_id=job["id"], printer=target,
                     actor=job.get("source"), site=job.get("site"),
                     ip=job.get("origin_ip"), doc_hash=job.get("content_hash"),
                     details="%d ms" % ms)
            log("[OK] job #%d printed on %s in %d ms" % (job["id"], target, ms))
            return True
        except Exception as e:
            last_err = e
            log("[FAIL] job #%d on '%s': %s" % (job["id"], cand or "default", e))
            if (db_get(job["id"]) or {}).get("status") == "canceled":
                log("[CANCELED] job #%d killed mid-print" % job["id"])
                return False
    latest = db_get(job["id"]) or {}
    if latest.get("status") == "canceled":
        log("[CANCELED] job #%d killed mid-print" % job["id"])
        return False
    db_update(job["id"], status="failed", error=str(last_err)[:500])
    db_audit("print.failed", job_id=job["id"], printer=job.get("printer"),
             details=str(last_err)[:200])
    _retry_or_dead(job, last_err)
    return False

def worker():
    # recover jobs stuck in 'printing' from a previous crash/restart
    try:
        for j in db_list(limit=200, status="printing"):
            log("[RECOVER] job #%d was interrupted -> requeued" % j["id"])
            db_update(j["id"], status="queued",
                      error="requeued after hub restart")
    except Exception as e:
        log("[WORKER] recovery pass failed: %s" % e)
    while True:
        # v2.2.1: the loop body is exception-proof. Earlier a single
        # unexpected error (driver glitch, DB hiccup, OSError) killed this
        # thread and EVERY later job stayed 'queued' forever while the hub
        # still answered OK - the "extension shows OK but nothing prints"
        # report. Now the error is logged + audited and the loop keeps
        # running; the watchdog below respawns the thread even if this
        # last line of defence is somehow bypassed.
        job = None                  # v2.2.1: for the crash handler below
        try:
            RESUME_EVENT.wait()                 # pause support
            try:
                db_promote_scheduled()          # scheduled prints -> queue
                _release_held_jobs()            # offline printers -> back up
            except Exception:
                pass
            job = db_next_queued()
            if not job:
                # v2.9.1 (audit P1 fix): sleep on the wake event instead of
                # a 0.35 s poll - enqueue_print sets the event the moment a
                # job lands, so latency DROPS while idle CPU does too. The
                # 2 s timeout keeps the scheduled-promote / hold-release
                # passes running for jobs that nobody wakes the queue for.
                _WORKER_WAKE.wait(2.0)
                _WORKER_WAKE.clear()
                continue
            if CFG.get("debug"):
                log("[DEBUG] worker picked job #%d (%s) for printer %r"
                    % (job["id"], job.get("kind"), job.get("printer")))
            # v2.9.1: observable busy flag - the queue-reset logic (and
            # tests) can wait for the worker to be genuinely idle instead
            # of guessing from DB statuses.
            _WORKER_BUSY[0] = True
            try:
                # v2.9: resolve the destination ONCE - ANY printer: per-job
                # name, OS default, selected printer or the upstream IP printer.
                dkind, dest = resolve_dest(job.get("printer") or "")
                # HOLD: printer offline / out of paper / error state (raw jobs
                # skip the status check - receipt printers rarely report state)
                if CFG.get("hold_offline", True) and job.get("kind") != "raw":
                    if dkind == "ip":
                        # the destination is the network printer - probe ITS
                        # reachability, never a local printer's state
                        pstat = ip_printer_probe(dest)
                    else:
                        pstat = printer_ready(job.get("printer") or "")
                    if pstat in ("offline", "paper-out", "error"):
                        if dkind == "ip":
                            why = ("IP printer %s:%d is unreachable - job held"
                                   " until it answers ('Print now' overrides"
                                   " this, or switch off 'Printer status hold'"
                                   " in the dashboard)" % (dest[0], dest[1]))
                        else:
                            why = ("printer '%s' is %s - job held until it"
                                   " is ready ('Print now' overrides this,"
                                   " or switch off 'Printer status hold' in"
                                   " the dashboard)"
                                   % (job.get("printer") or "default", pstat))
                        _hold_job(job, why)
                        continue
                    # v2.9.1 (audit M4 fix): forward to a peer ONLY when the
                    # printer is REALLY down (offline / paper-out / error).
                    # The old condition was pstat != "ready", and
                    # printer_ready() answers "unknown" for group names and
                    # printers with no reported state - so perfectly healthy
                    # jobs were silently shipped to a peer PC. "unknown" now
                    # prints locally (and holds only for offline/error).
                    if dkind != "ip" and \
                            pstat in ("offline", "paper-out", "error") and \
                            _try_peer_forward(job):
                        continue
                # v2.5: virtual PDF printer (Microsoft Print to PDF etc.) ->
                # save the PDF directly - no renderer, no Save-As dialog.
                # v2.9: NEVER applies when the destination is the IP printer
                # (the remote printer decides what to do with the bytes).
                if job.get("kind") != "raw" and dkind != "ip" and \
                        is_virtual_pdf_printer(
                            job.get("printer") or CFG.get("printer")
                            or default_printer() or ""):
                    _save_virtual_pdf(job)
                    continue
                t0 = time.time()
                db_update(job["id"], status="printing", error=None)
                if job.get("kind") == "raw":
                    try:
                        with open(job["file_path"], "rb") as f:
                            data = f.read()
                        target = print_raw(data, job.get("printer") or "",
                                           job_id=job["id"],
                                           title=job.get("title") or "raw")
                        ms = int((time.time() - t0) * 1000)
                        db_update(job["id"], status="printed", error=None,
                                  duration_ms=ms, printer=target)
                        db_audit("print.completed", job_id=job["id"],
                                 printer=target, actor=job.get("source"),
                                 site=job.get("site"), ip=job.get("origin_ip"),
                                 doc_hash=job.get("content_hash"))
                        log("[OK] job #%d raw-printed on %s"
                            % (job["id"], target))
                    except Exception as e:
                        latest = db_get(job["id"]) or {}
                        if latest.get("status") == "canceled":
                            log("[CANCELED] job #%d killed mid-print"
                                % job["id"])
                        else:
                            db_update(job["id"], status="failed",
                                      error=str(e)[:500])
                            db_audit("print.failed", job_id=job["id"],
                                     printer=job.get("printer"),
                                     details=str(e)[:200])
                            _retry_or_dead(job, e)
                else:
                    _execute_job(job, t0)
                finally_guard(job)
            finally:
                _WORKER_BUSY[0] = False
        except SystemExit:
            raise
        except Exception as e:                  # v2.2.1: NEVER let it die
            try:
                log("[WORKER] unexpected error (queue keeps running): %s"
                    % e)
                db_audit("worker.error", details=str(e)[:300])
                # do not leave the job as 'printing' forever
                if job is not None:
                    latest = db_get(job["id"]) or {}
                    if latest.get("status") == "printing":
                        db_update(job["id"], status="failed",
                                  error="hub error: %s" % str(e)[:300])
                        db_audit("print.failed", job_id=job["id"],
                                 printer=job.get("printer"),
                                 details="worker crash: %s" % str(e)[:200])
                        _retry_or_dead(job, e)
            except Exception:
                pass
            time.sleep(1.0)

_WORKER_THREAD = [None]

def _spawn_worker():
    t = threading.Thread(target=worker, daemon=True, name="advprint-worker")
    _WORKER_THREAD[0] = t
    t.start()

def _worker_watchdog():
    """v2.2.1 safety net: if the print worker thread ever disappears
    (native crash, OOM kill, unforeseen bug), respawn it within 30 s so
    the queue can never stall silently again."""
    while True:
        time.sleep(30)
        try:
            t = _WORKER_THREAD[0]
            if t is None or not t.is_alive():
                log("[WORKER] worker thread is GONE - restarting it "
                    "(jobs left in 'queued' will now print)")
                try:
                    db_audit("worker.restarted",
                             details="worker thread was dead - respawned "
                                     "by watchdog")
                except Exception:
                    pass
                _spawn_worker()
        except Exception:
            pass

def finally_guard(job):
    # keep the file for reprint (unless keep_files is off)
    if not CFG["keep_files"] and job.get("file_path") \
            and os.path.exists(job["file_path"]) \
            and (db_get(job["id"]) or {}).get("status") in (
                "printed", "failed", "dead", "canceled"):
        try:
            os.unlink(job["file_path"])
        except OSError:
            pass

def start_worker():
    _spawn_worker()
    threading.Thread(target=_worker_watchdog, daemon=True,
                     name="advprint-watchdog").start()

# v2.9.1 (audit H1 fix): serializes the dedupe check -> file save -> DB
# insert inside enqueue_print so two concurrent identical submissions
# can never both pass the duplicate check and print twice.
_ENQ_LOCK = threading.Lock()
# v2.9.1 (audit P1 fix): the FIFO worker sleeps on this event instead of
# polling every 0.35 s. enqueue_print sets it the moment a job lands; the
# worker also wakes on a 2 s timeout so scheduled-promote / hold-release
# passes still run periodically.
_WORKER_WAKE = threading.Event()
# v2.9.1: True while the worker is processing a job (claim -> finally).
# The queue-reset logic and tests wait on this instead of guessing.
_WORKER_BUSY = [False]

def sanitize_fname(text, maxlen=50, extra="-_ ", fallback="job"):
    """v2.9.1 (audit L3 fix): keep letters/numbers/marks from ANY language
    when building file names. The old ``c.isalnum()`` check dropped Bengali
    combining marks (category Mc/Mn are not alnum), so 'রিপোর্ট-Lab'
    became the mangled 'রপরট-Lab'. unicodedata.category() keeps every
    letter (L*), number (N*) AND combining mark (M*) - 'রিপোর্ট-Lab'
    survives intact - while still removing path separators, control
    characters and symbols that are unsafe in a filename."""
    out = []
    for c in (text or ""):
        if unicodedata.category(c)[0] in "LNM" or c in extra:
            out.append(c)
    return ("".join(out)[:maxlen].strip() or fallback)

def save_job_file(kind, title, data, ext="pdf"):
    """Write payload bytes into the jobs dir; returns full path.
    v2.9.1 (audit H1 fix): the name now carries a 6-hex random suffix and
    is created EXCLUSIVELY ('xb'), so two jobs printed in the same second
    from the same process can never overwrite each other's payload -
    the old name (title-second-pid) collided on a double-click and the
    duplicate-deletion path then removed the ORIGINAL job's file."""
    ensure_dirs()
    safe = sanitize_fname(title, maxlen=40, extra="-_ ", fallback="job")
    jobs_dir = os.path.join(CFG["data_dir"], "jobs")
    for _attempt in range(20):
        fname = "%s-%s-%s-%s.%s" % (safe.replace(" ", "_"),
                                    datetime.now().strftime("%Y%m%d%H%M%S"),
                                    os.getpid(),
                                    secrets.token_hex(3), ext)
        path = os.path.join(jobs_dir, fname)
        try:
            f = open(path, "xb")            # exclusive create: never overwrite
        except FileExistsError:
            continue                        # freak collision - pick a new name
        break
    else:
        raise RuntimeError("cannot create a unique job file in %s" % jobs_dir)
    with f:
        f.write(data)
    return path

def enqueue_print(kind, title, data, printer="", copies=1,
                  source="api", origin_ip="-", queue_mode=True,
                  priority=5, run_at=None, site=None, dedupe=True,
                  content_hash=None, **extra):
    """Save file + insert DB row. Returns (job_id, duplicate_job_id_or_None).
    queue_mode=True  -> FIFO worker prints the job in order (pause respected)
    queue_mode=False -> Queue Mode OFF: job prints IMMEDIATELY in its own
                        thread, pause has no effect. Tracked like always.
    dedupe=False     -> skip duplicate blocking for this one submission."""
    ext = "prn" if kind == "raw" else "pdf"
    if not content_hash:
        content_hash = hashlib.sha256(data).hexdigest()
    dedupe_key = hashlib.sha256(("%s|%s|%s|%s" % (title, printer, kind,
                                                  content_hash))
                                .encode()).hexdigest()[:32]
    # v2.6.9 FIX (double print): decide direct-vs-queued BEFORE the DB row
    # exists. Queue Mode OFF used to insert the row as 'queued' and only
    # flip it to 'printing' AFTER the slow printer-status probe (hundreds
    # of ms on Windows) - the FIFO worker polls every 0.35 s and could
    # claim the job inside that window, so BOTH paths sent the same job to
    # the printer: two Sumatra runs, two '[OK] job #N' lines and the page
    # physically printed twice. Now the row is BORN in its final state
    # ('printing' for direct jobs) - the worker, which only claims
    # 'queued' rows, can never see a direct job.
    status = "queued"
    next_at = None
    if run_at:
        status = "scheduled"
        next_at = run_at
    direct = (status == "queued" and not queue_mode)
    auto_hold = None
    # v2.3 INSTANT PRINT fallback: queue mode OFF + the printer is NOT
    # active -> auto-queue the job instead of firing a doomed direct
    # print. The FIFO worker then handles it like any other job (with
    # hold_offline it even waits for the printer to come back and
    # prints automatically). Raw/ESC-POS jobs skip the check - receipt
    # printers rarely report a usable status.
    if direct and CFG.get("instant_auto_queue", True) and kind != "raw":
        # v2.9: probe the REAL destination - with dest_mode "ip" that is
        # the upstream network printer, never the local default
        _dkind, _dtarget = resolve_dest(printer)
        pstat = (ip_printer_probe(_dtarget) if _dkind == "ip"
                 else printer_ready(printer))
        if pstat in ("offline", "paper-out", "error"):
            auto_hold = pstat
            direct = False
    if direct:
        status = "printing"        # row never visible as 'queued'
    # v2.9.1 (audit H1 fix): the duplicate check runs BEFORE the payload is
    # written (the old order wrote the file first, then deleted it on the
    # duplicate path - and because two same-second submissions shared ONE
    # file path, deleting the duplicate's file destroyed the ORIGINAL
    # job's payload). The process-wide _ENQ_LOCK spans check -> file ->
    # insert, so two concurrent identical requests can no longer both
    # pass the dedupe and print twice. The slow printer probe runs BEFORE
    # the lock so instant submissions never serialize behind each other.
    with _ENQ_LOCK:
        dup = None
        if dedupe:
            dup = db_find_duplicate(dedupe_key,
                                    int(CFG.get("dedupe_minutes", 5)))
        if dup:
            log("[DEDUPE] job identical to #%d (%s) from %s - blocked"
                % (dup["id"], dup["title"], dup["created_at"]))
            return dup["id"], dup["id"]
        path = save_job_file(kind, title, data, ext=ext)
        job_id = db_add(kind, title, printer, copies, path, source,
                        origin_ip,
                        status=status,
                        priority=max(1, min(9, int(priority or 5))),
                        run_at=run_at, next_attempt_at=next_at, site=site,
                        dedupe_key=dedupe_key, content_hash=content_hash,
                        **extra)
    # v2.9.1 (audit P1 fix): wake the FIFO worker the moment a job lands
    # instead of letting it poll every 0.35 s (lower latency, less CPU).
    _WORKER_WAKE.set()
    if status == "scheduled":
        log("[SCHEDULE] job #%d scheduled for %s" % (job_id, run_at))
        return job_id, None
    if queue_mode:
        log("[QUEUE] job #%d queued (p%s, %s, %s) from %s"
            % (job_id, priority, kind, title or "untitled", source))
        return job_id, None
    if auto_hold:
        db_audit("print.auto_queued", job_id=job_id, printer=printer,
                 details="instant print: printer '%s' is %s - job"
                         " auto-queued (prints when it is ready)"
                         % (printer or "default", auto_hold))
        log("[INSTANT] job #%d auto-queued - printer '%s' is %s"
            % (job_id, printer or "default", auto_hold))
        return job_id, None
    threading.Thread(target=_print_now,
                     args=(job_id, path, kind, printer, copies),
                     daemon=True, name="advprint-direct-%d" % job_id).start()
    log("[DIRECT] job #%d printing immediately (queue mode OFF)"
        % job_id)
    return job_id, None


def _print_now(job_id, path, kind, printer, copies):
    """Immediate-execution thread for queue:false jobs (bypasses FIFO)."""
    t0 = time.time()
    if CFG.get("debug"):
        log("[DEBUG] instant print job #%d -> %r (kind=%s, copies=%d)"
            % (job_id, printer or "OS default", kind, copies))
    try:
        # v2.9.1 (audit M3 fix): instant jobs now resolve PRINTER GROUPS
        # exactly like the FIFO worker does. _print_now never touched
        # printer_group_members/pick_group_printer, so a group name in
        # Queue Mode OFF went straight to the print backend and died with
        # "printer not found".
        if printer_group_members(printer):
            member = pick_group_printer(printer)
            if member:
                log("[GROUP] instant job #%d '%s' -> member '%s'"
                    % (job_id, printer, member))
                printer = member
        dkind, dtarget = resolve_dest(printer)   # v2.9: ANY printer
        if kind == "raw":
            with open(path, "rb") as f:
                data = f.read()
            target = print_raw(data, printer, job_id=job_id)
        elif dkind == "ip":
            target = _print_file_to_ip(path, kind, dtarget, copies, job_id)
        elif is_virtual_pdf_printer(
                printer or CFG.get("printer") or default_printer() or ""):
            # v2.6.7: virtual PDF printers (Microsoft Print to PDF /
            # File (PDF)) take the save path here TOO - Queue Mode OFF
            # used to hand "File (PDF)" straight to the print backend,
            # and SumatraPDF exited 1 (no such Windows printer).
            jrow = dict(db_get(job_id) or {})
            jrow.setdefault("id", job_id)
            jrow.setdefault("file_path", path)
            _save_virtual_pdf(jrow)
            return
        else:
            jrow = db_get(job_id) or {}
            target = print_file(path, kind, printer, copies, job_id=job_id,
                                pages=jrow.get("pages"),
                                duplex=jrow.get("duplex"),
                                paper_size=jrow.get("paper_size"),
                                tray=jrow.get("tray"),
                                per_sheet=jrow.get("per_sheet"),
                                quality=jrow.get("quality"))
        ms = int((time.time() - t0) * 1000)
        db_update(job_id, status="printed", error=None,
                  duration_ms=ms, printer=target)
        db_audit("print.completed", job_id=job_id, printer=target)
        log("[OK] job #%d printed on %s in %d ms (direct)"
            % (job_id, target, ms))
    except Exception as e:
        latest = db_get(job_id) or {}
        if latest.get("status") == "canceled":
            log("[CANCELED] job #%d killed mid-print" % job_id)
        else:
            db_update(job_id, status="failed", error=str(e)[:500])
            db_audit("print.failed", job_id=job_id, printer=printer,
                     details=str(e)[:200])
            _retry_or_dead(db_get(job_id) or {}, e)
    finally:
        # v2.6.9: keep the file when the job was requeued for retry -
        # deleting it here used to make the retry fail with "file no
        # longer stored". Only clean up terminal states, like the FIFO
        # worker's finally_guard does.
        if not CFG["keep_files"] and path and os.path.exists(path) \
                and (db_get(job_id) or {}).get("status") in (
                    "printed", "failed", "dead", "canceled", "saved"):
            try:
                os.unlink(path)
            except OSError:
                pass

def save_file_job(kind, title, data, source="api", origin_ip="-"):
    """Destination 'file': write the PDF into the user's file folder
    (~/Downloads/AdvPrint by default) - NO paper, NO queue. The job is
    stored with status 'saved' and can be re-printed later."""
    fdir = default_file_dir()
    try:
        os.makedirs(fdir, exist_ok=True)
    except OSError:
        fdir = os.path.join(CFG["data_dir"], "files")
        os.makedirs(fdir, exist_ok=True)
    safe = sanitize_fname(title or "document", maxlen=50, extra="-_ ",
                          fallback="document")
    fname = "%s-%s.pdf" % (safe.replace(" ", "_"),
                           datetime.now().strftime("%Y%m%d-%H%M%S"))
    path = os.path.join(fdir, fname)
    n = 1
    while os.path.exists(path):            # never overwrite an earlier file
        path = os.path.join(fdir, "%s-%d.pdf" % (fname[:-4], n))
        n += 1
    _write_atomic(path, data)   # v2.6.7: ride out AV/OneDrive lock windows
    job_id = db_add(kind, title, "File (PDF)", 1, path, source, origin_ip,
                    status="saved")
    log("[FILE] job #%d saved -> %s" % (job_id, path))
    return job_id, path

# ------------------------------------------------------------
# Auto-start at logon (visible, user-controllable)
# ------------------------------------------------------------
# v1.5.0: Windows autostart is a NORMAL STARTUP-APP SHORTCUT
# ("shell:startup\AdvPrint Pro.lnk"), NOT a hidden scheduled task.
# Why it matters: Startup-folder apps appear in Task Manager ->
# "Startup apps" with name + icon, so the user can Enable/Disable
# them with one click; scheduled tasks are invisible there, which
# made the hub look uninstallable. The tray icon menu and the
# /autostart API below toggle the same shortcut.

def hub_dir():
    return os.path.dirname(os.path.abspath(__file__))


def launcher_exe():
    """Windows: prefer a sibling AdvPrintPro.exe (renamed pythonw.exe) so
    Task Manager shows 'AdvPrintPro' instead of 'pythonw'. Non-Windows:
    the current interpreter."""
    if IS_WIN:
        cand = os.path.join(os.path.dirname(sys.executable), "AdvPrintPro.exe")
        if os.path.isfile(cand):
            return cand
    return sys.executable


def hub_icon_path():
    cand = os.path.join(hub_dir(), "advprint.ico")
    return cand if os.path.isfile(cand) else ""


def autostart_path():
    """File that controls 'start at logon' (None = unsupported platform)."""
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(base, "Microsoft", "Windows", "Start Menu",
                            "Programs", "Startup", "AdvPrint Pro.lnk")
    if sys.platform.startswith("linux"):
        cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config")
        return os.path.join(cfg, "autostart", "advprint-pro.desktop")
    return None


def autostart_enabled():
    p = autostart_path()
    return bool(p) and os.path.isfile(p)


def _legacy_task_remove():
    """Old releases (v1.2 - v1.4) registered a SCHEDULED TASK named
    'AdvPrint Pro'. Delete it so the hub never starts twice."""
    if not IS_WIN:
        return
    try:
        subprocess.run(["schtasks", "/Delete", "/TN", "AdvPrint Pro", "/F"],
                       creationflags=HIDE, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15)
    except Exception:
        pass


def autostart_set(enable):
    """Enable/disable the logon autostart. Returns the resulting state."""
    p = autostart_path()
    if not p:
        return False
    _legacy_task_remove()
    try:
        if IS_WIN:
            if enable:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                lnk = p.replace("'", "''")
                exe = launcher_exe().replace("'", "''")
                hubpy = os.path.join(hub_dir(), "advprint.py").replace("'", "''")
                ico = (hub_icon_path() or "").replace("'", "''")
                wd = hub_dir().replace("'", "''")
                ps = ("$w=New-Object -ComObject WScript.Shell;"
                      "$s=$w.CreateShortcut('{lnk}');"
                      "$s.TargetPath='{exe}';"
                      "$s.Arguments='\"{hubpy}\" serve';"
                      "$s.IconLocation='{ico},0';"
                      "$s.WorkingDirectory='{wd}';"
                      "$s.Description='AdvPrint Pro silent print hub';"
                      "$s.Save()").format(lnk=lnk, exe=exe, hubpy=hubpy,
                                          ico=ico, wd=wd)
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy",
                     "Bypass", "-Command", ps],
                    creationflags=HIDE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=30)
                ok = (r.returncode == 0 and os.path.isfile(p))
                log("[AUTOSTART] %s (%s)" %
                    ("enabled - Startup shortcut created" if ok
                     else "FAILED to create Startup shortcut",
                     p))
                return ok
            if os.path.isfile(p):
                os.remove(p)
            log("[AUTOSTART] disabled - Startup shortcut removed")
            return False
        # Linux: XDG autostart desktop entry
        if enable:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            exe = launcher_exe()
            ico = os.path.join(hub_dir(), "advprint.png")
            with open(p, "w", encoding="utf-8") as f:
                f.write("[Desktop Entry]\nType=Application\n"
                        "Name=AdvPrint Pro\n"
                        "Comment=Silent print hub (localhost:9235)\n"
                        "Exec=%s %s serve\n" % (exe, os.path.join(hub_dir(),
                                                                 "advprint.py")))
                if os.path.isfile(ico):
                    f.write("Icon=%s\n" % ico)
                f.write("Terminal=false\nCategories=Utility;\n")
            return os.path.isfile(p)
        if os.path.isfile(p):
            os.remove(p)
        return False
    except Exception as e:
        log("[AUTOSTART] error: %s" % e)
        return autostart_enabled()


# ------------------------------------------------------------
# HTTP API (pure stdlib, CORS-ready for ANY browser/website)
# ------------------------------------------------------------
CORS_HEADERS = [
    ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
    ("Access-Control-Allow-Headers",
     "Content-Type, X-AdvPrint-Token, Access-Control-Request-Private-Network"),
    ("Access-Control-Max-Age", "86400"),
]
# v2.9.1 (audit H6 fix): "Access-Control-Allow-Private-Network: true" is NO
# LONGER sent unconditionally (it used to live in the list above). It is
# added per-request in _cors() ONLY when the caller's Origin is actually
# allowed - so a random website's Local Network Access preflight for the
# hub is denied by default instead of green-lit from every page on the
# internet.

# v2.0 auth hardening state
_AUTH_FAILS = {}          # ip -> {count, until, first, last_audit, warned}
                          # 10 wrong tokens inside the window -> lock
                          # (v2.0.1: loopback IPs are exempt by default -
                          #  see lockout_exempt_loopback in CFG)
_AUTH_AUDIT_TS = {}       # ip -> last auth.failed audit write (survives
                          # success-clears so the audit log can never be
                          # flooded: max 1 row per 10 s per IP)
# v2.9.1 (audit L4 fix): the two dicts above are mutated from EVERY request
# thread - the multi-step check/increment/lock decisions now run under one
# lock so two concurrent failures cannot interleave the bookkeeping.
_AUTH_LOCK = threading.Lock()
START_TS = time.time()    # for the diagnostics uptime report

def _extension_origin(origin):
    """Browser-extension origins are always trusted (they are the user's
    own install, governed by the extension's master switch)."""
    o = (origin or "").lower()
    return (o.startswith("chrome-extension://")
            or o.startswith("moz-extension://")
            or o.startswith("safari-web-extension://"))

def mask_token(tok):
    t = str(tok or "")
    return (t[:4] + "***") if len(t) > 6 else "***"

def read_json_body(handler, required=True):
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        if required:
            raise ValueError("empty or oversized body (0 bytes)")
        return {}
    if length > MAX_BODY:
        raise ValueError("oversized body (%d bytes)" % length)
    raw = handler.rfile.read(length)
    ctype = (handler.headers.get("Content-Type") or "").lower()
    if "urlencoded" in ctype:
        # Browser hidden-form fallback: field 'payload' carries the JSON.
        fields = dict(parse_qsl(raw.decode("utf-8", "replace")))
        payload = fields.get("payload") or (list(fields.values())[0] if fields else "")
        try:
            return json.loads(payload)
        except Exception:
            raise ValueError("form 'payload' field is not valid JSON")
    return json.loads(raw.decode("utf-8", "replace"))

def read_raw_body(handler):
    """Read the request body as raw bytes (raw-PDF / multipart / IPP).
    v3.0.8: also decodes "Transfer-Encoding: chunked" - some phone IPP
    print stacks POST without a Content-Length, and a body reader that
    only knows Content-Length turns that into "empty body" errors."""
    te = (handler.headers.get("Transfer-Encoding") or "").lower()
    if "chunked" in te:
        chunks = []
        total = 0
        while True:
            line = handler.rfile.readline(1024)
            if not line:
                raise ValueError("truncated chunked body")
            try:
                size = int(line.strip().split(b";")[0], 16)
            except ValueError:
                raise ValueError("bad chunk size header")
            if size == 0:
                # consume trailers (optionally sent) up to the blank line
                while True:
                    t = handler.rfile.readline(1024)
                    if t in (b"\r\n", b"\n", b""):
                        break
                break
            total += size
            if total > MAX_BODY:
                raise ValueError("oversized chunked body")
            data = handler.rfile.read(size)
            if len(data) < size:
                raise ValueError("truncated chunk")
            chunks.append(data)
            handler.rfile.readline(1024)   # CRLF after each chunk
        return b"".join(chunks)
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        raise ValueError("empty body (0 bytes)")
    if length > MAX_BODY:
        raise ValueError("oversized body (%d bytes)" % length)
    return handler.rfile.read(length)

def parse_multipart(raw, ctype):
    """Minimal multipart/form-data parser (stdlib only - the cgi module was
    removed in Python 3.13). Returns (file_bytes_or_None, fields dict).
    The file part is the one carrying a filename or field name 'pdf'/'file'.
    Lets Laravel/PHP clients do Http::attach('pdf', $bytes)->post(...) with
    NO base64 encoding."""
    m = re.search(r'boundary="?([^";,]+)"?', ctype or "", re.I)
    if not m:
        raise ValueError("multipart body without boundary")
    bnd = ("--" + m.group(1)).encode("utf-8")
    fields, fdata = {}, None
    for part in raw.split(bnd):
        p = part
        if p.startswith(b"\r\n"):
            p = p[2:]
        if p.endswith(b"\r\n"):
            p = p[:-2]
        if p in (b"", b"--") or b"\r\n\r\n" not in p:
            continue
        head, _, content = p.partition(b"\r\n\r\n")
        nm = re.search(rb'name="([^"]*)"', head)
        name = nm.group(1).decode("utf-8", "replace") if nm else ""
        if b'filename="' in head or name in ("pdf", "file"):
            fdata = content
            fn = re.search(rb'filename="([^"]*)"', head)   # v2.8: keep it
            if fn:
                fields["filename"] = fn.group(1).decode("utf-8", "replace")
        else:
            fields[name] = content.decode("utf-8", "replace")
    return fdata, fields

class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """v2.9.1 (audit H7 fix): re-run pdf_url_guard() on EVERY redirect hop.
    The old download_pdf guarded the FIRST url only - urllib then followed
    redirects un-rechecked, so an attacker URL (public host, allowed by the
    guard) could 302 straight to file:// / http://127.0.0.1 / any private
    address and turn the hub into an internal-network file fetcher."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        pdf_url_guard(newurl)          # blocked hop raises - fetch aborts
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def download_pdf(url):
    """Fetch a PDF from a URL (used by 'pdf_url' mode).
    v2.0: guarded by pdf_url_guard() - file://, ftp:// and private/local
    addresses are blocked (see pdf_url_allowed_hosts for exemptions).
    v2.9.1 (audit H7 fix): EVERY redirect hop is re-guarded (see
    _GuardedRedirect), so a redirect to loopback/private/file can no
    longer bypass the allowlist."""
    pdf_url_guard(url)
    req = urllib.request.Request(url, headers={"User-Agent": "AdvPrintPro/%s" % VERSION})
    opener = urllib.request.build_opener(_GuardedRedirect)
    with opener.open(req, timeout=30) as r:
        data = r.read(MAX_PDF + 1)
    if not data or len(data) > MAX_PDF:
        raise ValueError("pdf_url download too large or empty")
    if not data[:5].startswith(b"%PDF"):
        raise ValueError("pdf_url did not return a PDF")
    return data

# ------------------------------------------------------------
# REPRINT watermark (v2.0): stamps diagonal gray text on every page.
# Best-effort pure-Python PDF edit - on ANY problem the ORIGINAL bytes
# are returned so printing never breaks because of the watermark.
# ------------------------------------------------------------
def pdf_watermark(data, text="REPRINT"):
    try:
        return _pdf_watermark_impl(data, text)
    except Exception as e:
        log("[WARN] watermark skipped (%s) - printing the original file" % e)
        return data

def _pdf_watermark_impl(data, text):
    if not data or not data[:5].startswith(b"%PDF") or b"/Encrypt" in data[:2048]:
        return data
    if b"ObjStm" in data:          # compressed object streams: not edited
        raise ValueError("PDF uses object streams")
    text = (text or "REPRINT")[:24]
    # collect top-level "N 0 obj ... endobj" segments
    objs = {}                       # num -> bytes body (without obj/endobj)
    for m in re.finditer(rb"(\d+)\s+0\s+obj\b", data):
        num = int(m.group(1))
        end = data.find(b"endobj", m.end())
        if end < 0:
            raise ValueError("broken object body")
        objs[num] = data[m.end():end].strip(b"\r\n \t")
        if len(objs) > 4000:
            raise ValueError("PDF too complex to watermark")
    if not objs:
        raise ValueError("no objects found")
    pages = [n for n, b in objs.items() if re.search(rb"/Type\s*/Page\b", b)]
    if not pages:
        raise ValueError("no page objects found")
    next_id = max(objs) + 1
    gs_id, font_id = next_id, next_id + 1
    ov_id = next_id + 2
    next_id += 3
    content = (
        b"q /PHwm gs 0.72 0.72 0.72 rg BT /PHwmF 56 Tf "
        b"0.7071 0.7071 -0.7071 0.7071 60 240 Tm (" +
        _pdf_escape(text).encode("latin-1", "replace") + b") Tj ET Q")
    objs[gs_id] = b"<< /Type /ExtGState /CA 0.18 /ca 0.18 >>"
    objs[font_id] = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica"
                     b" /Encoding /WinAnsiEncoding >>")
    objs[ov_id] = b"<< /Length %d >>\nstream\n" % len(content) + content + \
                  b"\nendstream"
    for n in pages:
        body = objs[n]
        if re.search(rb"/Contents\s*\[", body):
            body = re.sub(rb"/Contents\s*\[", b"/Contents [" +
                          b" %d 0 R" % ov_id, body, count=1)
        elif re.search(rb"/Contents\s*/?\d+\s+0\s+R", body):
            body = re.sub(rb"(/Contents\s*)/?(\d+\s+0\s+R)",
                          lambda mm: mm.group(1) + b"[%d 0 R %s]"
                          % (ov_id, mm.group(2)),
                          body, count=1)
        else:
            raise ValueError("page %d has no /Contents" % n)
        if b"/ExtGState" not in body:
            if b"/Resources" not in body:
                body += (b" /Resources << /ExtGState << /PHwm %d 0 R >>"
                         b" /Font << /PHwmF %d 0 R >> >>" % (gs_id, font_id))
            else:
                body = re.sub(rb"/Resources\s*<<",
                              b"/Resources << /ExtGState << /PHwm %d 0 R >>"
                              b" /Font << /PHwmF %d 0 R >>" % (gs_id, font_id),
                              body, count=1)
        elif b"PHwm" not in body:
            body = re.sub(rb"/ExtGState\s*<<",
                          b"/ExtGState << /PHwm %d 0 R" % gs_id, body, count=1)
            if b"PHwmF" not in body:
                body = re.sub(rb"/Font\s*<<",
                              b"/Font << /PHwmF %d 0 R" % font_id, body, count=1)
        objs[n] = body
    # re-serialize everything with a fresh classic xref table
    out = bytearray(data.split(b"%PDF-", 1)[0][:0] + b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for idx in sorted(objs):
        offsets[idx] = len(out)
        out += ("%d 0 obj\n" % idx).encode() + objs[idx] + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % next_id).encode()
    out += b"0000000000 65535 f \n"
    for idx in range(1, next_id):
        if idx in offsets:
            out += ("%010d 00000 n \n" % offsets[idx]).encode()
        else:
            out += b"0000000000 65535 f \n"      # gap ids keep the table aligned
    cat = next(n for n, b in objs.items() if b"/Type" in b and b"/Catalog" in b)
    out += ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (next_id, cat, xref)).encode()
    return bytes(out)

# ------------------------------------------------------------
# RAW printing (v2.0): ESC/POS receipts + ZPL labels - no driver, no PDF
#   Windows: winspool RAW datatype via ctypes (pure stdlib)
#   Unix:    CUPS "lp -o raw"
# ESC/POS helpers cover cut, cash drawer, CODE128 barcode and QR codes.
# ------------------------------------------------------------
ESC_ESC = b"\x1b"
def escpos_init():
    return ESC_ESC + b"@"                      # initialize

def _escpos_cp():
    return str(CFG.get("escpos_codepage") or "cp437")

def escpos_align(mode):
    return ESC_ESC + b"a" + bytes([mode])      # 0 left, 1 center, 2 right

def escpos_size(big):
    return (b"\x1d!\x11" if big else b"\x1d!\x00")   # double / normal

def escpos_feed(n=4):
    return ESC_ESC + b"d" + bytes([max(0, min(255, int(n)))])

def escpos_cut():
    return b"\x1dV\x42\x00"                    # full cut

def escpos_drawer():
    return b"\x1bp\x00\x19\xfa"                # pin 2, 50 ms on / 250 ms off

def escpos_barcode(data):
    d = b"{B" + str(data or "").encode("ascii", "replace")[:60]
    return b"\x1dkI" + bytes([len(d)]) + d     # GS k 73 (CODE128)

def escpos_qr(data):
    d = str(data or "").encode("utf-8")[:500]
    nL, nH = (len(d) + 3) & 0xFF, ((len(d) + 3) >> 8) & 0xFF
    return (b"\x1d(k\x04\x001A2\x00"           # model 2
            b"\x1d(k\x03\x001C\x06"            # module size 6
            b"\x1d(k\x03\x001E\x31"            # error correction M
            b"\x1d(k" + bytes([nL, nH]) + b"31" + d +
            b"\x1d(k\x03\x0031Q")              # print

def escpos_bytes(text, cut=True, drawer=False):
    """Plain text -> ESC/POS receipt bytes. Markers:
    '#big ' double size | '|center|' centered | '|right|' right aligned
    '|cut|' cut here  | '|drawer|' open cash drawer
    '|barcode:12345|' CODE128  | '|qr:text|' QR code."""
    out = bytearray(escpos_init())
    out += escpos_align(1)
    out += b"AdvPrint Pro\n\n"
    out += escpos_align(0)
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip("\n")
        if line.startswith("|cut|"):
            out += escpos_feed(3) + escpos_cut()
            continue
        if line.startswith("|drawer|"):
            out += escpos_drawer()
            continue
        m = re.match(r"^\|barcode:([^|]+)\|\s*$", line)
        if m:
            out += escpos_align(1) + escpos_barcode(m.group(1)) + \
                   escpos_feed(2) + escpos_align(0)
            continue
        m = re.match(r"^\|qr:([^|]*)\|\s*$", line)
        if m:
            out += escpos_align(1) + escpos_qr(m.group(1)) + \
                   escpos_feed(2) + escpos_align(0)
            continue
        big = line.startswith("#big")
        if big:
            line = line[4:].strip()
        if line.startswith("|center|"):
            out += escpos_align(1)
            line = line[8:].strip()
        elif line.startswith("|right|"):
            out += escpos_align(2)
            line = line[7:].strip()
        else:
            out += escpos_align(0)
        out += escpos_size(big)
        try:
            out += line.encode(_escpos_cp()) + b"\n"
        except (UnicodeEncodeError, LookupError):
            # configured codepage cannot represent this line (e.g. Bangla):
            # fall back to cp437 + replacement chars AND warn once per job
            out += line.encode("cp437", "replace") + b"\n"
            log("[RAW] line not encodable in %s - replaced; use the"
                " html/page path (or thermal_text_engine) for Bangla" % _escpos_cp())
        out += escpos_size(False)
    out += escpos_feed(4)
    if drawer:
        out += escpos_drawer()
    if cut:
        out += escpos_cut()
    return bytes(out)

def raw_print_windows(data, printer, job_id=None, title="raw"):
    """Send RAW bytes to a Windows printer via winspool (DATATYPE RAW)."""
    import ctypes
    from ctypes import wintypes
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    OpenPrinterW = winspool.OpenPrinterW
    OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(ctypes.c_void_p),
                             ctypes.POINTER(ctypes.c_void_p)]
    StartDocPrinterW = winspool.StartDocPrinterW
    StartDocPrinterW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.c_void_p)]
    WritePrinter = winspool.WritePrinter
    WritePrinter.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD)]
    class DOCINFO1(ctypes.Structure):
        _fields_ = [("pDocName", ctypes.c_void_p),
                    ("pDatatype", ctypes.c_void_p),
                    ("pOutputFile", ctypes.c_void_p)]
    h = ctypes.c_void_p()
    name = ctypes.c_wchar_p(printer or "NULL")
    if not OpenPrinterW(name, ctypes.byref(h), None):
        raise RuntimeError("printer '%s' not found (winspool error %d)"
                           % (printer or "(default)", ctypes.get_last_error()))
    try:
        di = DOCINFO1()
        di.pDocName = ctypes.cast(ctypes.c_wchar_p(title or "AdvPrint raw"),
                                  ctypes.c_void_p).value
        di.pDatatype = ctypes.cast(ctypes.c_wchar_p("RAW"),
                                   ctypes.c_void_p).value
        di.pOutputFile = None
        if not StartDocPrinterW(h, 1, ctypes.byref(di)):
            raise RuntimeError("StartDocPrinter failed (error %d)"
                               % ctypes.get_last_error())
        if not winspool.StartPagePrinter(h):
            raise RuntimeError("StartPagePrinter failed")
        written = wintypes.DWORD(0)
        chunk = 65536
        for off in range(0, len(data), chunk):
            view = (ctypes.c_char * min(chunk, len(data) - off)).from_buffer_copy(
                data[off:off + chunk])
            if not WritePrinter(h, view, len(data) - off, ctypes.byref(written)):
                raise RuntimeError("WritePrinter failed (error %d)"
                                   % ctypes.get_last_error())
        winspool.EndPagePrinter(h)
        winspool.EndDocPrinter(h)
    finally:
        winspool.ClosePrinter(h)
    return printer or "Windows RAW"

def print_raw(data, printer="", job_id=None, title="raw"):
    """Print RAW bytes (ESC/POS / ZPL / PCL) directly to the printer."""
    # v2.9: destination routing - ANY printer. Raw bytes go out as-is;
    # the printer language is whatever the sender chose.
    dkind, dtarget = resolve_dest(printer)
    if dkind == "ip":
        name = ip_printer_send(data, title or "raw", dtarget,
                               docformat="application/octet-stream")
        log("[RAW] -> %s (%d bytes)" % (name, len(data)))
        return name
    target = dtarget or default_printer() or ""
    if not target:
        raise RuntimeError("raw printing needs a printer name"
                           " (no OS default printer found)")
    if IS_WIN:
        log("[RAW] winspool -> %s (%d bytes)" % (target, len(data)))
        return raw_print_windows(data, target, job_id=job_id, title=title)
    if shutil.which("lp") is None:
        raise RuntimeError("CUPS 'lp' not found - raw printing needs CUPS")
    path = os.path.join(tempfile.gettempdir(), "advprint-raw-%s.prn" % os.getpid())
    with open(path, "wb") as f:
        f.write(data)
    try:
        cmd = ["lp", "-d", target, "-o", "raw", path]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError("raw print failed: %s"
                               % (proc.stderr or proc.stdout or "")[:200])
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    log("[RAW] lp -o raw -> %s (%d bytes)" % (target, len(data)))
    return target

def raw_payload_bytes(body):
    """Build the raw byte stream for /print raw mode.
      raw_base64            -> verbatim bytes (ESC/POS or ZPL you prepared)
      lang=escpos + text    -> ESC/POS builder (cut/drawer/barcode/QR markers)
      lang=zpl + text       -> verbatim ZPL II text (^XA...^XZ)
    Returns (bytes, lang)."""
    lang = (body.get("lang") or "escpos").lower()
    if body.get("raw_base64"):
        data = base64.b64decode(body["raw_base64"], validate=False)
        return data, lang
    text = body.get("text")
    if text is None:
        raise ValueError("raw print needs 'text' or 'raw_base64'")
    if lang == "zpl":
        return str(text).encode("latin-1", "replace"), "zpl"
    cut = body.get("cut", True)
    if isinstance(cut, str):
        cut = cut.strip().lower() not in ("0", "false", "no", "off")
    drawer = body.get("drawer", False)
    if isinstance(drawer, str):
        drawer = drawer.strip().lower() in ("1", "true", "yes", "on")
    return escpos_bytes(text, cut=bool(cut), drawer=bool(drawer)), "escpos"


# ------------------------------------------------------------
# v2.7.0: shared reprint core - used by POST /jobs/{id}/reprint AND
# POST /jobs/bulk-reprint (the dashboard History tab "Reprint selected"
# / "Reprint all non-printed" buttons and the extension History panel).
# Returns (http_status, payload_dict).
# ------------------------------------------------------------
def reprint_job_core(j, body, ip, site):
    """Re-queue one stored job row `j` for printing again. `body` may
    carry reason / watermark / watermark_text / printer exactly like the
    single-job endpoint. Never raises - problems come back as (4xx/5xx)."""
    try:
        if not j:
            return 404, {"ok": False, "error": "job not found"}
        if not (j.get("file_path") and os.path.exists(j["file_path"])):
            return 410, {"ok": False,
                         "error": "original file no longer stored"}
        # v2.0: the audit trail asks WHY something is printed again
        reason = str((body or {}).get("reason") or "").strip()[:200] or None
        if CFG.get("reprint_reason_required") and not reason:
            return 400, {
                "ok": False,
                "error": "a reprint reason is required on this hub"
                         " (reprint_reason_required) - add \"reason\""}
        wm = (body or {}).get("watermark")
        if wm is None:
            wm = CFG.get("reprint_watermark", False)
        elif isinstance(wm, str):
            wm = wm.strip().lower() in ("1", "true", "yes", "on")
        with open(j["file_path"], "rb") as f:
            data = f.read()
        if wm and j.get("kind") != "raw":
            data = pdf_watermark(data, str((body or {}).get("watermark_text")
                                           or "REPRINT"))
        # a 'saved' (file-destination) job has no printer yet ->
        # reprinting it sends it to the OS default printer
        rpt_printer = str((body or {}).get("printer") or "")
        if not rpt_printer:
            rpt_printer = ("" if j["status"] == "saved"
                           else (j["printer"] or ""))
            if rpt_printer == "File (PDF)":
                rpt_printer = ""
        job, dup = enqueue_print(
            j["kind"], (j["title"] or "reprint") + "-reprint", data,
            rpt_printer, j["copies"] or 1, "api", ip,
            site=site, reason=reason,
            dedupe=False,          # a reprint is never a duplicate
            priority=(j.get("priority") or 5),
            pages=j.get("pages"), duplex=j.get("duplex"),
            paper_size=j.get("paper_size"), tray=j.get("tray"),
            profile=j.get("profile"),
            content_hash=hashlib.sha256(data).hexdigest(),
            **({"watermarked": 1} if wm else {}))
        db_audit("reprint", job_id=job, actor="api", site=site, ip=ip,
                 doc_hash=hashlib.sha256(data).hexdigest(),
                 printer=rpt_printer, reason=reason,
                 details="reprint of job #%d%s"
                         % (j["id"], ", watermarked" if wm else ""))
        return 200, {"ok": True, "job_id": job,
                     "duplicate": dup is not None,
                     "reprint_of": j["id"],
                     "watermark": bool(wm and j.get("kind") != "raw")}
    except Exception as e:                      # never kill the request
        return 500, {"ok": False, "error": "reprint failed: %s" % e}



# ------------------------------------------------------------
# v3.0.7 SELF-HOST EXTENSION SERVER.  The hub serves the SIGNED,
# PACKED browser extension (.crx, CRX3 format) plus a Chromium
# update manifest, so Chrome / Edge / Brave install it silently
# through the enterprise force-install policy AND auto-update it
# whenever a newer .crx lands in the install folder:
#
#   policy value:  <extension-id>;http://127.0.0.1:9235/extension/updates.xml
#   open GET:      /extension/updates.xml        gupdate 2.0 XML
#                  /extension/AdvPrint-Pro.crx   the signed package
#                  /extension/info               dashboard JSON
#                  /extension                    landing page
#
# The endpoints are OPEN because Chrome's updater cannot send our
# token header - but the Host-header rule (localhost / LAN IP only)
# still applies, so no outsider can pull the package.  The .crx
# ships inside the Setup exe / deb at <hub folder>/extension/; the
# extension ID is DERIVED FROM THE SIGNING KEY inside the .crx
# header, so the ID is stable across versions - that stability is
# exactly what makes silent updates possible (same ID + higher
# version in updates.xml = Chrome updates without any prompt).
EXT_CRX_NAME = "AdvPrint-Pro.crx"
# Belt-and-braces: the ID of the release signing key.  Everything
# derives from the shipped .crx at runtime; this fallback only
# covers the "policy without package" corner (recovery installs).
EXT_CRX_ID = "likldbkamojokkfdlcjibiljpgbbnohc"
_EXT_CRX_CACHE = {"path": None, "mtime": None, "loaded": False,
                  "data": None, "ext_id": None, "version": None}


def _crx_pb_varint(buf, i):
    shift = val = 0
    while True:
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, i
        shift += 7


def _crx_pb_fields(buf):
    """Minimal protobuf reader for the CRX3 header (wire type 2 only)."""
    out = {}
    i = 0
    while i < len(buf):
        tag, i = _crx_pb_varint(buf, i)
        fn, wt = tag >> 3, tag & 7
        if wt == 2:
            ln, i = _crx_pb_varint(buf, i)
            out.setdefault(fn, []).append(buf[i:i + ln])
            i += ln
        elif wt == 0:
            v, i = _crx_pb_varint(buf, i)
            out.setdefault(fn, []).append(v)
        else:
            raise ValueError("wire type %d" % wt)
    return out


def _crx_id_from_raw(raw16):
    """16 bytes -> 32 letters a..p (hex NIBBLE mapping, id_util.cc)."""
    return "".join(chr(n + 97) for b in raw16
                   for n in (b >> 4, b & 0x0F))


def _crx_paths():
    here = os.path.dirname(os.path.abspath(__file__))
    return [os.path.join(here, "extension", EXT_CRX_NAME),
            os.path.join(os.path.expanduser("~"), ".advprint",
                         "extension", EXT_CRX_NAME)]


def crx_package(force=False):
    """The shipped .crx: {'data','ext_id','version','path'} or None.
    Parsed ONCE, re-parsed automatically when the file changes (so an
    IT admin can drop a newer package in without restarting the hub
    and every Chrome still updates silently).  Pure stdlib."""
    import struct as _struct
    import zipfile as _zipfile
    c = _EXT_CRX_CACHE
    for p in _crx_paths():
        try:
            mtime = os.path.getmtime(p)
        except OSError:
            continue
        if (not force and c["loaded"] and c["path"] == p
                and c["mtime"] == mtime):
            return c
        try:
            with open(p, "rb") as f:
                data = f.read()
            if data[:4] != b"Cr24":
                continue
            hlen = _struct.unpack("<I", data[8:12])[0]
            if hlen <= 0 or 12 + hlen > len(data):
                continue
            header = data[12:12 + hlen]
            fields = _crx_pb_fields(header)
            # signed_header_data (field 10000) = SignedData{crx_id=1}
            signed = fields[10000][0]
            raw_id = _crx_pb_fields(signed)[1][0]
            ext_id = _crx_id_from_raw(raw_id)
            # manifest.json lives inside the zip that follows the header
            with _zipfile.ZipFile(io.BytesIO(data[12 + hlen:])) as zf:
                version = json.loads(
                    zf.read("manifest.json").decode("utf-8")).get(
                    "version", "?")
            c.update(path=p, mtime=mtime, loaded=True, data=data,
                     ext_id=ext_id, version=version)
            return c
        except Exception:
            continue
    return None


def _ver_lt(a, b):
    """v3.2.8: True when dotted version string a is OLDER than b.
    Non-numeric parts compare as 0 ('3.2.8a' < '3.2.8' is NOT claimed
    older - equal parts win). Pure int comparison, never raises."""
    def nums(v):
        out = []
        for part in str(v or "").split("."):
            try:
                out.append(int(re.sub(r"\D", "", part) or 0))
            except Exception:
                out.append(0)
        return out or [0]
    A, B = nums(a), nums(b)
    while len(A) < len(B):
        A.append(0)
    while len(B) < len(A):
        B.append(0)
    return A < B


def ext_health():
    """Compact /health block about the served extension.
    v3.2.8 STALE-CRX GUARD (the Bug 2 delivery trap): the hub serves its
    embedded .crx at /extension/updates.xml and Chrome auto-updates from
    it. When that embedded copy is OLDER than the hub itself (it can
    happen - the v3.2.8 build forgot to re-sync the embedded copy, so
    the hub kept serving 3.2.6 while the hub code was 3.2.8), Chrome
    NEVER sees a higher version, NEVER updates, and every browser keeps
    running the OLD extension with the OLD bugs - the fixed release
    silently never reaches the page. 'stale: true' makes that state
    VISIBLE in /health, /extension/info, /extension and the Console."""
    c = crx_package()
    if not c:
        return {"served": False, "id": EXT_CRX_ID}
    return {"served": True, "id": c["ext_id"], "version": c["version"],
            "hub_version": VERSION, "stale": _ver_lt(c["version"], VERSION)}


# ---- Windows per-user force-install policy (HKCU - no UAC needed;
#      the Setup exe writes the machine-wide HKLM twin) ----
EXT_POLICY_BROWSERS = [          # (hive path fragment, display name)
    ("Google\\Chrome", "Chrome"),
    ("Microsoft\\Edge", "Edge"),
    ("BraveSoftware\\Brave", "Brave"),
    ("Chromium", "Chromium"),
    ("Vivaldi", "Vivaldi"),
]


def ext_policy_url():
    return "http://127.0.0.1:%d/extension/updates.xml" % int(
        CFG.get("port", 9235))


def ext_forcelist_value():
    c = crx_package()
    ext_id = c["ext_id"] if c else EXT_CRX_ID
    return "%s;%s" % (ext_id, ext_policy_url())


def _ext_reg_hive(hive):
    """'HKCU'/'HKLM' -> full Python registry-ish key via reg.exe."""
    return hive


def _ext_reg_query_values(full_key):
    """{value_name: data} of REG_SZ values under full_key (reg.exe)."""
    out = {}
    if not IS_WIN:
        return out
    try:
        p = subprocess.run(["reg", "query", full_key],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return out
    if p.returncode != 0:
        return out
    for line in (p.stdout or "").splitlines():
        m = re.match(r"\s+(\S+)\s+REG_SZ\s+(.*?)\s*$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _ext_reg_add(full_key, name, data):
    """v3.2.5 BUG FIX 5: reg.exe first, PowerShell fallback second.
    User report "policy install failed: HTTP 200" - on several machines
    reg.exe is blocked by AV suites / app-control policies while
    New-ItemProperty still works, and the console hid the real reason
    behind a generic 'HTTP 200'. Both writers do the same thing:
    REG_SZ value <name> = <data> under <full_key> (the key is created)."""
    r = subprocess.run(
        ["reg", "add", full_key, "/v", name, "/t", "REG_SZ",
         "/d", data, "/f"], capture_output=True, text=True,
        timeout=10).returncode == 0
    if r:
        return True
    if not IS_WIN:
        return False
    ps = ("$k='%s';" % full_key.replace("'", "''") +
          "New-Item -Path $k -Force -ErrorAction SilentlyContinue "
          "| Out-Null;"
          "New-ItemProperty -Path $k -Name '%s' -PropertyType String "
          "-Value '%s' -Force | Out-Null"
          % (name.replace("'", "''"), data.replace("'", "''")))
    try:
        p2 = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", ps], capture_output=True, text=True, timeout=20,
            creationflags=HIDE)
        ok2 = p2.returncode == 0
        if ok2:
            log("[POLICY] reg.exe failed for %s - PowerShell fallback "
                "wrote it" % full_key)
        else:
            log("[POLICY] PowerShell fallback failed too (rc %s): %s"
                % (p2.returncode, (p2.stderr or "").strip()[:200]))
        return ok2
    except Exception as e:
        log("[POLICY] PowerShell fallback error: %s" % e)
        return False


def _ext_reg_delete(full_key, name):
    try:
        return subprocess.run(
            ["reg", "delete", full_key, "/v", name, "/f"],
            capture_output=True, text=True, timeout=10).returncode == 0
    except Exception:
        return False


def ext_policy_status():
    """Where is the force-install policy present, per browser?"""
    ext_id = (crx_package() or {}).get("ext_id", EXT_CRX_ID)
    want = ext_id + ";"
    result = {"ok": True, "platform": "windows" if IS_WIN else
              ("macos" if IS_MAC else "linux"),
              "extension_id": ext_id,
              "updates_url": ext_policy_url(),
              "browsers": {}}
    if not IS_WIN:
        result["note"] = ("on Linux the deb package installs the policy"
                          " as /etc/*/policies/managed/advprint-pro.json"
                          " (Chrome, Chromium, Edge, Brave) - check that"
                          " file; nothing is stored in the registry")
        return result
    for frag, name in EXT_POLICY_BROWSERS:
        b = {"present": False}
        for hive in ("HKCU", "HKLM"):
            key = "%s\\SOFTWARE\\Policies\\%s\\ExtensionInstallForcelist" \
                % (hive, frag)
            vals = _ext_reg_query_values(key)
            for vname, vdata in vals.items():
                if vdata.startswith(want) or vname.startswith("AdvPrint"):
                    b["present"] = True
                    b["hive"] = hive
                    b["value"] = vname
                    b["data"] = vdata
        result["browsers"][name] = b
    return result


def ext_policy_install():
    """Write the force-install policy for THIS user (HKCU).  Returns a
    per-browser report + the honest expectation text (silent install
    needs a managed/domain machine on Chrome + Edge; home PCs use
    Load unpacked instead)."""
    if not IS_WIN:
        return {"ok": False, "note": ext_policy_status().get("note")}
    data = ext_forcelist_value()
    ext_id = (crx_package() or {}).get("ext_id", EXT_CRX_ID)
    report = {}
    wrote = 0
    for frag, name in EXT_POLICY_BROWSERS:
        key = "HKCU\\SOFTWARE\\Policies\\%s\\ExtensionInstallForcelist" \
            % frag
        vals = _ext_reg_query_values(key)
        target = None
        for vname, vdata in vals.items():
            if vdata.startswith(ext_id + ";"):
                target = vname            # keep our existing slot
                break
        if target is None:
            target = str(len(vals) + 1)   # first free index
        ok = _ext_reg_add(key, target, data)
        if ok:
            # remember the slot so uninstall can remove exactly ours
            _ext_reg_add("HKCU\\Software\\AdvPrintPro",
                         "ExtPolicy." + frag, target)
            wrote += 1
        report[name] = ("written (entry %s)" % target if ok
                        else "reg add AND PowerShell fallback failed "
                             "(AV/app-control may block policy writes)")
    # v3.2.5 BUG FIX 5: carry the real reason in `error` so no client
    # ever reduces a {ok:false} response to a blind "HTTP 200" again.
    return {"ok": wrote > 0, "browsers": report, "wrote": wrote,
            "value": data,
            "error": (None if wrote > 0 else
                      "no policy entry written (HKCU) - check the "
                      "per-browser report; the docs 'Force-install "
                      "policy' section has the manual .reg / gpedit "
                      "apply steps"),
            "message": ("policy written for %d browser(s) - restart the"
                        " browser once, then chrome://policy shows it."
                        " Chrome/Edge install the extension silently on"
                        " managed (domain/enrolled) PCs; on a normal PC"
                        " Chrome ignores off-store force-install - use"
                        " chrome://extensions > Load unpacked there"
                        % wrote)}


def ext_policy_remove():
    """Delete exactly OUR force-install entries (never other
    extensions a company may already force-install)."""
    if not IS_WIN:
        return {"ok": False, "note": ext_policy_status().get("note")}
    ext_id = (crx_package() or {}).get("ext_id", EXT_CRX_ID)
    removed = []
    for frag, name in EXT_POLICY_BROWSERS:
        for hive in ("HKCU", "HKLM"):
            key = "%s\\SOFTWARE\\Policies\\%s\\ExtensionInstallForcelist" \
                % (hive, frag)
            vals = _ext_reg_query_values(key)
            for vname, vdata in vals.items():
                if vdata.startswith(ext_id + ";"):
                    if _ext_reg_delete(key, vname):
                        removed.append("%s %s:%s" % (name, hive, vname))
            slot_key = "HKCU\\Software\\AdvPrintPro"
            _ext_reg_delete(slot_key, "ExtPolicy." + frag)
    return {"ok": True, "removed": removed,
            "message": ("%d policy entry(ies) removed; Chrome removes the"
                        " extension at its next start (force-install"
                        " removal auto-uninstalls)" % len(removed))
            if removed else
            "no AdvPrint policy entry found - nothing to remove"}


class Handler(BaseHTTPRequestHandler):
    server_version = "AdvPrintPro/" + VERSION
    protocol_version = "HTTP/1.1"
    # v2.9.1 (audit M1 fix): a per-connection socket timeout. Before this
    # the handler had NO timeout - a slowloris client that opened a
    # connection and dribbled bytes (or just sent a huge Content-Length
    # and never a body) held a request thread FOREVER; 30 such sockets
    # stalled the whole hub. 30 s per recv is far above any real client
    # (LAN transfers stream continuously) and starves out dead peers.
    timeout = 30

    # ---- v2.9.1 (audit H5 fix): Host header allowlist ----
    # A DNS-rebinding page can rebind its own domain to 127.0.0.1 and then
    # fetch http://evil.example:9235/token/current FROM the hub PC - the
    # request arrives on loopback (trusted) with an ATTACKER Host header,
    # and "same-origin" so CORS does not help. Checking the Host header
    # closes it: only the names this hub is legitimately reached by are
    # accepted (loopback literals, private-LAN IP literals, this PC's LAN
    # IP, machine hostname, *.local). An attacker domain gets 421.
    def _host_ok(self):
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return True          # HTTP/1.0 clients may omit it (curl legacy)
        # v3.3.0 BUG 2: parse BRACKETED IPv6 hosts correctly - the old
        # split(":")[0] turned "[::1]" into "[" and rejected every IPv6
        # client with 421 the moment the hub gained a [::] listener.
        if host.startswith("["):
            end = host.find("]")
            hostname = host[1:end] if end > 0 else host[1:]
        else:
            hostname = host.split(":")[0]
        hostname = hostname.strip("[]").strip("%")
        if hostname in ("localhost", "localhost.localdomain",
                        "127.0.0.1", "::1", "::ffff:127.0.0.1", "::"):
            return True
        if hostname.endswith(".local") or hostname.endswith(".localdomain"):
            return True
        if hostname == (CFG.get("host") or "").lower() or \
                hostname == lan_ip().lower():
            return True
        try:
            ip = ipaddress.ip_address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_link_local
        except ValueError:
            return False         # rebinded/attacker domain

    def _host_error(self):
        """421 Misdirected Request when the Host header is foreign."""
        host = (self.headers.get("Host") or "-")[:100]
        db_audit("auth.host_denied", details="Host header not allowed: %s"
                 % host)
        log("[SECURITY] blocked request with foreign Host header: %s" % host)
        return self._send(421, {
            "ok": False,
            "error": "this is the AdvPrint Pro hub - reach it on"
                     " 127.0.0.1, the PC's hostname or its LAN IP"
                     " (Host header '%s' is not allowed)" % host})

    # ---- v2.9.1 (audit M1 fix): pre-auth body gate ----
    def _preauth_gate(self, q):
        """Big request bodies are no longer read BEFORE authentication.
        The old order read up to 25 MB of body first and only then checked
        the token - a remote client could make the hub swallow arbitrary
        bandwidth with zero credentials (a cheap DoS). Now: if the body
        is LARGE (> 1 MB) and the caller cannot show the token in the
        header OR the query string, the 401 is answered without reading
        a byte. Small bodies keep the old readable "invalid or missing
        token" errors, and the phone /send portal keeps working because
        its QR link carries ?token= (query token accepted here too)."""
        try:
            clen = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            clen = 0
        if clen <= 1024 * 1024:
            return False
        given = self.headers.get("X-AdvPrint-Token") or \
            (q.get("token") or [""])[0]
        if given and hmac.compare_digest(str(given), str(CFG["token"])):
            return False
        return True

    # ---- plumbing ----
    def _origin_allowed(self, origin):
        """v2.9.1 (audit H6 fix): shared allow-decision for ACAO + ACAPN.
        Extension origins are always allowed; plain origins need the
        allowed_origins list (empty list = the legacy open behaviour)."""
        return bool(origin) and (_extension_origin(origin)
                                 or origin_allowed(origin))

    def _cors(self):
        for k, v in CORS_HEADERS:
            self.send_header(k, v)
        # v2.0 origin allowlist: echo the caller origin when allowed,
        # otherwise omit Access-Control-Allow-Origin (browser blocks it).
        # Empty list = allow every origin exactly like 1.x did.
        origin = self.headers.get("Origin")
        if CFG.get("allowed_origins"):
            if self._origin_allowed(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
            else:
                self.send_header("Access-Control-Allow-Origin", "null")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        # v2.9.1 (audit H6 fix): the Private-Network preflight answer is
        # emitted ONLY for allowed origins - not for every website.
        if origin and self._origin_allowed(origin):
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_html(self, code, html):
        """v2.8: HTML page answer (send portal, error pages)."""
        body = html.encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_local(self, code, obj):
        """v2.6.2: like _send() but CORS-LOCKED for token-bearing replies.
        Access-Control-Allow-Origin is always "null" here, so a WEB PAGE
        from anywhere can never read the answer (its fetch is blocked by
        the browser). The browser extension does not need CORS at all -
        it has host_permissions for the hub address - so the extension
        keeps working while the token stays invisible to websites."""
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        for k, v in CORS_HEADERS:
            self.send_header(k, v)
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_file(self, path, download_name, ctype="application/pdf"):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self._send(404, {"ok": False, "error": "file no longer stored"})
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        # v2.9.1 (audit L7 fix): download names come from job titles, so a
        # title containing quotes/CR/LF used to break (or inject into) the
        # Content-Disposition header. Strip those, cap the length, and add
        # RFC 5987 filename* for non-ASCII (Bengali titles etc.).
        safe = "".join(c for c in str(download_name or "file")
                       if c not in ('"', "\r", "\n", "\\"))[:100] or "file"
        if all(ord(c) < 128 for c in safe):
            disp = 'attachment; filename="%s"' % safe
        else:
            disp = ("attachment; filename*=UTF-8''%s"
                    % quote(safe, safe=""))
        self.send_header("Content-Disposition", disp)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):     # quieter default logging
        if _env("VERBOSE"):
            log("[HTTP] %s %s" % (self.address_string(), fmt % args))

    # ---- auth (v2.0, fixed in v2.0.1) ----
    # * token in the X-AdvPrint-Token HEADER is always accepted
    # * token in query/body: accepted on old installs; on new installs
    #   (token_header_only) it is rejected everywhere EXCEPT the few
    #   endpoints a browser must open by navigation (/dashboard,
    #   /jobs/{id}/file, /export/*.csv) - documented in docs/API.md
    # * v2.0.1 LOCKOUT RULES (the v2.0.0 lockout could lock out the OWNER):
    #     - every Chrome window/profile shares ONE IP (127.0.0.1), so a
    #       stale token in one window locked the dashboard, tray and
    #       extension of ALL windows -> loopback is now exempt by default
    #       (config: lockout_exempt_loopback, default true)
    #     - failures only count inside a sliding window (lockout_minutes)
    #       so old failures can never accumulate into a surprise lock
    #     - a successful auth clears that IP's counter immediately
    #     - REMOTE IPs still get the full 10-wrong-tokens -> 5 min lock
    # * browser Origin header must match allowed_origins (when set)
    def _client_ip(self):
        return self.client_address[0] if self.client_address else "-"

    def _is_loopback(self):
        ip = self._client_ip()
        return ip in ("127.0.0.1", "::1", "localhost",
                      "::ffff:127.0.0.1", "::ffff:127.0.0.1%0")

    # ---- v3.2.9 BUG 3: the address THIS device used -------------------
    def _req_host(self):
        """The (sanitized) host part of the request's Host header - the
        address the OPENING device actually typed/used, e.g. the LAN PC
        sees the hub IP IT can reach, the hub PC sees localhost. Pages
        build their printer/queue URLs from this so every device gets
        its own local ip:port (never one global lan_ip())."""
        host, _p = _sanitize_host_hdr(self.headers.get("Host"))
        if not host:
            return ""
        loop = host in ("localhost", "127.0.0.1", "::1") or \
            host.startswith("127.")
        if loop:
            return ""                       # loopback names are per-PC only
        return host

    def _req_port(self):
        """Port from the Host header when the device used one, else the
        hub's configured port."""
        _h, p = _sanitize_host_hdr(self.headers.get("Host"))
        if p and p.isdigit():
            return int(p)
        return int(CFG.get("port", 9235))

    def _ip_gate(self):
        """v3.2.3 ALLOWED-IPS gate - runs BEFORE auth on every GET/POST.
        Loopback (the hub PC itself) always passes; with the factory
        default allowed_ips ["*"] every LAN device passes as before.
        The moment the hub owner adds real entries (LAN Sharing >
        Allowed IPs) the request IP must match one, otherwise the caller
        gets a branded 403 (HTML for browsers, JSON for API clients) and
        the denial is audited (max 1 row per 10 s per IP)."""
        if self._is_loopback():
            return True
        rules = CFG.get("allowed_ips") or ["*"]
        if "*" in rules:
            return True
        ip = self._client_ip() or ""
        if ip_allowed_by_list(ip, rules):
            return True
        log("[ACL] %s denied - not in allowed_ips (%s)"
            % (ip, ",".join(str(r) for r in rules[:6])))
        now = time.time()
        if now - _ACL_AUDIT_TS.get(ip, 0) >= 10:
            _ACL_AUDIT_TS[ip] = now
            try:
                db_audit("acl.denied", ip=ip,
                         details="IP is not on the allowed_ips list")
            except Exception:
                pass
        if "text/html" in (self.headers.get("Accept") or ""):
            safe_ip = (ip.replace("&", "&amp;").replace("<", "&lt;")
                         .replace(">", "&gt;").replace('"', "&quot;"))[:100]
            page = (
                "<html><head><meta charset=\"utf-8\">"
                "<title>AdvPrint Pro - access denied</title>"
                "<style>body{font-family:Segoe UI,system-ui,sans-serif;"
                "background:#f5f8fc;color:#0f172a;display:flex;"
                "align-items:center;justify-content:center;min-height:100vh;"
                "margin:0}.win{max-width:540px;background:#fff;border:1px"
                " solid #e2e8f0;border-radius:12px;overflow:hidden;"
                "box-shadow:0 10px 30px rgba(15,23,42,.08)}.bar{background:"
                "linear-gradient(135deg,#1e3a8a,#1d4ed8);color:#fff;padding:"
                "14px 18px;font-weight:700;font-size:15px}.b{padding:18px;"
                "font-size:13.5px;line-height:1.65}code{background:#f1f5f9;"
                "border:1px solid #e2e8f0;border-radius:5px;padding:1px 5px;"
                "font-size:12px}footer{padding:10px 18px;border-top:1px"
                " solid #e2e8f0;color:#64748b;font-size:11.5px}</style>"
                "</head><body><div class=\"win\">"
                "<div class=\"bar\">AdvPrint Pro - access denied</div>"
                "<div class=\"b\"><b>" + safe_ip + "</b> is not on this"
                " hub's <b>Allowed-IPs</b> list, so the hub refuses the"
                " connection - the console, the send portal, the API and"
                " IPP printing included.<br><br>The hub PC's owner can"
                " allow this device in <b>THE ONE UI &#8594; LAN Sharing"
                " &#8594; Allowed IPs</b>, or set"
                " <code>&quot;allowed_ips&quot;: [&quot;*&quot;]</code> in"
                " config.json to open the hub for the whole LAN again."
                " (The hub PC itself, 127.0.0.1, is always allowed.)"
                "</div><footer>100% local &#183; no cloud. AdvPrint by"
                " Bit Dream IT - Innovative Healthcare Solutions.</footer>"
                "</div></body></html>").encode("utf-8")
            try:
                self.send_response(403)
                self._cors()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return False
        try:
            self._send(403, {"ok": False, "error":
                "access denied - this IP is not on the hub's allowed_ips"
                " list (the hub owner can add it in THE ONE UI > LAN"
                " Sharing > Allowed IPs)", "ip": ip,
                # v3.2.9 BUG 2: echo the ACTIVE rules so the denied
                # device (and the hub owner debugging it) sees exactly
                # which list applies - * / exact / CIDR / wildcard
                "allowed_ips": [str(r) for r in
                                (CFG.get("allowed_ips") or ["*"])[:8]]})
        except Exception:
            pass
        return False

    # ---- v3.2.6 UI SECURITY GATE ------------------------------------
    def _is_own_host(self):
        """True when the request comes from the hub PC ITSELF: loopback
        OR any of this machine's own IPs (so http://<own-lan-ip>:9235/ui
        still opens ON the hub PC). An undeterminable client address
        passes - the owner is never locked out by a proxy quirk."""
        ip = self._client_ip()
        if not ip:
            return True
        if ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            return True
        try:
            return ip in own_ip_set()
        except Exception:
            return True

    def _mgmt_locked(self, route):
        """v3.2.6: True when THIS route must refuse non-local callers.
        From the hub PC everything answers as before. From the LAN only
        the PRINT SURFACE answers (see MGMT_OPEN_* above) - the console
        UI and every settings/management endpoint are local-only."""
        if self._is_own_host():
            return False
        if self.command == "POST":
            if route in MGMT_POST_DENY:
                return True
            if route in MGMT_OPEN_POST_EXACT:
                return False
            for p in MGMT_OPEN_POST_PREFIX:
                if route.startswith(p):
                    return False
            return True
        if route in MGMT_OPEN_GET_EXACT:
            return False
        for p in MGMT_OPEN_GET_PREFIX:
            if route.startswith(p):
                return False
        return True

    def _ui_locked_answer(self, route):
        """Branded 403 for a LAN visitor that touched a local-only
        route. HTML for browsers (points at the print URLs), JSON for
        API clients. Audited once per 10 s per IP like the ACL gate."""
        ip = self._client_ip() or "?"
        log("[SECURITY] %s %s refused - the console UI is local-only "
            "(v3.2.6)" % (ip, route))
        now = time.time()
        if now - _ACL_AUDIT_TS.get("ui" + ip, 0) >= 10:
            _ACL_AUDIT_TS["ui" + ip] = now
            try:
                db_audit("ui.locked", ip=ip,
                         details="non-local request to local-only %s"
                                 % route[:80])
            except Exception:
                pass
        if "text/html" in (self.headers.get("Accept") or ""):
            page = (
                "<html><head><meta charset=\"utf-8\">"
                "<title>AdvPrint Pro - console is local-only</title>"
                "<style>body{font-family:Segoe UI,system-ui,sans-serif;"
                "background:#f5f8fc;color:#0f172a;display:flex;"
                "align-items:center;justify-content:center;min-height:100vh;"
                "margin:0}.win{max-width:560px;background:#fff;border:1px"
                " solid #e2e8f0;border-radius:12px;overflow:hidden;"
                "box-shadow:0 10px 30px rgba(15,23,42,.08)}.bar{background:"
                "linear-gradient(135deg,#1e3a8a,#1d4ed8);color:#fff;padding:"
                "14px 18px;font-weight:700;font-size:15px}.b{padding:18px;"
                "font-size:13.5px;line-height:1.7}code{background:#f1f5f9;"
                "border:1px solid #e2e8f0;border-radius:5px;padding:1px 5px;"
                "font-size:12px}footer{padding:10px 18px;border-top:1px"
                " solid #e2e8f0;color:#64748b;font-size:11.5px}</style>"
                "</head><body><div class=\"win\">"
                "<div class=\"bar\">AdvPrint Pro - the console runs on"
                " the hub PC only</div>"
                "<div class=\"b\"><b>Printing still works from this"
                " device.</b> This hub accepts print jobs from the whole"
                " LAN (or the Allowed-IPs list): the send portal, the"
                " IPP printer URL and the print API all answer"
                " normally.<br><br>"
                "The <b>console UI, the settings and the history are"
                " locked to the hub PC itself</b> (v3.2.6 security -"
                " only the hub's own screen may change hub settings)."
                " Open the console on the hub PC:"
                " <code>http://127.0.0.1:%d/ui</code><br><br>"
                "To PRINT from this device:<ul>"
                "<li>Phones: open the <b>Send portal</b> - ask the hub"
                " owner for the <code>/send?token=...</code> URL</li>"
                "<li>Any PC or phone: add this PC as a network printer"
                " - <code>http://%s:%d/ipp/print</code></li></ul>"
                "</div><footer>100% local &#183; no cloud. AdvPrint by"
                " Bit Dream IT - Innovative Healthcare Solutions.</footer>"
                "</div></body></html>"
                % (int(CFG.get("port", 9235)),
                   _html_escape(lan_ip() or "this-PC"),
                   int(CFG.get("port", 9235)))).encode("utf-8")
            try:
                self.send_response(403)
                self._cors()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        try:
            self._send(403, {
                "ok": False,
                "error": "local-only endpoint - '%s' answers on the hub"
                         " PC itself; LAN devices keep print access"
                         " (/print, /send, /ipp/print, /jobs)"
                         % route[:60]})
        except Exception:
            pass

    def _request_site(self):
        o = self.headers.get("Origin") or self.headers.get("Referer") or ""
        return o.strip()[:200] or None

    def _auth_hint(self, given):
        """Actionable hint appended to every 401 answer."""
        if given and given == LEGACY_TOKEN and CFG["token"] != LEGACY_TOKEN:
            return ("'%s' was the OLD default token and no longer works. "
                    "Get the current token from the tray menu (Open "
                    "dashboard), read it from %s, or run: %s"
                    % (LEGACY_TOKEN, config_path(), cli_cmd("token")))
        return ("get the token from the tray menu, from %s, or run: %s"
                % (config_path(), cli_cmd("token")))

    def _auth_error(self, qtoken=None, body=None, allow_query=False):
        """Returns None when authorized, otherwise (code, message).
        allow_query=True marks read-only GET navigation where the query
        token is accepted even in header-only mode (v2.0.2: every GET;
        POST stays header-strict)."""
        ip = self._client_ip()
        loopback = self._is_loopback()
        # v2.6.3: loopback is UNCONDITIONALLY exempt from lockout. The old
        # config knob (lockout_exempt_loopback) could be OFF - then one
        # stale browser token locked the OWNER's own dashboard, tray and
        # extension out of their own PC for minutes (the pasted
        # "this IP is locked for another 124s" error ON 127.0.0.1).
        # The owner's PC can never lock itself out again; the config key
        # is still accepted for compatibility but is ignored here.
        exempt = loopback
        now = time.time()
        # v2.9.1 (audit L4 fix): the lockout bookkeeping below mutates
        # shared dicts from every request thread - it all runs under one
        # lock now. db_audit() is called INSIDE the lock deliberately:
        # it has its own DB lock and the throttle guarantees it is rare.
        with _AUTH_LOCK:
            lock = _AUTH_FAILS.get(ip)
            if lock and lock.get("until", 0) > now:
                if not exempt:
                    left = int(lock["until"] - now)
                    return (429, "too many failed tokens - this IP is locked"
                                 " for another %ds" % left)
                _AUTH_FAILS.pop(ip, None)   # owner IP: never stay locked
            strict = bool(CFG.get("token_header_only")) and not allow_query
            given = self.headers.get("X-AdvPrint-Token") or ""
            if not strict:
                given = given or str(qtoken or "") or str((body or {}).get("token") or "")
            if given and hmac.compare_digest(str(given), str(CFG["token"])):
                _AUTH_FAILS.pop(ip, None)   # success clears the counter
                return None
            # record the failure -> maybe lock this IP
            window = max(int(CFG.get("lockout_minutes", 5)), 1) * 60
            rec = _AUTH_FAILS.get(ip)
            if rec is None or now - rec.get("first", 0) > window:
                rec = {"count": 0, "until": 0.0, "first": now,
                       "last_audit": 0.0, "warned": False}
                _AUTH_FAILS[ip] = rec
                if len(_AUTH_FAILS) > 512:          # memory hygiene
                    for k in [k for k, v in _AUTH_FAILS.items()
                              if now - v.get("first", 0) > window][:64]:
                        _AUTH_FAILS.pop(k, None)
            rec["count"] += 1
            # audit throttle: max 1 auth.failed row per 10 s per IP - kept in
            # a side table so clearing the counter on success cannot be used
            # to re-arm it and flood the audit log
            if now - _AUTH_AUDIT_TS.get(ip, 0) >= 10:
                _AUTH_AUDIT_TS[ip] = now
                if len(_AUTH_AUDIT_TS) > 512:       # memory hygiene
                    for k in [k for k, t in _AUTH_AUDIT_TS.items()
                              if now - t > 60][:64]:
                        _AUTH_AUDIT_TS.pop(k, None)
                db_audit("auth.failed", ip=ip,
                         details="wrong token (attempt %d)" % rec["count"])
            limit = max(int(CFG.get("max_auth_failures", 10)), 1)
            if rec["count"] >= limit:
                if exempt:
                    # v2.0.1: the owner's own IP is never locked - one stale
                    # token must not take the whole PC's printing down
                    rec["count"] = 0
                    if not rec.get("warned"):
                        rec["warned"] = True
                        log("[AUTH] %d wrong tokens from loopback %s - NOT"
                            " locked (the hub PC is always exempt since"
                            " v2.6.3; use the tray menu or '%s' to fix)"
                            % (limit, ip, cli_cmd("token")))
                else:
                    mins = int(CFG.get("lockout_minutes", 5))
                    rec["until"] = now + mins * 60
                    rec["count"] = 0        # fresh count after the lock ends
                    db_audit("auth.locked", ip=ip,
                             details="IP locked for %d min after %d wrong tokens"
                                     % (mins, limit))
                    log("[AUTH] IP %s locked for %d min (%d wrong tokens)"
                        % (ip, mins, limit))
                    return (429, "too many failed tokens - this IP is locked"
                                 " for %d minutes" % mins)
            return (401, "invalid or missing token - " + self._auth_hint(given))

    def _origin_error(self):
        """403 when the browser Origin is not on the allowed list.
        Extension origins and empty origins (curl/scripts) are exempt."""
        origin = self.headers.get("Origin")
        if not origin or _extension_origin(origin):
            return None
        if origin_allowed(origin):
            return None
        return (403, "origin %s is not on the hub's allowed_origins list"
                     % origin[:100])

    def _lan_share_url(self, kind="send"):
        """v2.8.1: the LAN URL another device uses to reach this hub.
        kind=send   -> http://<lan-ip>:<port>/send?token=<hub-token>
        kind=invite -> http://<lan-ip>:<port>/connect?t=<hub-token>&n=<host>
        Both carry the hub token BY DESIGN: the token is what authorises
        printing, and the URL is only ever shown to the hub's own owner
        (authed dashboard) or embedded in the QR they choose to share."""
        return lan_share_url(kind)

    def _html_response(self, code, body):
        """HTML page answer with no-store (invite / connect pages)."""
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _peer_connect(self):
        """v2.8.1: POST target of the one-click invite. Runs on the
        RECEIVING PC's hub, saves the inviting PC into peer_hubs.
        See the security model comment above connect_page_html()."""
        if not self._is_loopback():
            return self._html_response(403, peer_connect_result_html(
                False, "Not allowed",
                ["This endpoint only accepts connections from the hub's"
                 " own PC (loopback)."], show_dashboard=False))
        try:
            raw = read_raw_body(self).decode("utf-8", "replace")
        except Exception:
            raw = ""
        form = {}
        for k, v in parse_qs(raw, keep_blank_values=True).items():
            form[k] = v[0]
        url = str(form.get("url") or "").strip()
        token = str(form.get("token") or "").strip()
        name = str(form.get("name") or "").strip()[:60]
        ip = self._client_ip()

        # CSRF guard: a browser always sends Origin on a cross-site POST;
        # it must be exactly the hub being added. Empty Origin (local
        # scripts) is accepted - same trust level as /token/current.
        origin = (self.headers.get("Origin") or "").strip()
        if origin and origin.lower() != "null":
            o = urlparse(origin)
            u = urlparse(url)
            if (o.netloc or "").lower() != (u.netloc or "").lower() or \
                    (o.scheme or "").lower() not in ("http", "https"):
                db_audit("peer.connect.denied", ip=ip,
                         details="origin %s does not match peer url"
                                 % origin[:100])
                log("[PEER] DENIED peer-connect: Origin %s != %s"
                    % (origin[:80], (u.netloc or "?")[:80]))
                return self._html_response(403, peer_connect_result_html(
                    False, "Blocked",
                    ["The page that sent this request (%s) is not the hub"
                     " it wants to add (%s). Nothing was saved."
                     % (origin[:80], (u.netloc or "?")[:80])],
                    show_dashboard=False))

        # validate the peer URL: http(s) + private-LAN host only
        u = urlparse(url)
        host = (u.hostname or "").lower()
        ok_host = False
        if u.scheme in ("http", "https") and host:
            if host in ("localhost",) or host.endswith(".local"):
                ok_host = True
            elif host.startswith("127."):
                ok_host = True
            elif host.startswith("10.") or host.startswith("192.168."):
                ok_host = True
            elif host.startswith("172."):
                try:
                    second = int(host.split(".")[1])
                    ok_host = 16 <= second <= 31
                except (ValueError, IndexError):
                    ok_host = False
            elif host.startswith("169.254."):
                ok_host = True
        if not ok_host:
            return self._html_response(400, peer_connect_result_html(
                False, "Invalid peer address",
                ["'%s' is not a private-LAN AdvPrint hub URL." % url[:100]],
                show_dashboard=False))
        if not token or len(token) > 128:
            return self._html_response(400, peer_connect_result_html(
                False, "Invalid invite",
                ["The invite link carried no usable token."],
                show_dashboard=False))
        norm = "%s://%s" % (u.scheme.lower(), u.netloc.lower())
        # v3.3.0 BUG 1: never let a hub add ITSELF. The invite carries no
        # "which hub" marker beyond its own address, so a user who opened
        # the link on the hub PC (own LAN IP or localhost) ended up with a
        # peer_hubs entry pointing the hub at ITSELF - the "it redirects
        # own pc" report. If the peer URL is THIS hub, refuse with
        # instructions instead of writing garbage config.
        _ph = (u.hostname or "").lower().rstrip(".")
        _own = {"localhost", "127.0.0.1", "::1"}
        try:
            _own.add(str(lan_ip() or "").lower())
        except Exception:
            pass
        try:
            _own.add(socket.gethostname().lower())
        except Exception:
            pass
        try:
            for _o in list_lan_ips():
                _own.add(str(_o).lower())
        except Exception:
            pass
        if _ph and _ph in _own and \
                (u.port or int(CFG.get("port", 9235))) == \
                int(CFG.get("port", 9235)):
            db_audit("peer.connect.denied", ip=ip,
                     details="self-invite blocked: %s" % url[:100])
            log("[PEER] DENIED self-invite (%s) - the invite was opened"
                " on the hub PC itself" % url[:80])
            return self._html_response(400, peer_connect_result_html(
                False, "That is this hub's own invite",
                ["You opened the invite link ON the hub PC itself - the"
                 " entry would point this hub at ITSELF, so nothing was"
                 " saved.",
                 "Open the link on the OTHER PC you want to print FROM"
                 " (any browser there) and click the connect button on"
                 " that page.",
                 "Tip: the invite URL is on the hub console - LAN"
                 " Sharing > Connect another PC > Copy invite link."],
                show_dashboard=False))
        # dedupe: same peer URL -> replace the entry.
        # v3.3.3 POPUP FIX: if the SAME hub is already paired as the
        # Connections "lan-pc" entry, the invite must UPDATE that entry
        # in place (keep the lan-pc name). The old code deleted the
        # lan-pc entry and appended a plain host-named one, so Share
        # Send Mode silently lost its pairing and the switch answered
        # "Connect the LAN PC first" even though the SAME PC was still
        # connected - the v3.3.2 popup report.
        was_lan_pc = any(
            str(p.get("name") or "") == LAN_PC_PEER_NAME and
            _peer_url_norm(p.get("url")) == _peer_url_norm(norm)
            for p in (CFG.get("peer_hubs") or []))
        peers = [p for p in (CFG.get("peer_hubs") or [])
                 if _peer_url_norm(p.get("url"))
                 != _peer_url_norm(norm)]
        entry = {"url": "%s://%s" % (u.scheme, u.netloc), "token": token,
                 "name": LAN_PC_PEER_NAME if was_lan_pc
                 else (name or host)}
        # friendly live check (never blocks the save)
        ver, note = None, ""
        try:
            req = urllib.request.Request(
                norm + "/health",
                headers={"User-Agent": "AdvPrintPro/%s" % VERSION})
            with urllib.request.urlopen(req, timeout=3) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            ver = data.get("version")
            if not data.get("share_lan"):
                note = ("Warning: that hub currently has LAN sharing OFF,"
                        " so it will not accept jobs until it is enabled.")
        except Exception:
            note = ("Warning: the peer did not answer a health check just"
                    " now - it may be offline or the firewall may block"
                    " port %d. The peer was saved anyway." % (u.port or 9235))
        if ver:
            entry["version"] = str(ver)[:20]
        peers.append(entry)
        CFG["peer_hubs"] = peers
        try:
            write_config_file({k: CFG[k] for k in CONFIG_KEYS})
        except Exception as e:
            return self._html_response(500, peer_connect_result_html(
                False, "Could not save the peer",
                ["config.json could not be written: %s" % e],
                show_dashboard=False))
        _PEER_CACHE["t"] = 0.0                 # force a fresh probe
        db_audit("peer.connected", actor="lan", ip=ip,
                 details="peer added via invite: %s (%s) version=%s"
                         % (entry["url"], entry["name"], ver or "?"))
        log("[PEER] connected: %s (%s) v%s" % (entry["url"], entry["name"],
                                               ver or "?"))
        lines = ["%s is now in your LAN print peers." % entry["name"],
                 "Hub URL: %s" % entry["url"]]
        if ver:
            lines.append("Peer hub is online, running AdvPrint Pro v%s."
                         % ver)
        if note:
            lines.append(note)
        lines.append("Open the dashboard LAN card to shift waiting jobs"
                     " to it (and to remove the peer again).")
        return self._html_response(200, peer_connect_result_html(
            True, "Connected!", lines))

    # ---- routes ----
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # v2.6.4 NEVER-EMPTY-RESPONSE GUARANTEE. Every request is wrapped:
    # if ANY handler raises (a bug, a broken disk, a bad config value...),
    # the client now gets a readable JSON 500 (or the HTML error page for
    # browsers) instead of the connection dying with Chrome's
    # ERR_EMPTY_RESPONSE - and the traceback lands in hub.log + /debug so
    # the cause is always visible. (The v2.6.3 field incident: a missing
    # `winreg` import killed /debug + /diagnostics exactly this way.)
    def do_GET(self):
        try:
            # v2.9.1 (audit H5 fix): every request must name THIS hub in
            # its Host header (DNS-rebinding protection)
            if not self._host_ok():
                return self._host_error()
            # v3.2.3 ALLOWED IPS - the network-level gate (before auth)
            if not self._ip_gate():
                return
            # v3.2.6 UI SECURITY GATE - non-local clients get the print
            # surface only; the console UI + management endpoints are
            # local-only ("only own ip or loopback ip can show ui")
            if self._mgmt_locked(self.path.split("?")[0].rstrip("/") or "/"):
                return self._ui_locked_answer(
                    self.path.split("?")[0].rstrip("/") or "/")
            return self._do_get_impl()
        except (BrokenPipeError, ConnectionResetError):
            pass                          # client hung up - fine
        except Exception:
            self._internal_error("GET")

    def do_POST(self):
        try:
            # v2.9.1 (audit H5 fix): same Host rule for POSTs
            if not self._host_ok():
                return self._host_error()
            # v3.2.3 ALLOWED IPS - same gate for mutating calls
            if not self._ip_gate():
                return
            # v3.2.6 UI SECURITY GATE - same rule for mutating calls
            if self._mgmt_locked(self.path.split("?")[0].rstrip("/") or "/"):
                return self._ui_locked_answer(
                    self.path.split("?")[0].rstrip("/") or "/")
            return self._do_post_impl()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._internal_error("POST")

    def _internal_error(self, method):
        """Last-resort answer for an unexpected handler exception."""
        try:
            import traceback
            tb = traceback.format_exc()
            log("[ERROR] %s %s crashed:" % (method, self.path.split("?")[0]))
            for line in tb.strip().splitlines():
                log("        " + line)
            try:
                db_audit("error", details="%s %s failed: %s"
                         % (method, self.path.split("?")[0],
                            tb.strip().splitlines()[-1][:160]),
                         ip=self._client_ip())
            except Exception:
                pass
            msg = {"ok": False, "error": "internal error - see hub.log"
                   " (the traceback was logged; this is an AdvPrint Pro"
                   " bug, please report the log tail)"}
            if "text/html" in (self.headers.get("Accept") or ""):
                page = ("<html><head><meta charset=\"utf-8\">"
                        "<title>AdvPrint Pro - internal error</title></head>"
                        "<body style=\"font-family:Segoe UI,sans-serif;"
                        "background:#f5f8fc;color:#0f172a;padding:40px\">"
                        "<h2 style=\"color:#dc2626\">AdvPrint Pro -"
                        " internal error</h2>"
                        "<p>This page crashed inside the hub. It has been"
                        " logged to <code>hub.log</code>.</p>"
                        "<p>Printing and the rest of the hub keep"
                        " working. Please send the last 20 lines of"
                        " hub.log when asking for help.</p>"
                        "<p><a href=\"/dashboard\">Back to the"
                        " dashboard</a></p></body></html>").encode("utf-8")
                self.send_response(500)
                self._cors()
                self.send_header("Content-Type",
                                 "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                try:
                    self.wfile.write(page)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            self._send(500, msg)
        except Exception:
            pass                          # even the rescue must not raise

    def _loopback_token_redirect(self, route, query):
        """v2.6.4 ONE-CLICK-FREE TOKEN REPAIR for the owner's browser.
        When a browser navigates (Accept: text/html) to /dashboard, /docs
        or any GET page with a STALE token - an old bookmark, an old
        popup link, a token the hub rotated - and the request comes from
        the hub PC itself (loopback), the hub answers 302 to the SAME
        page with the CURRENT token instead of an error page. Same trust
        level as /token/current (which hands the token to loopback
        callers anyway); remote IPs and API clients (fetch sends
        Accept: */*) keep the strict 401 + lockout rules untouched."""
        if not CFG.get("token") or not self._is_loopback():
            return False
        if "text/html" not in (self.headers.get("Accept") or ""):
            return False
        parts = []
        for k, vals in (query or {}).items():
            if k == "token":
                continue
            for v in vals:
                parts.append("%s=%s" % (quote(str(k)), quote(str(v))))
        loc = route + "?token=" + quote(CFG["token"])
        if parts:
            loc += "&" + "&".join(parts)
        try:
            self.send_response(302)
            self._cors()
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass
        log("[AUTH] loopback %s had a stale/missing token - redirected"
            " to the current one (302 auto-repair)" % route)
        return True

    def _do_get_impl(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        qt = (q.get("token") or [""])[0]
        route = u.path.rstrip("/") or "/"
        # v2.0.2 auth rule (fixes the /audit vs /dashboard mismatch):
        # EVERY GET endpoint accepts ?token= for plain browser navigation
        # - browsers cannot send the X-AdvPrint-Token header, and a token
        # that opens /dashboard must equally open /audit, /stats, /jobs.
        # Mutating calls (POST) still require the header in header-only
        # mode, so the extension/API hardening is not weakened.

        if route == "/health":                        # open: INSTANT snapshot
            # v2.6.3: serves the precomputed snapshot (refreshed every 3 s
            # by the background refresher). The old code ran up to THREE
            # PowerShell/WMI scans on this route (default_printer +
            # printers_status + list), each with a 20 s timeout - the
            # first probe after boot could block longer than every client
            # (console tool polls 20 s, extension popup even less), so
            # the hub looked "listening but not answering" and the
            # extension showed OFFLINE. /health never blocks on anything
            # now - even a cold or AV-slowed WMI cannot touch it.
            return self._send(200, health_snapshot())

        # ---- v3.0.7 SELF-HOST extension server (OPEN endpoints:
        # Chrome's updater sends no token; the Host rule above already
        # limits these to localhost / LAN callers) ----
        if route == "/extension/updates.xml":
            c = crx_package()
            if not c:
                return self._send(404, {
                    "ok": False,
                    "error": "no extension package found (missing"
                             " extension/" + EXT_CRX_NAME + ")"})
            host = (self.headers.get("Host") or "127.0.0.1:%d"
                    % int(CFG.get("port", 9235))).strip()
            if not re.match(r"^[A-Za-z0-9.:\[\]-]+$", host):
                host = "127.0.0.1:%d" % int(CFG.get("port", 9235))
            base = "http://" + host
            xml = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                   "<gupdate xmlns='http://www.google.com/update2/response'"
                   " protocol='2.0'>\n"
                   "  <app appid='%s'>\n"
                   "    <updatecheck codebase='%s/extension/%s'"
                   " version='%s' />\n"
                   "  </app>\n"
                   "</gupdate>\n"
                   % (c["ext_id"], base, EXT_CRX_NAME, c["version"]))
            body = xml.encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        if route == "/extension/" + EXT_CRX_NAME:
            c = crx_package()
            if not c:
                return self._send(404, {
                    "ok": False,
                    "error": "no extension package found (missing"
                             " extension/" + EXT_CRX_NAME + ")"})
            self.send_response(200)
            self._cors()
            # REQUIRED: Chromium only treats the download as an
            # installable extension with this exact Content-Type
            # (missing it = policy install silently fails).
            self.send_header("Content-Type",
                             "application/x-chrome-extension")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(c["data"])))
            self.end_headers()
            try:
                self.wfile.write(c["data"])
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        if route == "/extension/info":
            c = crx_package()
            return self._send(200, {
                "ok": True,
                "served": bool(c),
                "extension_id": c["ext_id"] if c else EXT_CRX_ID,
                "version": c["version"] if c else None,
                "hub_version": VERSION,
                "stale": bool(c) and _ver_lt(c["version"], VERSION),
                "updates_url": ("http://127.0.0.1:%d/extension/updates.xml"
                                % int(CFG.get("port", 9235))),
                "crx_url": ("http://127.0.0.1:%d/extension/%s"
                            % (int(CFG.get("port", 9235)), EXT_CRX_NAME)),
                "forcelist_value": ext_forcelist_value(),
                "note": "Chrome installs silently on managed"
                        " (domain/enrolled) PCs via"
                        " ExtensionInstallForcelist; on a home PC use"
                        " chrome://extensions > Load unpacked"})

        if route == "/extension":
            c = crx_package()
            # v3.2.8 STALE-CRX GUARD: an embedded package older than the
            # hub means every paired browser is stuck on the OLD
            # extension (Chrome only updates when updates.xml shows a
            # HIGHER version). Say so, loudly, right on this page.
            stale = bool(c) and _ver_lt(c["version"], VERSION)
            stale_html = "" if not stale else (
                "<p style='background:#fef2f2;border:1px solid #fecaca;"
                "color:#991b1b;border-radius:8px;padding:12px 16px;"
                "font-size:14px'><b>&#9888; Stale package - your browsers"
                " are NOT auto-updating.</b> This hub serves extension"
                " <b>v%s</b> but the hub itself is <b>v%s</b>. Chrome"
                " checks updates.xml, sees no higher version and keeps"
                " the old extension running (old bugs included). Fix:"
                " re-run the AdvPrint Pro Setup, or copy the current"
                " <code>AdvPrint-Pro.crx</code> from the release package"
                " over <code>hub/extension/AdvPrint-Pro.crx</code> - no"
                " restart needed (the hub re-reads the file when it"
                " changes).</p>"
                % (c["version"], VERSION))
            page = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    "<title>AdvPrint Pro - extension server</title>"
                    "</head><body style='font-family:Segoe UI,sans-serif;"
                    "background:#f5f8fc;color:#0f172a;padding:32px'>"
                    "<h2>AdvPrint Pro - self-host extension server"
                    " (v%s)</h2>" % VERSION +
                    stale_html +
                    "<p>This hub serves its signed browser extension so"
                    " Chrome / Edge / Brave can install and update it"
                    " silently via the ExtensionInstallForcelist"
                    " policy.</p><ul>"
                    "<li><a href='/extension/updates.xml'>updates.xml"
                    "</a> - Chromium update manifest (gupdate 2.0)</li>"
                    "<li><a href='/extension/%s'>%s</a> - the signed"
                    " package (CRX3)</li>"
                    "<li><a href='/extension/info'>info</a> - JSON"
                    " (ID, version, policy value)</li></ul>"
                    "<p>Extension ID: <b>%s</b> &middot; served version:"
                    " <b>%s</b></p><p>Policy value for registry/GPO:"
                    " <code>%s;%s</code></p>"
                    "<p><a href='/dashboard'>Dashboard</a></p></body>"
                    "</html>"
                    % (EXT_CRX_NAME, EXT_CRX_NAME,
                       c["ext_id"] if c else EXT_CRX_ID,
                       c["version"] if c else "-",
                       c["ext_id"] if c else EXT_CRX_ID,
                       ext_policy_url())).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            try:
                self.wfile.write(page)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return


        # /token/current - v2.6 ONE-CLICK TOKEN FIX. Loopback ONLY: the
        # owner's own PC can always recover the dashboard (a stale
        # bookmark must never require reading config files). Remote IPs
        # always get 403 - the token never leaves the hub PC.
        # v2.6.2: answered with _send_local (Access-Control-Allow-Origin
        # is always "null") - before this, _cors() could answer
        # ACAO:* on the default config and ANY website could read the
        # token out of this endpoint. Extension keeps working (it uses
        # host_permissions, not CORS); websites are blocked again.
        if route == "/token/current":
            if not self._is_loopback():
                return self._send_local(403, {
                    "ok": False,
                    "error": "loopback only - run this on the hub PC"})
            return self._send_local(200, {"ok": True, "token": CFG["token"],
                                          "app": APP_NAME,
                                          "version": VERSION})

        # /dashboard - browser page with its own early auth so browser
        # users always get the HTML error page (v2.0.2: /audit, /stats
        # and every other GET accept ?token= too - see the generic rule)

        # v3.1.2 THE ONE UI - /ui serves console.html (the Windows-IDM
        # style console: Dashboard / Printers / Jobs / Audit / IPP
        # Printer / Extension / Settings / Logs). Same auth as the
        # classic dashboard (token via ?token=, header or the loopback
        # redirect). The page is loaded from disk NEXT TO advprint.py
        # so the installer / deb payload ships it; when the file is
        # missing the hub serves a small fallback page pointing at the
        # classic dashboard.
        if route == "/ui":
            err = self._auth_error(qt, allow_query=True)
            if err:
                if self._loopback_token_redirect(route, q):
                    return
                if "text/html" in (self.headers.get("Accept") or ""):
                    page = dashboard_auth_error_html(err[1]).encode("utf-8")
                    self.send_response(err[0])
                    self._cors()
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    try:
                        self.wfile.write(page)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                return self._send(err[0], {"ok": False, "error": err[1]})
            # v3.2.0: SELF PC UI for the owner (loopback), CENTER PC UI
            # for every LAN PC that opens the share URL. ?view=self|center
            # overrides (useful for previews / screenshots).
            view = (q.get("view") or [""])[0].lower()
            if view not in ("self", "center"):
                view = "self" if self._is_loopback() else "center"
            page = console_page_bytes(view, req_host=self._req_host(),
                                      req_port=self._req_port(),
                                      client_ip=self._client_ip())
            if page is None:
                page = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                        "<title>AdvPrint Pro Console</title></head><body"
                        " style='font:15px/1.6 Segoe UI,system-ui,sans-serif;"
                        "background:#f5f8fc;color:#0f172a;padding:8vh 24px'>"
                        "<div style='max-width:560px;margin:0 auto;background:"
                        "#fff;border:1px solid #e2e8f0;border-radius:14px;"
                        "padding:24px'><h1 style='color:#1d4ed8;font-size:19px'"
                        ">AdvPrint Pro Console</h1><p>The All-in-One console UI is"
                        " embedded inside advprint.py; this build"
                        " looks damaged.</p><p>"
                        "Please re-install AdvPrint Pro, or open the classic"
                        " dashboard: <a href='/dashboard?token=%s'>"
                        "/dashboard</a></p></div></body></html>"
                        % urllib.parse.quote(qt or "")).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            try:
                self.wfile.write(page)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        if route == "/dashboard":
            err = self._auth_error(qt, allow_query=True)
            if err:
                # v2.6.4: the owner's own browser with an old bookmark
                # is redirected to the working URL (no error page)
                if self._loopback_token_redirect(route, q):
                    return
                # v2.0.1: browsers get a readable HTML page with fix
                # instructions instead of a raw JSON blob
                if "text/html" in (self.headers.get("Accept") or ""):
                    page = dashboard_auth_error_html(err[1]).encode("utf-8")
                    self.send_response(err[0])
                    self._cors()
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    try:
                        self.wfile.write(page)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                return self._send(err[0], {"ok": False, "error": err[1]})
            # v3.2.0 THE ONE UI: /dashboard answers with the SAME approved
            # console.html as /ui (self view for the owner, center view for
            # LAN PCs). The classic dashboard page stays in the code
            # (dashboard_html()) for tests / embedding but is no longer the
            # browser answer - ONE UI, no separate URLs.
            view = (q.get("view") or [""])[0].lower()
            if view not in ("self", "center"):
                view = "self" if self._is_loopback() else "center"
            html = console_page_bytes(view, req_host=self._req_host(),
                                      req_port=self._req_port(),
                                      client_ip=self._client_ip())
            if html is None:
                html = dashboard_html(u.query).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            try:
                self.wfile.write(html)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        # /docs - v2.2: the full user guide served BY the hub, so the
        # documentation is always where the product is (same token rule
        # as the dashboard, browsers get HTML)
        if route == "/docs":
            err = self._auth_error(qt, allow_query=True)
            if err:
                if self._loopback_token_redirect(route, q):
                    return
                if "text/html" in (self.headers.get("Accept") or ""):
                    page = dashboard_auth_error_html(err[1]).encode("utf-8")
                    self.send_response(err[0])
                    self._cors()
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    try:
                        self.wfile.write(page)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                return self._send(err[0], {"ok": False, "error": err[1]})
            page = docs_html().encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            try:
                self.wfile.write(page)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        # /connect - v2.8.1 ONE-CLICK LAN INVITE landing page. Opened on
        # the OTHER PC's browser; carries THIS hub's token as ?t=... and
        # validates itself (no hub-token auth: the receiving PC does not
        # know this hub's token yet - that is the whole point). Wrong or
        # stale t -> readable error page, no data exposure.
        if route == "/connect":
            it = (q.get("t") or [""])[0]
            iname = (q.get("n") or [""])[0]
            if not CFG.get("token") or \
                    not hmac.compare_digest(str(it), str(CFG["token"])):
                # v3.3.0 BUG 1: the old text blamed an "old or mistyped"
                # link - but the REAL confusion (user report) is opening
                # the invite on the WRONG PC: every AdvPrint hub has its
                # own token, so a token copied from a DIFFERENT PC's
                # console fails exactly like a stale one. Say both.
                page = connect_error_html(
                    "The ?t= parameter does not match THIS hub's token -"
                    " the invite link is old, mistyped, or it belongs to"
                    " a DIFFERENT PC's hub. Every AdvPrint Pro hub has"
                    " its own token: open the invite link that was"
                    " copied on the PC you want to CONNECT TO (its"
                    " console > LAN Sharing > Connect another PC > Copy"
                    " invite link).").encode("utf-8")
                self.send_response(403)
                self._cors()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                try:
                    self.wfile.write(page)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if not CFG.get("share_lan"):
                page = connect_error_html(
                    "LAN sharing is currently OFF on this hub - enable it"
                    " first (dashboard > LAN card > Enable).").encode("utf-8")
                self.send_response(403)
                self._cors()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                try:
                    self.wfile.write(page)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            db_audit("peer.invite", actor="lan", ip=self._client_ip(),
                     details="invite page opened (peer name=%s)"
                             % str(iname or "?")[:60])
            # v3.3.0 BUG 1: the page is built from the address the VISITOR
            # actually used (Host header), not the serving PC's lan_ip()
            # guess - and when the visitor IS the hub PC itself (loopback)
            # it gets the self-invite explainer instead of a form that
            # would add this hub to itself.
            page = connect_page_html(
                str(it), iname,
                req_host=self._req_host(), req_port=self._req_port(),
                visitor_is_hub=self._is_loopback()).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            try:
                self.wfile.write(page)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        err = self._origin_error()
        if err:
            return self._send(err[0], {"ok": False, "error": err[1]})
        # v2.9.0: the IPP printer info page answers WITHOUT the token -
        # it is the landing page of the network-printer URL (phones and
        # Windows probe it anonymously; IPP itself is token-free too).
        # v3.0.9: /ipp/print/<printer> gets the SAME landing page for
        # that ONE per-printer queue (status + exact ipp:// URL).
        if route.startswith("/ipp/print/"):
            if not ipp_printer_enabled():
                return self._send(404, {"ok": False,
                                        "error": "IPP printer is off"})
            nm = _ipp_queue_match_cached(
                urllib.parse.unquote(route[len("/ipp/print/"):]))
            if not nm:
                # v3.3.2 BUG 3: an unknown queue gets the GENERIC landing
                # page (HTML with the how-to), not a JSON 404 - browsers
                # and phones that typed a slightly wrong name still see
                # the printer page and the exact queue list.
                return self._send_html(200, ipp_landing_html(
                    req_host=self._req_host(), req_port=self._req_port()))
            host = socket.gethostname()
            # v3.2.9 BUG 3: the ipp:// URL on the queue landing page uses
            # the address THE OPENING DEVICE used, so every LAN PC sees
            # its own reachable ip:port for THIS printer.
            q_url = ipp_queue_url(nm, host=self._req_host())
            st = printers_status_cached().get(nm, "unknown")
            return self._send_html(200, """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport"
 content="width=device-width,initial-scale=1"><title>AdvPrint Pro - IPP queue %s</title>
<style>body{font:15px/1.55 "Segoe UI",system-ui,sans-serif;background:#f5f8fc;
 color:#0f172a;margin:0;padding:24px}.b{max-width:640px;margin:4vh auto;background:#fff;
 border:1px solid #e2e8f0;border-radius:14px;padding:22px}
 h1{font-size:19px;margin:0 0 6px}h2{font-size:15px;margin:18px 0 6px;color:#1d4ed8}
 code{background:#f1f5f9;border:1px solid #e2e8f0;border-radius:4px;padding:1px 6px;
 font-size:12.5px;word-break:break-all}li{margin:5px 0}
 .ok{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:10px 14px;
 margin:14px 0;font-size:13.5px}</style></head><body><div class="b">
 <h1>AdvPrint Pro - IPP queue &ldquo;%s&rdquo;</h1>
 <p>This per-printer queue (v3.0.9) prints <b>only on <span>%s</span></b>
 attached to <span>%s</span>. Add it as a printer - do not open it in a browser:</p>
 <p style="font-size:16px"><code>%s</code></p>
 <p>Printer state right now: <b>%s</b>.</p>
 <h2>Windows 10 / 11</h2>
 <ul><li>Settings &rarr; Bluetooth &amp; devices &rarr; Printers &amp;
 scanners &rarr; <b>Add device</b> - the queue announces itself by
 mDNS while LAN sharing is on - click it.</li>
 <li>Or: <b>Add manually</b> &rarr; &ldquo;Select a shared printer by
 name&rdquo; &rarr; paste <code>%s</code>.</li></ul>
 <h2>Linux / CUPS</h2>
 <ul><li><code>lpadmin -p advprint-%s -E -v %s -m everywhere</code></li></ul>
 <div class="ok"><b>The hub is the central IPP middleware</b> - child
 PCs, phones and tablets print through this ONE center PC without
 installing anything. 100%% local - powered by AdvPrint Pro %s.</div>
 </div></body></html>
""" % (_html_escape(_ipp_queue_slug(nm)),
                             _html_escape(nm),
                             _html_escape(nm),
                             _html_escape(host),
                             _html_escape(q_url, quote=True),
                             _html_escape(st),
                             _html_escape(q_url, quote=True),
                             _html_escape(_ipp_queue_slug(nm)),
                             _html_escape(q_url, quote=True),
                             VERSION))
        if route in ("/ipp/print", "/ipp", "/ipp/") and \
                not ipp_printer_enabled():
            return self._send(404, {"ok": False,
                                    "error": "IPP printer is off"})
        if route in ("/ipp/print", "/ipp", "/ipp/"):
            # v2.9.0: humans who open the IPP printer URL in a browser
            # get a how-to page (IPP clients POST binary IPP instead).
            # v3.0.8: per-OS cheat sheet. v3.2.2: shared with the
            # standard-port mirror (ipp631) via ipp_landing_html().
            # v3.2.9 BUG 3: the page shows the address THIS device used.
            return self._send_html(200, ipp_landing_html(
                req_host=self._req_host(), req_port=self._req_port()))
        err = self._auth_error(qt, allow_query=True)   # v2.0.2: every GET
        if err:
            if self._loopback_token_redirect(route, q):
                return
            # v2.0.2: a browser that followed a link gets the same
            # readable HTML error page as the dashboard; API clients
            # (fetch/curl) keep the JSON error
            if "text/html" in (self.headers.get("Accept") or ""):
                page = dashboard_auth_error_html(err[1]).encode("utf-8")
                self.send_response(err[0])
                self._cors()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                try:
                    self.wfile.write(page)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            return self._send(err[0], {"ok": False, "error": err[1]})

        if route == "/":
            # v3.2.0 THE ONE UI: a BROWSER opening the hub root gets the
            # same All-in-One console (self view on the hub PC, center view
            # from the LAN) - no separate URL to remember. API clients
            # (no Accept: text/html) still get the JSON endpoint index.
            if "text/html" in (self.headers.get("Accept") or ""):
                err = self._auth_error(qt, allow_query=True)
                if err:
                    if self._loopback_token_redirect(route, q):
                        return
                    page = dashboard_auth_error_html(err[1]).encode("utf-8")
                    self.send_response(err[0])
                    self._cors()
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    try:
                        self.wfile.write(page)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                view = (q.get("view") or [""])[0].lower()
                if view not in ("self", "center"):
                    view = "self" if self._is_loopback() else "center"
                html = console_page_bytes(view, req_host=self._req_host(),
                                          req_port=self._req_port(),
                                          client_ip=self._client_ip())
                if html is None:
                    html = dashboard_html(u.query).encode("utf-8")
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                try:
                    self.wfile.write(html)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            return self._send(200, {
                "app": APP_NAME, "version": VERSION, "by": VENDOR,
                "branding": BRANDING,
                "endpoints": ["/health", "/dashboard?token=...",
                              "/printers", "/jobs[?status=]", "/jobs/{id}/file",
                              "/jobs/{id}/reprint (POST)", "/jobs/{id}/cancel (POST)",
                              "/jobs/{id}/retry (POST, failed/dead jobs)",
                              "/jobs/{id}/priority (POST {priority:1-9})",
                              "/print (POST) [&queue=false] [+priority,run_at,"
                              "profile,pages,duplex,paper,tray,reason,watermark,raw]",
                              "/queue (GET)", "/queue/pause|resume|clear (POST)",
                              "/debug", "/debug/report (POST - client errors)",
                              "/autostart (GET) + /autostart (POST)",
                              "/testprint?kind=a4|thermal",
                              "/stats", "/audit[?event=]", "/audit.csv",
                              "/export/history.csv", "/export/audit.csv",
                              "/diagnostics", "/config (GET/POST)",
                              "/token/rotate (POST)", "/token/current",
                              "/livetest (POST)", "/peers",
                              "/ui (v3.2.0 THE ONE UI - the approved IDM All-in-One console; / and /dashboard serve the SAME page),"
                              "/dropzone (GET) + /dropzone/open (POST),"
                              " /send (GET portal, POST upload),"
                              " /qr (GET QR SVG, kind=send|invite|ipp),"
                              " /connect (GET invite page),"
                              " /peer-connect (POST auto-add peer),"
                              " /ipp/print (v2.9 IPP network printer),"
                              " /restart (POST) - v2.8/v2.8.1/v2.9"],
            })
        if route == "/printers":
            dp = default_printer_cached()
            st = printers_status_cached()
            groups = CFG.get("printer_groups") or {}
            # v3.0.9: every local printer also carries its own per-printer
            # IPP queue URL - ipp://ip:9235/ipp/print/<printer> - so child
            # PCs / phones can add ONE printer of the center PC directly.
            # v3.2.9 BUG 3: the URL is built per REQUEST with the address
            # the asking device used (Host header) - a LAN PC copying the
            # queue from its own console always gets ITS reachable URL.
            per_printer = ipp_printer_enabled()
            _req_h = self._req_host()
            items = []
            for n in list_printers_cached():
                item = {"name": n, "is_default": n == dp,
                        "status": st.get(n, "unknown"),
                        "is_group": False}
                if per_printer:
                    item["ipp_queue"] = ipp_queue_url(n, host=_req_h)
                    # v3.2.6 BUG FIX 2: return the BARE queue slug. The
                    # console used to prepend "/ipp/print" to this value
                    # AND the value itself started with "ipp/print/",
                    # producing the doubled
                    # /ipp/print/ipp/print/<printer>?token=... URL on
                    # the printer Details button.
                    item["ipp_path"] = _ipp_queue_slug(n)
                items.append(item)
            for g in groups:
                items.append({"name": g, "is_default": False,
                              "status": "group",
                              "is_group": True,
                              "members": groups[g]})
            return self._send(200, {
                "ok": True, "printers": items, "default": dp,
                "groups": groups,
                "ipp_per_printer": per_printer,
                "ipp_central_url": lan_share_url("ipp")
                                   if per_printer else ""})
        if route.startswith("/printers/") and route.endswith("/capabilities"):
            name = urllib.parse.unquote(
                route[len("/printers/"):-len("/capabilities")])
            return self._send(200, printer_capabilities(name))
        if route == "/autostart":
            return self._send(200, {
                "ok": True, "enabled": autostart_enabled(),
                "path": autostart_path(),
                "hint": "POST {\"enabled\": true|false} to change"
                        " (same toggle as the tray icon menu)"})
        if route == "/queue":
            cur = None
            with _CURRENT_LOCK:
                if _CURRENT["id"]:
                    cur = db_get(_CURRENT["id"])
            return self._send(200, {
                "ok": True,
                "paused": not RESUME_EVENT.is_set(),
                "pending": db_count_pending(),
                "held": db_count_held(),
                "current": cur})
        if route == "/jobs":
            # v2.9.1 (audit L5 fix): clamp the limit (the old int() accepted
            # ?limit=999999999 and made the hub serialize the whole table)
            try:
                limit = int((q.get("limit") or [str(HISTORY_DEFAULT)])[0])
            except (TypeError, ValueError):
                limit = HISTORY_DEFAULT
            limit = max(1, min(200, limit))
            status = (q.get("status") or [""])[0] or None
            return self._send(200, {"ok": True,
                                    "jobs": db_list(limit, status=status)})
        if route == "/stats":
            st = db_stats()
            _psn = printers_status_cached()
            st.update({
                "ok": True, "version": VERSION, "paused": not RESUME_EVENT.is_set(),
                "printers": _psn,
                "printers_ready": sum(1 for v in _psn.values()
                                      if v == "ready"),
                "default_token_warning": DEFAULT_TOKEN_WARNING,
                "service": service_state(),
                "uptime_s": int(time.time() - START_TS),
            })
            return self._send(200, st)
        if route == "/audit":
            try:
                limit = int((q.get("limit") or ["50"])[0])
            except (TypeError, ValueError):
                limit = 50
            limit = max(1, min(1000, limit))          # v2.9.1 (L5) clamped
            event = (q.get("event") or [""])[0] or None
            return self._send(200, {"ok": True,
                                    "entries": audit_list(limit, event)})
        if route == "/audit.csv":
            return self._csv_response("audit", audit_list(limit=5000))
        if route in ("/export/history.csv", "/history.csv"):
            return self._csv_response("jobs", db_list(limit=5000))
        if route == "/export/audit.csv":
            return self._csv_response("audit", audit_list(limit=5000))
        if route == "/diagnostics":
            return self._send(200, build_diagnostics())
        if route == "/debug":
            # v2.3: one-stop "why is nothing printing?" - the hub's own
            # verdict (worker, queue, printers, stuck jobs) PLUS the
            # error reports collected from the browser extension /
            # desktop tool. Same auth as every other GET endpoint.
            return self._send(200, build_debug_report())
        if route == "/config":
            return self._send(200, redacted_config())
        if route == "/peers":
            return self._send(200, {"ok": True, "peers": probe_peers()})
        if route == "/dropzone":                    # v2.8 DropZone status
            st = drop_stats()
            st["delete"] = bool(CFG.get("drop_delete"))
            st["custom_dir"] = (CFG.get("drop_dir") or "").strip()
            st["is_default"] = not st["custom_dir"]
            return self._send(200, st)
        if route == "/lan/selftest":                # v2.8.2 one-click check
            # Answers "why can the other PC not connect?": the hub tests
            # its own LAN URL server-side. A PASS proves the listener is
            # reachable on the LAN IP of THIS PC - a DIFFERENT PC that
            # still fails is the firewall (click 'Allow in firewall').
            u = "http://%s:%d/health" % (lan_ip(), CFG["port"])
            try:
                with urllib.request.urlopen(u, timeout=5) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
                res = {"ok": True, "url": u,
                       "version": data.get("version"),
                       "note": "the listener answers on this PC's LAN IP; "
                               "if a DIFFERENT PC still cannot connect, "
                               "allow TCP %d in the firewall"
                               % CFG["port"]}
            except Exception as e:
                res = {"ok": False, "url": u, "error": str(e),
                       "hint": "the LAN listener is not answering - "
                               "toggle LAN sharing off/on, then check "
                               "hub.log"}
            return self._send(200, res)
        if route == "/send":                        # v2.8 send portal page
            tok = qt or CFG["token"]
            return self._send_html(200, send_portal_html(tok))
        if route == "/qr":                          # v2.8.1 QR code SVG
            # kind=send (default) -> the LAN Send-portal URL with token;
            # kind=invite          -> the one-click /connect invite link.
            # kind=ipp (v2.9)      -> the IPP printer URL (no token).
            # v3.2.6 BUG FIX 5 - the ipp QR MUST encode the http:// URL:
            # phone browsers cannot open ipp:// (they Google-search it),
            # so the SCANNABLE payload is always
            #   http://<ip>:<port>/ipp/print
            # while the console modal DISPLAYS and COPIES the ipp:// URL
            # that Windows / macOS / CUPS expect for "add a printer".
            # (lan_share_url("ipp") already returns http:// - the rule is
            # pinned here explicitly and locked by tests/test_v326.py.)
            # Auth like every GET (?token= works), answer is an SVG image
            # that the dashboard <img> tag (and any phone camera) reads.
            kind = (q.get("kind") or ["send"])[0]
            if kind not in ("send", "invite", "ipp", "hub"):
                kind = "send"
            if kind == "hub":       # v3.2.1: THE ONE UI console itself
                url = "%s/?token=%s" % (
                    (("http://%s:%d" % (lan_ip(), CFG["port"]))
                     if CFG.get("share_lan")
                     else ("http://127.0.0.1:%d" % CFG["port"])),
                    quote(str(CFG["token"] or "")))
            elif kind == "ipp":     # v3.2.6: http:// goes INTO the QR
                url = "http://%s:%d/ipp/print" % (
                    lan_ip() if CFG.get("share_lan") else "127.0.0.1",
                    int(CFG.get("port", 9235)))
            else:
                url = self._lan_share_url(kind)
            svg = qr_svg(url.encode("utf-8")).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(svg)))
            self.end_headers()
            try:
                self.wfile.write(svg)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if route == "/testprint":
            kind = (q.get("kind") or ["a4"])[0]
            if kind not in ("a4", "thermal"):
                kind = "a4"
            if kind == "thermal":
                data, _ = thermal_pdf_bytes(
                    "#big AdvPrint Pro\n|center|Bit Dream IT - TEST RECEIPT\n"
                    "--------------------------------\n"
                    "Item 1              10.00\nItem 2              25.50\n"
                    "--------------------------------\n"
                    "TOTAL               35.50\n\n"
                    "|center|Thank you!\n", "testprint")
                title = "test-thermal"
            else:
                data, _ = thermal_pdf_bytes(
                    "#big AdvPrint Pro - A4 TEST"
                    "\n\nIf this page came out of your printer,"
                    "\nthe hub is working perfectly."
                    "\n\nTime: %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "testprint", paper="a4")
                title = "test-a4"
            job, dup = enqueue_print(kind, title, data, dedupe=False,
                                     origin_ip=self._client_ip(),
                                     site=self._request_site())
            db_audit("print.submitted", job_id=job, actor="api",
                     site=self._request_site(), ip=self._client_ip(),
                     doc_hash=hashlib.sha256(data).hexdigest())
            return self._send(200, {"ok": True, "job_id": job, "kind": kind,
                                    "message": "queued - check your printer"})
        if route.startswith("/jobs/"):
            parts = route.strip("/").split("/")
            if len(parts) == 2 and parts[1].isdigit():
                j = db_get(int(parts[1]))
                if not j:
                    return self._send(404, {"ok": False,
                                            "error": "job not found"})
                return self._send(200, {"ok": True, "job": j})
            if len(parts) == 3 and parts[2] == "file":
                j = db_get(int(parts[1]) if parts[1].isdigit() else 0)
                if j and j.get("file_path") and os.path.exists(j["file_path"]):
                    ctype = ("application/octet-stream"
                             if j.get("kind") == "raw" else "application/pdf")
                    return self._send_file(j["file_path"],
                                           "advprint-job-%d.%s"
                                           % (j["id"], "prn"
                                              if j.get("kind") == "raw"
                                              else "pdf"), ctype)
                return self._send(404, {"ok": False,
                                        "error": "job or file not found"})
        if route == "/extension/policy/status":
            return self._send(200, ext_policy_status())
        # GET /peer/status - v3.3.2: the LAN PC card's state. Persisted
        # pairing (url + label, token never returned) + a FRESH probe of
        # the other PC (version, LAN sharing / IP printer states, its
        # printer list) + the Share Send Mode switch state. The card
        # renders from this on every poll, so a reload / hub restart
        # always shows the truth instead of a stale demo chip.
        if route == "/peer/status":
            return self._send(200, _lan_peer_status())
        return self._send(404, {"ok": False, "error": "unknown endpoint"})

    def _csv_response(self, which, rows):
        if which == "audit":
            cols = ["id", "ts", "event", "job_id", "actor", "site", "ip",
                    "doc_hash", "printer", "reason", "details"]
            name = "advprint-audit-%s.csv"
        else:
            cols = ["id", "created_at", "kind", "title", "printer", "copies",
                    "status", "priority", "attempts", "source", "site",
                    "origin_ip", "pages", "duplex", "paper_size", "tray",
                    "profile", "reason", "duration_ms", "error", "content_hash"]
            name = "advprint-history-%s.csv"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore",
                           lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
        data = buf.getvalue().encode("utf-8-sig")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         'attachment; filename="%s"'
                         % (name % datetime.now().strftime("%Y%m%d-%H%M%S")))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _do_post_impl(self):
        u = urlparse(self.path)
        route = u.path.rstrip("/")
        q = parse_qs(u.query)
        ctype = (self.headers.get("Content-Type") or "").lower()
        raw_pdf = None
        # v2.9.1 (audit M1 fix): refuse LARGE unauthenticated bodies before
        # reading them (401, nothing swallowed). Query token counts - the
        # phone /send portal rides its QR link's ?token=.
        # v3.3.2 BUG 2: native IPP routes are EXEMPT - Windows speaks IPP
        # without any token (like a physical network printer) and its
        # Print-Job bodies are routinely > 1 MB; the old gate answered 401
        # BEFORE reading a byte, the still-transmitting client got a
        # mid-body connection abort (BrokenPipe on our side, "couldn't
        # connect" on Windows) and every real print died. IPP keeps its
        # own guards: ipp_printer_enabled() + the browser-Origin refusal +
        # the MAX_PDF body cap + per-request audit with the source IP.
        if route.startswith("/ipp/print") or route in ("/ipp", "/ipp/"):
            pass
        elif self._preauth_gate(q):
            return self._send(401, {
                "ok": False,
                "error": "invalid or missing token - "
                         "the request body was not read"})

        # POST /peer-connect - v2.8.1 one-click invite accept. Runs on
        # the RECEIVING PC's hub and must work WITHOUT that hub's token
        # (the inviting hub cannot know it) - so it is handled BEFORE the
        # generic body/auth parsing, with its own loopback + CSRF guards
        # (see connect_page_html's security model comment). The body is
        # a plain urlencoded form POST from the confirmation page.
        if route == "/peer-connect":
            return self._peer_connect()
        # POST /ipp/print - v2.9.0 NETWORK PRINTER (IPP everywhere).
        # Handled BEFORE body/auth parsing: the body is binary IPP,
        # not JSON. IPP is its own protocol (like a physical network
        # printer - no token), guarded by ipp_printer + size limits +
        # audit; see the v2.9.0 NETWORK PRINTER MODE comment block.
        # v3.0.9 PER-PRINTER QUEUES: /ipp/print/<printer> routes the
        # job to exactly that local printer (raw name, URL-encoded or
        # slug - see _ipp_queue_match).
        # v3.3.2 BUG 3: an UNKNOWN queue no longer hard-404s the whole
        # add-printer flow. Windows validates the queue during "add" with
        # Get-Printer-Attributes/Validate-Job - a JSON 404 there answered
        # "Windows couldn't connect to the printer" for every slightly
        # mistyped or not-yet-known queue name. The slug is carried into
        # ipp_handle now: Get-Printer-Attributes / Validate-Job answer as
        # the generic queue with the client URI echoed and the requested
        # name as printer-name (the add SUCCEEDS), Print-Job falls back to
        # the hub's default destination with an audit note, and the GET
        # landing page keeps its HTML answer. Known queues behave exactly
        # as before (routed to that one printer).
        ipp_q_printer = ""
        ipp_q_unknown = ""
        if route.startswith("/ipp/print/"):
            ipp_q_printer = _ipp_queue_match_cached(
                urllib.parse.unquote(route[len("/ipp/print/"):]))
            if not ipp_q_printer:
                ipp_q_unknown = urllib.parse.unquote(
                    route[len("/ipp/print/"):])[:80]
                db_audit("ipp.queue.reject", ip=self._client_ip(),
                         site="lan",
                         details="unknown per-printer IPP queue %r "
                                 "(answered as generic queue)"
                                 % route[:120])
            route = "/ipp/print"
        if route in ("/ipp/print", "/ipp", "/ipp/"):
            if not ipp_printer_enabled():
                return self._send(404, {"ok": False,
                                        "error": "IPP printer is off"})
            # v2.9.1 (audit H6 fix): native IPP clients (Windows "add a
            # printer by URL", phones, CUPS) NEVER send a browser Origin
            # header - only a web page's fetch() does. A web page has no
            # business speaking raw IPP to the hub, so any request with a
            # browser http(s)/null Origin is refused BEFORE the body is
            # even read. This closes the "unauthenticated IPP + CORS *"
            # combination where any website could drive the printer.
            ipp_origin = (self.headers.get("Origin") or "").strip()
            if ipp_origin and ipp_origin.lower() != "null" \
                    and not _extension_origin(ipp_origin):
                return self._send(403, {
                    "ok": False,
                    "error": "IPP is for native print clients - web pages"
                             " must use /print with the hub token"})
            try:
                data = read_raw_body(self)
            except ValueError as e:
                # chunked decode errors / oversized bodies - a clean
                # HTTP 400 instead of a traceback in the thread
                return self._send(400, {"ok": False,
                                        "error": "bad IPP request: %s" % e})
            if len(data) > MAX_PDF:
                return self._send(413, {"ok": False,
                                        "error": "IPP request too large"})
            resp = ipp_handle(data, self._client_ip(), printer=ipp_q_printer,
                              unknown_queue=ipp_q_unknown)
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", IPP_MIME)
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            try:
                self.wfile.write(resp)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        try:
            if route in ("/print", "/send") and (
                    "application/pdf" in ctype or
                    "application/octet-stream" in ctype):
                # RAW BINARY upload - zero base64 cost.
                # application/pdf        -> PDF bytes (default)
                # application/octet-stream + ?kind=raw or ?lang=escpos|zpl
                #                        -> RAW printer bytes (ESC/POS / ZPL)
                # POST the bytes directly; parameters ride the query string:
                # /print?title=...&printer=...&copies=2&token=...
                # v2.8: /send accepts the same bodies (send portal upload)
                body = {}
                raw_pdf = read_raw_body(self)
            elif route in ("/print", "/send") and \
                    "multipart/form-data" in ctype:
                # multipart upload (Laravel Http::attach, curl -F, forms,
                # the v2.8 /send portal page): file field 'pdf'/'file' =
                # PDF bytes, text fields = params
                raw_pdf, body = parse_multipart(
                    read_raw_body(self), self.headers.get("Content-Type"))
            else:
                body = read_json_body(self, required=(route == "/print"))
        except (ValueError, json.JSONDecodeError) as e:
            return self._send(400, {"ok": False, "error": "bad request body: %s" % e})

        err = self._origin_error()
        if err:
            return self._send(err[0], {"ok": False, "error": err[1]})
        # v2.9.0 PHONE AUTH FIX: the /send portal is a plain BROWSER page
        # (phones scanning the QR code). In token_header_only mode the
        # old code accepted the token ONLY from the X-AdvPrint-Token
        # header on POST - which no phone browser can send - so every
        # phone got "invalid or missing token" (the reported "Auth
        # fail") right after picking a PDF, while PCs (extension, which
        # sends the header) kept working. /send is exactly like the GET
        # pages: the token rides the same shared QR link, so allow the
        # query/body token here too. The token is still REQUIRED and
        # still compared with hmac.compare_digest - only the transport
        # is relaxed, and ONLY for this one endpoint.
        err = self._auth_error((q.get("token") or [""])[0], body,
                               allow_query=(route == "/send"))
        if err:
            if route == "/send":
                # phone-friendly message instead of the long CLI hint
                return self._send(err[0], {
                    "ok": False, "error":
                    "Auth failed - the link you scanned carries an old or"
                    " wrong token. Open the hub dashboard, press 'QR code'"
                    " and scan the fresh one." if err[0] == 401 else err[1]})
            return self._send(err[0], {"ok": False, "error": err[1]})
        ip = self._client_ip()
        site = self._request_site()

        # POST /jobs/{id}/reprint
        if route.startswith("/jobs/") and route.endswith("/reprint"):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            code, payload = reprint_job_core(j, body, ip, site)
            return self._send(code, payload)

        # POST /jobs/bulk-reprint - v2.7.0: reprint MANY stored jobs in
        # one call. Either {"ids":[12,13,...]} (History tab "Reprint
        # selected") or {"scope":"not_printed"} (every failed/dead/
        # canceled job - "Reprint all non-printed"). Optional reason /
        # watermark / watermark_text / printer ride along, exactly like
        # the single-job reprint. Per-job failures never abort the batch.
        if route == "/jobs/bulk-reprint":
            ids = body.get("ids") or []
            scope = str(body.get("scope") or "").strip().lower()
            pairs = []                       # (requested_id, job_row|None)
            if scope == "not_printed":
                try:
                    lim = max(1, min(1000, int(body.get("limit") or 500)))
                except (TypeError, ValueError):
                    lim = 500
                pairs = [(j["id"], j)
                         for j in db_list_not_printed(limit=lim)]
            elif isinstance(ids, list) and ids:
                seen = set()
                pick = []
                for x in ids:
                    try:
                        i = int(x)
                    except (TypeError, ValueError):
                        continue
                    if i > 0 and i not in seen:
                        seen.add(i)
                        pick.append(i)
                # v2.7.0: unknown ids stay in the list (as None rows) so
                # the caller sees them as skipped, not silently dropped
                pairs = [(i, db_get(i)) for i in pick]
            else:
                return self._send(400, {
                    "ok": False,
                    "error": "give \"ids\":[...] or \"scope\":\"not_printed\""})
            results, okn, skip = [], 0, 0
            for req_id, j in pairs:
                if j is None:
                    skip += 1
                    results.append({"id": req_id, "ok": False,
                                    "job_id": None,
                                    "error": "job not found"})
                    continue
                code, payload = reprint_job_core(j, body, ip, site)
                if code == 200:
                    okn += 1
                else:
                    skip += 1
                results.append({"id": j["id"], "ok": code == 200,
                                "job_id": payload.get("job_id"),
                                "error": payload.get("error")})
            db_audit("reprint.bulk", actor="api", site=site, ip=ip,
                     details="bulk reprint: %d queued, %d skipped "
                             "(scope=%s ids=%s)"
                             % (okn, skip, scope or "ids",
                                (",".join(str(i) for i in ids))[:80]))
            log("[REPRINT] bulk: %d queued, %d skipped" % (okn, skip))
            return self._send(200, {"ok": True, "queued": okn,
                                    "skipped": skip, "results": results})

        # POST /history/clear - v2.7.0: wipe the FINISHED job history
        # (printed / failed / dead / canceled / forwarded / saved).
        # Waiting jobs (queued / printing / held / scheduled) are never
        # touched - clearing the history cannot cancel a real print job.
        if route == "/history/clear":
            n = db_clear_history()
            db_audit("history.cleared", actor="api", site=site, ip=ip,
                     details="history cleared: %d finished job(s) removed"
                             % n)
            log("[HISTORY] cleared - %d finished job(s) removed" % n)
            return self._send(200, {"ok": True, "deleted": n,
                                    "message": "%d finished job(s) removed "
                                               "from the history" % n})

        # POST /send - v2.8: print WITHOUT the extension. The send portal
        # page (/send) and any LAN device (phone, tablet, another PC,
        # curl -F) upload a PDF here; it is printed on this PC's printers
        # exactly like a hub job. Same token auth as every other route.
        if route == "/send":
            fname = str(body.get("filename") or "send")
            if raw_pdf is None:
                if "multipart/form-data" in ctype:
                    raw_pdf, pbody = parse_multipart(
                        read_raw_body(self),
                        self.headers.get("Content-Type"))
                    fname = str(pbody.get("filename") or fname)
                    body.update(pbody)
                elif body.get("pdf_base64"):
                    # JSON mode, same as /print: {"pdf_base64": "..."}
                    import base64 as _b64
                    try:
                        raw_pdf = _b64.b64decode(
                            str(body.get("pdf_base64")), validate=False)
                    except Exception:
                        raw_pdf = None
                    fname = str(body.get("title") or "send")
                else:
                    return self._send(400, {"ok": False, "error":
                        "send a PDF: multipart -F file=@report.pdf, an "
                        "application/pdf body, or JSON pdf_base64"})
            if not raw_pdf or not raw_pdf.startswith(b"%PDF"):
                return self._send(400, {"ok": False, "error":
                    "only PDF files can be printed here"})
            if len(raw_pdf) > MAX_PDF:
                return self._send(413, {"ok": False, "error":
                    "PDF too large - the limit is %d MB"
                    % (MAX_PDF // (1024 * 1024))})
            title = str(body.get("title") or fname) or "send"
            if title.lower().endswith(".pdf"):
                title = title[:-4]
            job, dup = enqueue_print("a4", ("Send: " + title)[:90], raw_pdf,
                                     source="send", dedupe=False,
                                     origin_ip=ip)
            db_audit("print", job_id=job, site=site, ip=ip,
                     printer=dest_display(),
                     details="send portal upload (%d KB)"
                             % (len(raw_pdf) // 1024))
            log("[SEND] '%s' uploaded (%d KB) -> job #%d%s"
                % (fname, len(raw_pdf) // 1024, job,
                   " (already in the queue)" if dup else ""))
            return self._send(200, {"ok": True, "job_id": job})

        # POST /restart - v2.8: relaunch the hub as a NEW process and exit
        # this one (same as the tray menu Restart). The new process waits
        # for this one to release the port (ADVPRINT_RESTART=1).
        # POST /tool - v3.2.0 THE ONE UI: the desktop tool's WHOLE menu
        # (tool.py [1]..[14]) exposed over HTTP so the console Tools panel
        # replaces the command-line tool completely. Loopback + token only
        # (a LAN PC gets the CENTER view where these buttons are hidden).
        if route == "/tool":
            if not self._is_loopback():
                return self._send(403, {"ok": False, "error":
                    "the 14 tools run on the hub PC itself (loopback only)"})
            action = str(body.get("action") or "").strip()
            db_audit("tool." + (action or "?"), actor="console", site=site,
                     ip=ip, details="tool action from the ONE UI")
            res = {"ok": True, "message": "", "result": None}

            def _safe(fn, fallback):
                try:
                    return fn()
                except Exception as e:                    # noqa: BLE001
                    return fallback + (": %s" % e)

            if action == "start":
                res["message"] = ("the hub is already running - you are "
                                  "using it right now (tool [1] done)")
            elif action == "stop":
                # same clean exit the tray menu uses (os._exit after the
                # answer is flushed; the OS releases the port)
                log("[TOOL] stop requested from the ONE UI console")
                db_audit("hub.stop", actor="console", site=site, ip=ip,
                         details="tool [2] stop from the ONE UI")
                threading.Timer(0.8, os._exit, args=(0,)).start()
                res["message"] = "stopping the hub now - start it again with tool [1]"
            elif action == "status":
                res["result"] = {
                    "version": VERSION,
                    "service": _safe(service_state, {}),
                    "autostart": bool(_safe(autostart_enabled, False)),
                    "firewall": bool(_safe(firewall_rule_ok, False)),
                    "data_dir": CFG["data_dir"],
                    "config_file": config_path(),
                    "queue": _safe(lambda: {
                        "pending": db_count_pending(),
                        "held": db_count_held(),
                        "paused": not RESUME_EVENT.is_set(),
                    }, {}),
                }
            elif action == "testprint":
                data, _ = thermal_pdf_bytes(
                    "#big AdvPrint Pro - A4 TEST\n\nIf this page came out "
                    "of your printer,\nthe hub is working perfectly."
                    "\n\nTime: %s\n" % datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"),
                    "testprint", paper="a4")
                job, _dup = enqueue_print("a4", "test-a4", data,
                                          dedupe=False,
                                          origin_ip=self._client_ip(),
                                          site=self._request_site())
                res["message"] = "test page queued (job #%s)" % job["id"]
                res["result"] = {"job_id": job["id"]}
            elif action in ("service-install", "service-remove"):
                # UAC prompt on Windows; PowerShell decides the outcome.
                threading.Thread(
                    target=_safe,
                    args=(lambda: cmd_service(
                        "install" if action == "service-install"
                        else "remove"), ""),
                    daemon=True).start()
                res["message"] = (
                    "Windows service %s requested - approve the UAC prompt "
                    "(takes a few seconds)" % ("install" if
                    action == "service-install" else "removal"))
            elif action == "autorun-toggle":
                state = autostart_set(not bool(_safe(autostart_enabled,
                                                     False)))
                res["enabled"] = bool(state)
                res["message"] = "start at logon: %s" % ("ON" if state
                                                         else "OFF")
            elif action == "check-update":
                import urllib.request as _ur
                try:
                    req = _ur.Request(
                        "https://api.github.com/repos/bitdreamit/"
                        "AdvPrint-Pro/releases/latest",
                        headers={"User-Agent": "AdvPrintPro/%s" % VERSION})
                    with _ur.urlopen(req, timeout=6) as r:
                        rel = json.loads(r.read().decode("utf-8", "replace"))
                    tag = str(rel.get("tag_name") or "")
                    latest = tag.lstrip("vV")
                    res["result"] = {
                        "current": VERSION, "latest_tag": tag or "(unknown)",
                        "up_to_date": (not latest) or latest <= VERSION,
                        "url": rel.get("html_url") or
                        "https://github.com/bitdreamit/AdvPrint-Pro/releases",
                    }
                except Exception as e:                    # noqa: BLE001
                    res["result"] = {"current": VERSION,
                                     "latest_tag": "(unreachable)",
                                     "up_to_date": True,
                                     "note": "offline - %s" % e}
            elif action == "recent-jobs":
                db_init()
                res["result"] = {"jobs": [
                    {k: r[k] for k in ("id", "created_at", "status",
                                       "printer", "title")}
                    for r in db_list(15)]}
            elif action == "uninstall":
                _safe(lambda: autostart_set(False), "")
                svc = _safe(service_state, {}) or {}
                if svc.get("installed"):
                    threading.Thread(
                        target=_safe, args=(lambda: cmd_service("remove"),
                                            ""), daemon=True).start()
                res["message"] = (
                    "autostart removed%s - program files stay: uninstall "
                    "via Windows Settings > Apps > AdvPrint Pro; print "
                    "history is kept in %s"
                    % (" + service removal requested" if svc.get("installed")
                       else "", CFG["data_dir"]))
            elif action == "livetest":
                db_init()
                init_config()
                res["result"] = run_livetest(do_print=False)
            elif action == "open-dashboard":
                url = "http://127.0.0.1:%d/ui" % CFG["port"]
                threading.Thread(target=_safe,
                                 args=(lambda: webbrowser.open(url), ""),
                                 daemon=True).start()
                res["message"] = "opening %s in the default browser" % url
            elif action == "diagnose":
                dbg = _safe(build_debug_report, {"problems": []}) or {}
                res["result"] = {
                    "service": _safe(service_state, {}),
                    "autostart": bool(_safe(autostart_enabled, False)),
                    "firewall": bool(_safe(firewall_rule_ok, False)),
                    "problems": (dbg.get("problems") or [])[:12],
                }
            elif action == "policy-install":
                # v3.2.1 ONE UI Extension tab: multi-browser CRX forcelist
                # writer - reuses the existing ext_policy_* helpers.
                # body: {browser?: chrome|edge|brave|vivaldi|chromium|opera,
                #        hive?: HKCU|HKLM}   (default: every browser, HKCU)
                frag_map = {n: f for f, n in EXT_POLICY_BROWSERS}
                bkey = str(body.get("browser") or "").lower()
                hive = str(body.get("hive") or "HKCU").upper()
                if hive not in ("HKCU", "HKLM"):
                    hive = "HKCU"
                if not IS_WIN:
                    res = {"ok": False, "message": ext_policy_status()
                           .get("note", "policy-install writes Windows "
                           "registry keys; see docs/BUILD-FROM-SOURCE.md "
                           "for the Linux JSON policy"),
                           "error": "not Windows - " + ext_policy_status()
                           .get("note", "registry policy is Windows-only")}
                else:
                    pairs = ([(frag_map[bkey], bkey)] if bkey in frag_map
                             else list(EXT_POLICY_BROWSERS))
                    if bkey and bkey not in frag_map:
                        res = {"ok": False, "message":
                               "unknown browser '%s' (use chrome, edge, "
                               "brave, vivaldi, chromium)" % bkey,
                               "error": "unknown browser '%s'" % bkey}
                    else:
                        data = ext_forcelist_value()
                        ext_id = (crx_package() or {}).get("ext_id",
                                                           EXT_CRX_ID)
                        report, wrote = {}, 0
                        for frag, name in pairs:
                            key = ("%s\\SOFTWARE\\Policies\\%s\\"
                                   "ExtensionInstallForcelist" % (hive, frag))
                            vals = _ext_reg_query_values(key)
                            target = None
                            for vname, vdata in vals.items():
                                if vdata.startswith(ext_id + ";"):
                                    target = vname
                                    break
                            if target is None:
                                target = str(len(vals) + 1)
                            ok = _ext_reg_add(key, target, data)
                            if ok:
                                _ext_reg_add("HKCU\\Software\\AdvPrintPro",
                                             "ExtPolicy." + frag, target)
                                wrote += 1
                            report[name] = ("written (%s entry %s)" %
                                            (hive, target) if ok else
                                            "%s write failed (reg.exe AND "
                                            "PowerShell blocked - %s)"
                                            % (hive,
                                               "HKLM needs an admin console"
                                               if hive == "HKLM" else
                                               "AV/app-control may block "
                                               "policy writes"))
                        res = {"ok": wrote > 0, "browsers": report,
                               "wrote": wrote, "value": data,
                               "message": ("%s policy written for %d "
                                           "browser(s) - restart the "
                                           "browser once, then "
                                           "chrome://policy shows it"
                                           % (hive, wrote))}
                        if wrote == 0:
                            # v3.2.5 BUG FIX 5: the console api() helper
                            # used to show a blind "HTTP 200" here - now
                            # the real reason travels in error + message.
                            res["error"] = ("no policy entry written "
                                            "(%s) - see the report and "
                                            "the docs 'Force-install "
                                            "policy' section" % hive)
            elif action == "fw-allow":
                threading.Thread(target=_safe, args=(firewall_allow, ""),
                                 daemon=True).start()
                res["message"] = ("firewall rule requested - approve the "
                                  "UAC prompt (TCP %d + %d)"
                                  % (CFG["port"], CFG["raw_printer_port"]))
            elif action == "restart":
                db_audit("hub.restart", actor="console", site=site, ip=ip,
                         details="tool [14] restart from the ONE UI")
                log("[RESTART] tool [14] restart requested from the console")
                threading.Timer(0.7, _restart_and_exit).start()
                res["message"] = ("restarting - the hub is back in a few "
                                  "seconds")
            else:
                return self._send(400, {"ok": False, "error":
                    "unknown tool action '%s' (use start/stop/status/"
                    "testprint/service-install/service-remove/autorun-"
                    "toggle/check-update/recent-jobs/uninstall/livetest/"
                    "open-dashboard/diagnose/fw-allow/restart)" % action})
            return self._send(200, res)

        if route == "/restart":
            db_audit("hub.restart", actor="api", site=site, ip=ip,
                     details="restart requested (dashboard/API)")
            log("[RESTART] restart requested via HTTP - relaunching")
            threading.Timer(0.7, _restart_and_exit).start()
            return self._send(200, {"ok": True, "message":
                "Restarting - the hub is back in a few seconds"})

        # POST /dropzone/open - v2.8: open the DropZone folder in
        # Explorer (loopback only - a remote PC cannot pop windows here)
        if route == "/dropzone/open":
            if not self._is_loopback():
                return self._send(403, {"ok": False, "error":
                    "loopback only - open the folder on the hub PC"})
            d = drop_dir()
            try:
                os.makedirs(os.path.join(d, "done"), exist_ok=True)
            except OSError:
                pass
            try:
                if IS_WIN:
                    os.startfile(d)                       # noqa: S606
                elif IS_MAC:
                    subprocess.Popen(["open", d])
                else:
                    subprocess.Popen(["xdg-open", d])
            except Exception as e:
                return self._send(500, {"ok": False, "error":
                    "cannot open the folder: %s" % e})
            return self._send(200, {"ok": True, "dir": d})

        # POST /jobs/{id}/retry - failed/dead/held jobs, optionally on
        # ANOTHER printer (dead-letter recovery)
        if route.startswith("/jobs/") and route.endswith("/retry"):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            if not j:
                return self._send(404, {"ok": False, "error": "job not found"})
            if j["status"] not in ("failed", "dead", "canceled", "held",
                                   "scheduled"):
                return self._send(409, {"ok": False,
                                        "error": "job %s cannot be retried"
                                                 % j["status"]})
            if not (j.get("file_path") and os.path.exists(j["file_path"])):
                return self._send(410, {"ok": False,
                                        "error": "original file no longer stored"})
            new_printer = str(body.get("printer") or "").strip()
            db_update(j["id"], status="queued", error=None,
                      attempts=0, next_attempt_at=None, held_reason=None,
                      printer=new_printer or j.get("printer") or "")
            db_audit("print.requeued", job_id=j["id"], printer=new_printer,
                     reason=str(body.get("reason") or "")[:200] or None,
                     ip=ip, site=site,
                     details="manual retry%s"
                             % (" on printer '%s'" % new_printer
                                if new_printer else ""))
            log("[RETRY] job #%d requeued by request%s"
                % (j["id"], " on printer '%s'" % new_printer
                   if new_printer else ""))
            return self._send(200, {"ok": True, "job_id": j["id"],
                                    "printer": new_printer or j.get("printer")})

        # POST /jobs/release_all - v2.5: force EVERY held job out right now
        # (dashboard "Release ALL held jobs" button).
        if route == "/jobs/release_all":
            held = db_list(limit=200, status="held")
            n = 0
            for j in held:
                if j.get("file_path") and os.path.exists(j["file_path"]):
                    db_update(j["id"], status="printing", error=None,
                              held_reason=None, next_attempt_at=None,
                              attempts=0)
                    db_audit("job.print_now", job_id=j["id"],
                             printer=j.get("printer"), ip=ip, site=site,
                             details="release_all (was %s)" % j["status"])
                    threading.Thread(
                        target=_print_now,
                        args=(j["id"], j["file_path"], j.get("kind") or "a4",
                              j.get("printer") or "", j.get("copies") or 1),
                        daemon=True,
                        name="advprint-now-%d" % j["id"]).start()
                    n += 1
            return self._send(200, {"ok": True, "released": n})

        # POST /jobs/{id}/print-now - v2.2.1: force THIS job out of the
        # queue RIGHT NOW, bypassing the global pause and the printer-status
        # hold. Works on queued/held/scheduled/failed/dead/saved jobs - the
        # one-click remedy when "nothing prints". ("/release" is a v2.5
        # alias used by the extension and tests.)
        if route.startswith("/jobs/") and route.endswith(("/print-now",
                                                          "/release")):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            if not j:
                return self._send(404, {"ok": False, "error": "job not found"})
            if j["status"] in ("printing", "forwarded"):
                return self._send(409, {"ok": False,
                                        "error": "job is already %s"
                                                 % j["status"]})
            if j["status"] == "canceled":
                return self._send(409, {"ok": False,
                                        "error": "job was canceled - use"
                                                 " /retry instead"})
            if not (j.get("file_path") and os.path.exists(j["file_path"])):
                return self._send(410, {"ok": False,
                                        "error": "original file no longer"
                                                 " stored"})
            db_update(j["id"], status="printing", error=None,
                      held_reason=None, next_attempt_at=None, attempts=0)
            db_audit("job.print_now", job_id=j["id"],
                     printer=j.get("printer"), ip=ip, site=site,
                     details="forced print (was %s)" % j["status"])
            log("[NOW] job #%d forced to print (was %s)"
                % (j["id"], j["status"]))
            threading.Thread(
                target=_print_now,
                args=(j["id"], j["file_path"], j.get("kind") or "a4",
                      j.get("printer") or "", j.get("copies") or 1),
                daemon=True, name="advprint-now-%d" % j["id"]).start()
            return self._send(200, {"ok": True, "job_id": j["id"],
                                    "status": "printing",
                                    "message": "printing now (bypasses"
                                               " pause and hold)"})

        # POST /jobs/{id}/priority {"priority": 1..9}
        if route.startswith("/jobs/") and route.endswith("/priority"):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            if not j:
                return self._send(404, {"ok": False, "error": "job not found"})
            try:
                pr = max(1, min(9, int(body.get("priority"))))
            except (TypeError, ValueError):
                return self._send(400, {"ok": False,
                                        "error": "priority must be 1-9"})
            db_update(j["id"], priority=pr)
            return self._send(200, {"ok": True, "job_id": j["id"],
                                    "priority": pr})

        # POST /jobs/{id}/cancel  (queued -> canceled; printing -> killed)
        if route.startswith("/jobs/") and route.endswith("/cancel"):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            if not j:
                return self._send(404, {"ok": False, "error": "job not found"})
            if j["status"] in ("printed", "failed", "canceled", "saved",
                               "dead", "forwarded"):
                return self._send(409, {"ok": False,
                                        "error": "job already finished (%s)" % j["status"]})
            db_update(j["id"], status="canceled", error="canceled by user",
                      held_reason=None)
            db_audit("job.canceled", job_id=j["id"], ip=ip, site=site,
                     printer=j.get("printer"))
            killed = cancel_current_print()
            if killed == j["id"]:
                log("[CANCELED] job #%d killed while printing" % j["id"])
            return self._send(200, {"ok": True, "canceled": j["id"],
                                    "was_printing": killed == j["id"]})

        # POST /queue/pause | /queue/resume | /queue/clear
        if route in ("/queue/pause", "/queue/resume", "/queue/clear"):
            if route == "/queue/pause":
                RESUME_EVENT.clear()
                db_audit("queue.paused", ip=ip, site=site)
                log("[QUEUE] paused by request")
            elif route == "/queue/resume":
                RESUME_EVENT.set()
                db_audit("queue.resumed", ip=ip, site=site)
                log("[QUEUE] resumed by request")
            else:
                # v3.2.6 BUG FIX 1 - "clear but not clean": the old code
                # only flipped queued jobs to canceled and IGNORED the
                # {finished:true} body the console sent - rows stayed in
                # both views forever. NOW:
                #   {finished:true} -> remove every FINISHED record
                #                     (same as POST /history/clear)
                #   plain           -> cancel every live job AND remove
                #                     all terminal rows (queue is EMPTY
                #                     afterwards - really clean)
                if isinstance(body, dict) and body.get("finished"):
                    n = db_clear_history()
                    db_audit("history.cleared", ip=ip, site=site,
                             details="queue/clear finished:true - %d "
                                     "finished job(s) removed" % n)
                    log("[QUEUE] clear finished - %d row(s) removed" % n)
                    return self._send(200, {
                        "ok": True, "deleted": n,
                        "message": "%d finished job(s) removed" % n})
                canceled, removed = db_clear_queue()
                db_audit("queue.cleared", ip=ip, site=site,
                         details="%d job(s) canceled, %d row(s) removed"
                                 % (canceled, removed))
                log("[QUEUE] cleared - %d canceled, %d row(s) removed"
                    % (canceled, removed))
                return self._send(200, {
                    "ok": True, "canceled": canceled, "removed": removed,
                    "message": "%d job(s) canceled, %d record(s) removed "
                               "- the queue is clean" % (canceled, removed)})
            # v2.6.3: pause/resume must show in /health instantly (the
            # snapshot refreshes every 3 s in the background - rebuild it
            # now so the popup/dashboard never reads a stale pause flag).
            try:
                build_health_snapshot()
            except Exception:
                pass
            return self._send(200, {"ok": True,
                                    "paused": not RESUME_EVENT.is_set()})

        # POST /autostart  {"enabled": true|false}
        if route == "/autostart":
            enable = body.get("enabled")
            if enable is None:
                enable = (q.get("enabled") or [""])[0].lower() in ("1", "true", "on", "yes")
            state = autostart_set(bool(enable))
            # v3.2.5 BUG FIX 6: rebuild the health snapshot NOW so the
            # next console poll reads the NEW state - the old code left
            # the stale snapshot up for up to 3 s and the UI switch
            # flipped itself back on (tray said OFF, UI said ON).
            try:
                build_health_snapshot()
            except Exception:
                pass
            return self._send(200, {"ok": True, "enabled": state,
                                    "path": autostart_path()})

        # POST /token/rotate - generate a fresh random token (v2.0)
        if route == "/token/rotate":
            newtok = secrets.token_urlsafe(24)
            CFG["token"] = newtok
            disk = {k: CFG[k] for k in CONFIG_KEYS}
            write_config_file(disk)
            db_audit("token.rotated", ip=ip, site=site,
                     details="token changed via API")
            log("[TOKEN] rotated via API - new token saved to config.json")
            # v2.6.3: token state must show in /health instantly
            try:
                build_health_snapshot()
            except Exception:
                pass
            return self._send(200, {"ok": True, "token": newtok,
                                    "hint": "save this token now - enter it"
                                            " in the extension Options page"})

        # POST /livetest - v2.6: full A-to-Z self-test over HTTP (used by
        # the dashboard "Full self-test" button, the extension Debug tab
        # and the desktop tool). Read-only mechanics: nothing is printed,
        # nothing deleted.
        if route == "/livetest":
            return self._send(200, run_livetest(do_print=False))

        # POST /printers/set-default - v3.2.5 BUG FIX 1: ACTUALLY set the
        # OS default printer. body: {"printer": "<name>"} (default_printer
        # also accepted - the ONE UI uses printer). The old "Set Default"
        # button only saved CFG["printer"], so Windows kept its own default
        # and the auto-manage feature flipped it back. This endpoint calls
        # os_set_default_printer (Windows: LegacyDefaultPrinterMode=1 +
        # WScript.Network.SetDefaultPrinter, verified by reading back;
        # Unix: lpoptions -d), keeps the hub destination key in sync and
        # returns the VERIFIED new default. 200 even on failure (ok:false
        # + error) so the console toast can show the real reason.
        if route == "/printers/set-default":
            nm = str((body or {}).get("printer")
                     or (body or {}).get("default_printer") or "").strip()
            if not nm:
                return self._send(400, {"ok": False,
                    "error": "send {\"printer\": \"<printer name>\"}"})
            ok, got, detail = os_set_default_printer(nm)
            db_audit("printers.set_default", ip=ip, site=site,
                     details="%s -> %s (%s)" % (nm, got,
                                                "verified" if ok else "failed"))
            if ok:
                try:
                    CFG["printer"] = got
                    disk = {k: CFG[k] for k in CONFIG_KEYS}
                    write_config_file(disk)
                except Exception as e:
                    log("[SETDEF] config sync skipped: %s" % e)
                _DP_CACHE["t"] = 0.0        # next read re-scans the OS
                try:
                    build_health_snapshot()
                except Exception:
                    pass
                return self._send(200, {"ok": True, "default": got,
                                        "printer": nm, "detail": detail})
            return self._send(200, {"ok": False, "default": got,
                                    "printer": nm, "error": detail})

        # POST /config - update v2.0 settings at runtime (persists)
        if route == "/config":
            changed = []
            # v2.9.1 (audit M6 fix): ATOMIC config apply. The old loop did
            # CFG[key] = val per key and returned 400 mid-loop on a failing
            # key - keys 1..N-1 stayed in memory while disk kept the old
            # values (memory/disk drift until restart). Everything is now
            # validated into `updates` FIRST and applied in one shot.
            updates = {}
            for key, val in (body or {}).items():
                if key == "default_printer":
                    # v3.2.0: the ONE UI (and the old console) say
                    # default_printer - the config key is "printer"
                    key = "printer"
                if key == "token":
                    return self._send(400, {
                        "ok": False,
                        "error": "use POST /token/rotate to change the token"})
                if key not in CONFIG_TYPES:
                    return self._send(400, {
                        "ok": False, "error": "unknown config key '%s'" % key})
                # v2.9: friendly validation for the destination keys
                if key == "dest_mode" and str(val) not in (
                        "", "default", "selected", "ip"):
                    return self._send(400, {
                        "ok": False,
                        "error": "dest_mode must be '', 'default',"
                                 " 'selected' or 'ip'"})
                if key == "ip_printer_proto" and str(val) not in (
                        "raw", "ipp"):
                    return self._send(400, {
                        "ok": False,
                        "error": "ip_printer_proto must be 'raw' or 'ipp'"})
                # v3.3.2 SHARE SEND MODE - the switch cannot go ON without
                # a paired LAN PC (the v3.3.1 bug: a transient JS variable
                # made the check, so a reload wiped the state and the
                # switch said "connect the LAN PC first" even for a
                # connected PC). The check reads the PERSISTED pairing.
                if key == "share_send" and val and not _lan_pc_peer():
                    return self._send(400, {
                        "ok": False,
                        "error": "Connect the LAN PC first - enter its hub"
                                 " URL + token and press Connect (Share Send"
                                 " Mode sends every job to that PC)"})
                if key == "share_send" and val is False:
                    pass  # OFF is always allowed
                if key == "allowed_ips":
                    # v3.2.3 ALLOWED IPS - clean the list. "*" wins, and an
                    # EMPTY list means all-LAN again (never lock the owner
                    # out of their own hub from a typo). Entries are short
                    # strings (IP / CIDR / wildcard).
                    cleaned = []
                    for x in (val if isinstance(val, list) else []):
                        s = str(x).strip()[:64]
                        if s and s not in cleaned:
                            cleaned.append(s)
                    if not cleaned or "*" in cleaned:
                        cleaned = ["*"]
                    val = cleaned
                if key == "thermal_text_engine" and str(val) not in (
                        "", "auto", "builtin", "browser"):
                    return self._send(400, {
                        "ok": False,
                        "error": "thermal_text_engine must be '', 'auto',"
                                 " 'builtin' or 'browser'"})
                if key == "escpos_codepage":
                    import re as _re
                    if not _re.match(r"^[a-z0-9_\-]{1,24}$",
                                     str(val).lower()):
                        return self._send(400, {
                            "ok": False,
                            "error": "escpos_codepage looks wrong"
                                     " (examples: cp437, cp850, cp866)"})
                    val = str(val).lower()
                want = CONFIG_TYPES[key]
                try:
                    if want is bool:
                        val = bool(val)
                    elif want is int:
                        val = max(0, int(val))
                    elif want is list:
                        if not isinstance(val, list):
                            raise ValueError("must be a list")
                        if key == "peer_hubs":
                            # v2.9.1 (audit M6 fix): peer_hubs entries are
                            # DICTS ({url, token, name}) - the old
                            # [str(x) for x in val] turned real peer dicts
                            # into useless "{'url': ...}" repr strings and
                            # silently corrupted the peer list. Dicts pass
                            # through with basic shape validation.
                            cleaned = []
                            for x in val:
                                if isinstance(x, dict):
                                    e = {"url": str(x.get("url") or ""),
                                         "token": str(x.get("token") or ""),
                                         "name": str(x.get("name") or "")[:60]}
                                    # v3.3.2: keep the lan-pc display label
                                    if x.get("label"):
                                        e["label"] = str(x["label"])[:60]
                                    cleaned.append(e)
                                elif isinstance(x, str):
                                    cleaned.append({"url": x, "token": "",
                                                    "name": ""})
                                else:
                                    raise ValueError(
                                        "peer_hubs entries must be objects")
                            # v3.3.3 DUPLICATE-PEER FIX: never store two
                            # entries for the same hub URL
                            val = _dedupe_peer_hubs(cleaned)
                        elif key == "rules_mirror":
                            # v3.2.0 ONE UI: central rule manager entries
                            # are DICTS - a generic [str(x)] would corrupt
                            # them into repr strings. Clean with defaults.
                            cleaned = []
                            for x in val:
                                if isinstance(x, dict):
                                    cleaned.append({
                                        "id": x.get("id"),
                                        "name": str(x.get("name") or "")[:80],
                                        "pattern": str(x.get("pattern") or "*")[:300],
                                        "match": "content" if x.get("match") == "content" else "url",
                                        "kind": str(x.get("kind") or "")[:12],
                                        "printer": str(x.get("printer") or "")[:120],
                                        "action": str(x.get("action") or "auto")[:12],
                                        "copies": max(1, min(99, int(x.get("copies") or 1))),
                                        "paper": str(x.get("paper") or "")[:24],
                                        "on": bool(x.get("on", True)),
                                        "runs": max(0, int(x.get("runs") or 0)),
                                        # v3.2.1 rev-4 rule editor fields
                                        "auto": bool(x.get("auto", True)),
                                        "sched": str(x.get("sched") or "")[:40],
                                        "priority": max(1, min(99, int(x.get("priority") or 1))),
                                        "content": str(x.get("content") or "")[:200],
                                        "color": str(x.get("color") or "")[:12],
                                        "duplex": str(x.get("duplex") or "")[:16],
                                    })
                                else:
                                    raise ValueError(
                                        "rules_mirror entries must be objects")
                            val = cleaned
                        else:
                            val = [str(x) for x in val]
                    elif want is dict:
                        if not isinstance(val, dict):
                            raise ValueError("must be an object")
                        if key == "printer_groups":
                            # v2.9.1 (audit M6 fix): validate members are
                            # string lists, so {"Lab": "printer1"} can no
                            # longer corrupt the group picker
                            for g, members in val.items():
                                if not isinstance(members, list) or \
                                        not all(isinstance(m, str)
                                                for m in members):
                                    raise ValueError(
                                        "printer_groups['%s'] must be a"
                                        " list of printer-name strings" % g)
                        val = dict(val)
                except (TypeError, ValueError) as e:
                    return self._send(400, {"ok": False,
                                            "error": "config '%s': %s" % (key, e)})
                updates[key] = val
            # v3.2.6 NEW FEATURE: "LAN Sharing & Other PCs ipp by default
            # on when lan share on" - switching LAN sharing ON silently
            # enables the IPP printer with it (unless the same request
            # set ipp_printer explicitly, so the extra IPP Enable/Disable
            # toggle can still turn it off on a LAN-on hub).
            ipp_link = False
            if updates.get("share_lan") is True and \
                    "ipp_printer" not in updates and \
                    CFG.get("ipp_printer") is False:
                updates["ipp_printer"] = True
                ipp_link = True
            if updates:
                CFG.update(updates)
                changed = list(updates.keys())
                if "peer_hubs" in updates:
                    _PEER_CACHE["t"] = 0.0   # v3.3.3: probe the new list now
                disk = {k: CFG[k] for k in CONFIG_KEYS}
                write_config_file(disk)
                db_audit("config.changed", ip=ip, site=site,
                         details=", ".join(changed) +
                         (" (ipp auto-enabled with LAN sharing)"
                          if ipp_link else ""))
                log("[CONFIG] updated: %s%s"
                    % (", ".join(changed),
                       " [IPP printer auto-enabled with LAN sharing]"
                       if ipp_link else ""))
                # v2.6.3: config changes must be visible in /health
                # IMMEDIATELY (the snapshot refreshes every 3 s in the
                # background - rebuild it now so no client ever reads a
                # stale setting back).
                try:
                    build_health_snapshot()
                except Exception:
                    pass
            lan_info = None
            if "share_lan" in changed:
                # v2.8.2: LAN sharing applies LIVE - the dedicated LAN
                # listener starts/stops right here, before the response
                # leaves. No hub restart. Loopback is never touched.
                if _env("HOST"):
                    BOUND_LAN = bool(CFG.get("share_lan"))
                    lan_info = {"rebound": False, "lan_error": None,
                                "note": "ADVPRINT_HOST pins the main bind "
                                        "- restart the hub to apply"}
                elif CFG.get("share_lan"):
                    err = lan_listen_start()
                    lan_info = {"rebound": True, "lan_error": err}
                    # v3.2.6: the IPP listeners must follow the fresh
                    # config IMMEDIATELY (the 3 s refresher would catch
                    # up anyway - the user sees it faster this way).
                    try:
                        ipp631_listen_ensure()
                    except Exception:
                        pass
                    try:
                        ipp_mdns_ensure()
                    except Exception:
                        pass
                else:
                    lan_listen_stop()
                    lan_info = {"rebound": True, "lan_error": None}
            resp = {"ok": True, "changed": changed,
                    "config": redacted_config()}
            if lan_info:
                resp["lan"] = lan_info
            return self._send(200, resp)

        # POST /ip-printer/test - v2.9: check the upstream IP printer
        # (the dest_mode "ip" destination). Uses the form values when
        # given, so the user can test BEFORE saving. TCP reachability
        # + latency - the same probe the print worker uses to hold jobs
        # while the IP printer is down.
        if route == "/ip-printer/test":
            try:
                host = str((body or {}).get("host")
                           or CFG.get("ip_printer_host") or "").strip()
                port = int((body or {}).get("port")
                           or CFG.get("ip_printer_port") or 0)
                proto = str((body or {}).get("proto")
                            or CFG.get("ip_printer_proto")
                            or "raw").lower()
                if proto not in ("raw", "ipp"):
                    proto = "raw"
                if port <= 0:
                    port = 631 if proto == "ipp" else 9100
            except (TypeError, ValueError):
                return self._send(400, {"ok": False,
                                        "error": "bad host/port"})
            if not host:
                return self._send(400, {
                    "ok": False,
                    "error": "type the IP printer's IP or hostname first"})
            t0 = time.time()
            pstat = ip_printer_probe((host, port, proto), timeout=4.0)
            ms = int((time.time() - t0) * 1000)
            return self._send(200, {
                "ok": pstat == "ready", "state": pstat, "ms": ms,
                "target": "%s:%d (%s)" % (host, port, proto),
                "error": None if pstat == "ready" else
                         "no answer on TCP %d - check the IP, the port"
                         " and that this PC and the printer are on the"
                         " same network" % port})

        # POST /firewall/allow - v2.8.2 one-click Windows firewall fix.
        # Loopback ONLY: a UAC elevation prompt is a local, physical-
        # user action - never trigger it from a LAN client request.
        if route == "/firewall/allow":
            if self._client_ip() not in ("127.0.0.1", "::1",
                                         "::ffff:127.0.0.1"):
                return self._send(403, {
                    "ok": False,
                    "error": "open the dashboard on THIS PC "
                             "(http://127.0.0.1:%d) to change the "
                             "firewall" % CFG["port"]})
            ok, err = firewall_allow()
            return self._send(200 if ok else 400,
                              {"ok": ok, "error": err,
                               "firewall_ok": firewall_rule_ok()})

        # POST /debug/report - v2.3: the extension (Debug mode ON) and
        # the desktop tool send every error HERE so /debug can show why
        # a job did not print - browser-side problems (JS exceptions,
        # failed fetches, token errors) never reach hub.log otherwise.
        if route in ("/debug/report", "/client/report"):
            b = body or {}
            entry = add_debug_report(
                source=str(b.get("source") or "client"),
                level=str(b.get("level") or "error"),
                message=str(b.get("message") or ""),
                context=b.get("context"),
                job_id=b.get("job_id"), ip=ip, site=site)
            db_audit("debug.report", job_id=entry["job_id"],
                     actor=entry["source"], site=site, ip=ip,
                     details="%s: %s" % (entry["level"],
                                         entry["message"][:150]))
            return self._send(200, {
                "ok": True, "stored": len(_DBG_REPORTS),
                "debug": bool(CFG.get("debug")),
                "hint": "open /debug?token=... (or the extension Debug"
                        " tab) to see hub problems + client reports"})

        # POST /print
        if route == "/print":
            def bget(key, default=None):
                # JSON/multipart body first, query string second (?key=...)
                v = body.get(key)
                if v is None or v == "":
                    v = (q.get(key) or [default])[0]
                return v
            kind = (bget("kind") or "").lower()
            title = str(bget("title") or "document")[:60]
            printer = str(bget("printer") or "")[:120]
            source = str(bget("source") or "api")[:20]
            paper = (bget("paper") or ("thermal" if kind == "thermal" else "a4")).lower()
            landscape = bget("landscape")
            if isinstance(landscape, str):
                landscape = landscape.strip().lower() in ("1", "true", "yes", "on")
            copies = bget("copies") or 1
            try:
                copies = max(1, min(int(copies), 50))
            except (TypeError, ValueError):
                copies = 1
            # ---- v2.0 print options ----
            try:
                priority = max(1, min(9, int(bget("priority") or 5)))
            except (TypeError, ValueError):
                priority = 5
            pages = str(bget("pages") or "")[:60] or None
            duplex = str(bget("duplex") or "")[:20] or None
            paper_size = str(bget("paper_size") or "")[:20] or None
            tray = str(bget("tray") or "")[:40] or None
            # v2.1 print options: n-up, quality, scale, margins, orientation
            per_sheet = bget("per_sheet")
            try:
                per_sheet = max(1, min(16, int(per_sheet))) if per_sheet else 1
            except (TypeError, ValueError):
                per_sheet = 1
            # v2.2 quality accepts BOTH named presets (draft|normal|high)
            # AND a DPI number ("600", "600dpi") - stored exactly as given
            quality = str(bget("quality") or "")[:16].strip().lower() or None
            dpi = bget("dpi")
            try:
                dpi = int(dpi) if dpi else None
            except (TypeError, ValueError):
                dpi = None
            if quality and not dpi:
                mdpi = re.match(r"^(\d{2,4})\s*dpi$", quality)
                if mdpi:
                    dpi = int(mdpi.group(1))
                    quality = "dpi:%d" % dpi
                elif re.match(r"^\d{2,4}$", quality):
                    dpi = int(quality)
                    quality = "dpi:%d" % dpi
            if dpi:
                dpi = max(72, min(2400, dpi))
                quality = "dpi:%d" % dpi
            if quality in ("best", "fine"):
                quality = "high"
            scale_pct = bget("scale_pct") or bget("scale") or None
            margin_mm = bget("margin_mm") or bget("margins") or None
            orientation = str(bget("orientation") or "").lower()
            landscape = orientation in ("landscape", "land", "horizontal")
            reason = str(bget("reason") or "")[:200] or None
            profile_name = str(bget("profile") or "")[:60] or None
            lang = (bget("lang") or "").lower()
            # dedupe override (?dedupe=false / {"dedupe": false})
            dedupe_req = bget("dedupe")
            if dedupe_req is None:
                dedupe_req = True
            elif isinstance(dedupe_req, str):
                dedupe_req = dedupe_req.strip().lower() not in (
                    "0", "false", "off", "no")
            else:
                dedupe_req = bool(dedupe_req)
            # run_at: ISO datetime OR relative "+5m" / "+2h" / "+30s"
            run_at = None
            raw_run_at = str(bget("run_at") or "").strip()
            if raw_run_at:
                m = re.match(r"^\+(\d+)\s*([smhd])$", raw_run_at.lower())
                if m:
                    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
                    run_at = (datetime.now() +
                              timedelta(seconds=int(m.group(1)) * mult)) \
                        .isoformat(timespec="seconds")
                else:
                    try:
                        run_at = datetime.fromisoformat(
                            raw_run_at.replace("Z", "")).isoformat(timespec="seconds")
                    except ValueError:
                        return self._send(400, {
                            "ok": False,
                            "error": "run_at must be ISO datetime or"
                                     " +N(s|m|h|d)"})
            # print profile (v2.0): named defaults, request values win
            if profile_name:
                prof = (CFG.get("profiles") or {}).get(profile_name)
                if not isinstance(prof, dict):
                    return self._send(400, {"ok": False,
                                            "error": "unknown profile '%s'"
                                                     % profile_name})
                if not printer:
                    printer = str(prof.get("printer") or "")
                paper_size = paper_size or prof.get("paper_size") or prof.get("paper")
                tray = tray or prof.get("tray")
                duplex = duplex or prof.get("duplex")
                pages = pages or prof.get("pages")
                if "copies" in prof and copies == 1:
                    try:
                        copies = max(1, min(int(prof["copies"]), 50))
                    except (TypeError, ValueError):
                        pass
            # Queue Mode: body/query "queue": false -> print immediately,
            # bypassing the FIFO (pause has no effect on direct jobs).
            # v2.3: friendlier alias mode=instant|direct|now (and
            # mode=queue); a given "queue" value always wins.
            mode_req = str(bget("mode") or "").strip().lower()
            if not mode_req and bget("instant"):
                mode_req = "instant"     # v2.5: {"instant": true} alias
                queue_mode = False
            queue_mode = bget("queue")
            if queue_mode is None:
                if mode_req in ("instant", "direct", "now"):
                    queue_mode = False
                elif mode_req in ("queue", "queued", "fifo"):
                    queue_mode = True
            if queue_mode is None:
                queue_mode = True
            elif isinstance(queue_mode, str):
                queue_mode = queue_mode.strip().lower() not in (
                    "0", "false", "off", "no")
            else:
                queue_mode = bool(queue_mode)
            # destination: "printer" (default) | "file" (save as PDF, no paper)
            # printer value "__file__" is the extension's alias for destination file
            destination = (bget("destination") or
                           ("file" if printer == "__file__" else "printer")).lower()
            if destination not in ("printer", "file"):
                destination = "printer"
            if destination == "file":
                printer = ""
            data = None
            wm_flag = bget("watermark")
            if wm_flag is None:
                wm_flag = False
            elif isinstance(wm_flag, str):
                wm_flag = wm_flag.strip().lower() in ("1", "true", "yes", "on")
            wm_text = str(bget("watermark_text") or "REPRINT")[:24]

            if raw_pdf is not None:
                if (q.get("kind") or [""])[0].lower() == "raw" or lang in (
                        "escpos", "zpl"):
                    data = raw_pdf
                    kind = "raw"
                elif len(raw_pdf) > MAX_PDF:
                    return self._send(400, {"ok": False,
                                            "error": "PDF larger than %d MB" % (MAX_PDF // (1024 * 1024))})
                elif not raw_pdf[:5].startswith(b"%PDF"):
                    return self._send(400, {"ok": False,
                                            "error": "raw body is not a PDF (must start with %PDF-)"
                                                     " - add ?kind=raw for ESC/POS/ZPL bytes"})
                else:
                    data = raw_pdf
                    kind = kind or "a4"
            elif body.get("raw_base64") or (lang in ("escpos", "zpl") and
                                            body.get("text") is not None):
                try:
                    data, lang = raw_payload_bytes(body)
                except ValueError as e:
                    return self._send(400, {"ok": False, "error": str(e)})
                kind = "raw"
            elif body.get("pdf_base64"):
                try:
                    data = base64.b64decode(body["pdf_base64"], validate=False)
                except Exception as e:
                    return self._send(400, {"ok": False,
                                            "error": "bad pdf_base64: %s" % e})
                if not data[:5].startswith(b"%PDF"):
                    return self._send(400, {"ok": False,
                                            "error": "pdf_base64 is not a PDF"})
                kind = kind or "a4"
            elif body.get("pdf_url"):
                try:
                    data = download_pdf(body["pdf_url"])
                except Exception as e:
                    return self._send(400, {"ok": False,
                                            "error": "pdf_url failed: %s" % e})
                kind = kind or "a4"
            elif body.get("image_base64"):
                try:
                    img = base64.b64decode(body["image_base64"], validate=False)
                    if img[:3] == b"\xff\xd8\xff":
                        data, _ = image_pdf_bytes(img, title,
                                                  paper="thermal" if paper == "thermal" else "a4",
                                                  landscape=landscape)
                    else:
                        return self._send(400, {
                            "ok": False,
                            "error": "image_base64 must be a JPEG (image/jpeg);"
                                     " PNG is not supported - re-encode as JPEG"})
                except ValueError as e:
                    return self._send(400, {"ok": False, "error": str(e)})
                kind = "image-thermal" if paper == "thermal" else "image"
            elif body.get("html") is not None:
                try:
                    data, _ = html_to_pdf_bytes(
                        inject_page_css(body["html"], margin_mm=margin_mm,
                                        scale_pct=scale_pct,
                                        landscape=landscape),
                        is_url=False, title=title)
                except Exception as e:
                    return self._send(500, {"ok": False,
                                            "error": "html render failed: %s" % e})
                kind = "page"
            elif body.get("page_url"):
                try:
                    # v2.9.1 (audit H4 fix): page_url now runs the SAME
                    # SSRF guard as pdf_url. The old code passed the URL
                    # straight to headless Chrome, so "page_url":
                    # "file:///C:/..." (or any internal http URL) made
                    # the hub render local/internal content and send it
                    # back as a PDF to whoever asked.
                    pdf_url_guard(str(body["page_url"]))
                    data, _ = html_to_pdf_bytes(
                        body["page_url"], is_url=True, title=title)
                    # CSS injection applies to html payloads, not live URLs
                    if margin_mm or scale_pct or landscape:
                        log("[PRINT] note: margin/scale/orientation are not"
                            " applied to page_url jobs (server-rendered"
                            " page) - send 'html' instead")
                except ValueError as e:
                    # v2.9.1 (audit H4 fix): guard rejections are the
                    # caller's fault - a readable 400, not a server 500
                    return self._send(400, {"ok": False,
                                            "error": "page_url blocked: %s" % e})
                except Exception as e:
                    return self._send(500, {"ok": False,
                                            "error": "page render failed: %s" % e})
                kind = "page"
            elif body.get("text") is not None:
                txt = str(body["text"])
                engine = str(CFG.get("thermal_text_engine") or "auto").lower()
                want_browser = (
                    engine == "browser"
                    or (engine == "auto" and text_needs_browser(txt)))
                if want_browser and find_browser():
                    # v2.1: Bangla/Unicode text is shaped by Chrome with
                    # system fonts (Nirmala UI / Noto Sans Bengali) so
                    # receipts print correctly instead of '????'
                    receipt_html = (
                        "<html><head><meta charset='utf-8'>"
                        "<style>@page{size:80mm auto;margin:2mm}"
                        "pre{font:8pt/1.35 'Nirmala UI','Noto Sans Bengali',"
                        "'Vrinda',monospace;white-space:pre-wrap;}"
                        "</style></head><body><pre>%s</pre></body></html>"
                        % html.escape(txt))
                    data, _ = html_to_pdf_bytes(receipt_html, is_url=False,
                                                title=title)
                    kind = "thermal"
                    log("[PRINT] Bangla/Unicode text rendered via browser"
                        " engine (thermal roll)")
                else:
                    if want_browser:
                        log("[PRINT] browser not found - builtin thermal"
                            " renderer used; non-Latin text may show as '?'")
                    data, _ = thermal_pdf_bytes(
                        txt, title,
                        paper="thermal" if paper == "thermal" else "a4",
                        margin_mm=margin_mm, scale_pct=scale_pct,
                        landscape=landscape)
                    kind = "thermal" if paper == "thermal" else "a4"
            else:
                return self._send(400, {"ok": False,
                                        "error": "provide pdf_base64, pdf_url,"
                                                 " image_base64, html, page_url,"
                                                 " text, raw_base64 or"
                                                 " text+lang=escpos|zpl"})

            if kind not in ("a4", "thermal", "image", "image-thermal", "page",
                            "raw"):
                kind = "a4"

            content_hash = hashlib.sha256(data).hexdigest()

            # optional REPRINT/draft watermark on the PDF itself
            if wm_flag and kind not in ("raw",):
                data = pdf_watermark(data, wm_text)

            db_audit("print.submitted", job_id=None, actor=source, site=site,
                     ip=ip, doc_hash=content_hash, printer=printer or None,
                     reason=reason)

            if destination == "file":
                if kind == "raw":
                    return self._send(400, {"ok": False,
                                            "error": "raw print cannot use"
                                                     " destination file"})
                job, fpath = save_file_job(kind, title, data, source, ip)
                return self._send(200, {
                    "ok": True, "job_id": job, "kind": kind,
                    "destination": "file", "status": "saved",
                    "file": fpath, "url_path": "/jobs/%d/file" % job,
                    "message": "saved as PDF file - no paper used",
                })

            job, dup = enqueue_print(
                kind, title, data, printer, copies, source, ip,
                queue_mode=queue_mode, priority=priority, run_at=run_at,
                site=site, dedupe=dedupe_req, content_hash=content_hash,
                reason=reason, profile=profile_name, pages=pages,
                duplex=duplex, paper_size=paper_size, tray=tray,
                per_sheet=per_sheet, quality=quality,
                **({"watermarked": 1} if (wm_flag and kind != "raw") else {}))
            # v2.3: read the REAL status back - the instant-print auto-queue
            # fallback may have left the job queued instead of printing
            # v2.9.1: the worker is INSTANT now (wake event instead of the
            # 0.35 s poll), so an auto-queued job can already be HELD
            # (printer offline) by the time this response is built -
            # "held with a hold reason" counts as auto-queued too.
            real_row = db_get(job) or {}
            real_status = real_row.get("status")
            auto_queued = (not queue_mode and not run_at and dup is None and
                           (real_status == "queued" or
                            (real_status == "held"
                             and real_row.get("held_reason"))))
            resp = {
                "ok": True, "job_id": job, "kind": kind, "copies": copies,
                "destination": "printer",
                "queue_mode": "on" if queue_mode else "off",
                "instant": (not queue_mode),
                "auto_queued": auto_queued,
                "duplicate": dup is not None,
                "priority": priority,
                # v2.2.1: truthful initial status so clients (extension
                # history) stop recording everything as "queued"
                # v2.3: instant + no active printer -> the job was
                # auto-queued, so the answer says queued, not printing
                "status": ("scheduled" if run_at else real_status or
                           ("queued" if queue_mode else "printing")),
                "message": ("queued to printer" if queue_mode else
                            "printer not active - job auto-queued (prints"
                            " when it is ready)" if auto_queued else
                            "printing immediately (queue mode off)"),
            }
            if dup is not None:
                resp["message"] = ("duplicate blocked - identical job #%d"
                                   " already accepted recently" % dup)
                resp["status"] = (db_get(job) or {}).get("status") \
                    or "queued"
            if run_at:
                resp["scheduled_for"] = run_at
                resp["status"] = "scheduled"
            if lang:
                resp["lang"] = lang
            return self._send(200, resp)

        # POST /peer/pair - v3.3.2 SHARE SEND MODE pairing. The
        # Connections panel's "Another PC (LAN PC)" card sends the OTHER
        # PC's hub URL + token; this validates (probe /health with the
        # token, LAN sharing must be ON there), stores it as the
        # "lan-pc" peer_hubs entry in config.json (survives reloads -
        # the v3.3.1 report "reload wipes the token") and answers the
        # full card status. Never navigates the browser anywhere.
        if route == "/peer/pair":
            return _peer_pair(self, body, ip)

        # POST /peer/unpair - v3.3.2: the card's "Clear" button. Forgets
        # the lan-pc pairing and turns Share Send Mode OFF.
        if route == "/peer/unpair":
            return _peer_unpair(self, ip)

        # POST /peer/test-page - v3.3.2: print a test page on the PAIRED
        # LAN PC's named printer (server-side relay, no browser CORS).
        if route == "/peer/test-page":
            return _peer_test_page(self, body, ip)

        # POST /queue/shift - v2.1: move queued/held/failed jobs to ANOTHER
        # PC's hub over the LAN ("individual shift" via ids, "full shift"
        # via scope=all). Queue on/off stays /queue/pause + /queue/resume.
        if route == "/queue/shift":
            # v3.3.3: accept `peer` as an alias for `target` - the console's
            # Shift buttons sent {peer: url} while this endpoint read only
            # `target`, so the URL was silently ignored (the endpoint then
            # guessed the first live peer).
            target = str(body.get("target") or body.get("peer")
                         or "").strip().rstrip("/")
            ids = [int(x) for x in (body.get("ids") or [])
                   if str(x).isdigit()]
            scope = str(body.get("scope") or
                        ("job" if ids else "all")).lower()
            peer_tok = str(body.get("target_token") or "")
            if not target:
                live = [p for p in probe_peers() if p.get("alive")]
                if not live:
                    return self._send(400, {"ok": False, "error":
                        "no target given and no live peer_hubs configured"
                        " (add peers in config.json first)"})
                target = live[0]["url"]
            if not peer_tok:
                for p in CFG.get("peer_hubs") or []:
                    if _peer_url_norm(p.get("url")) == \
                            _peer_url_norm(target):
                        peer_tok = p.get("token") or ""
                        break
            picked = [j for j in db_list(500)
                      if j.get("status") in ("pending", "queued", "held",
                                             "failed", "dead", "retrying")]
            if scope == "job":
                picked = [j for j in picked if j["id"] in ids]
            shifted, errors = [], []
            for j in picked:
                try:
                    fpath = j.get("file_path")
                    if not (fpath and os.path.exists(fpath)):
                        raise RuntimeError("original file missing on this PC")
                    with open(fpath, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    payload = {"pdf_base64": b64,
                               "title": j.get("title") or "shifted job",
                               "printer": j.get("printer") or "",
                               "copies": j.get("copies") or 1,
                               "pages": j.get("pages"),
                               "duplex": j.get("duplex"),
                               "paper_size": j.get("paper_size"),
                               "tray": j.get("tray"),
                               "per_sheet": j.get("per_sheet"),
                               "quality": j.get("quality"),
                               "source": "shift"}
                    payload = {k: v for k, v in payload.items()
                               if v not in (None, "")}
                    req = urllib.request.Request(
                        target + "/print",
                        data=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json",
                                 "X-AdvPrint-Token": peer_tok,
                                 "User-Agent": "AdvPrintPro/%s" % VERSION})
                    with urllib.request.urlopen(req, timeout=25) as r:
                        pr = json.loads(r.read().decode("utf-8", "replace"))
                    if not pr.get("ok"):
                        raise RuntimeError(str(pr.get("error"))[:120])
                    db_update(j["id"], status="forwarded", peer=target,
                              held_reason=None)
                    db_audit("job.forwarded", job_id=j["id"],
                             actor="queue.shift", ip=ip,
                             details="shifted to %s (remote job %s)"
                                     % (target, pr.get("job_id")))
                    log("[SHIFT] job #%d -> %s (remote job %s)"
                        % (j["id"], target, pr.get("job_id")))
                    shifted.append(j["id"])
                except Exception as e:
                    errors.append({"id": j["id"], "error": str(e)[:120]})
            return self._send(200, {
                "ok": True, "target": target, "scope": scope,
                "shifted": shifted, "shifted_count": len(shifted),
                "errors": errors,
                "message": "%d job(s) shifted to %s" % (len(shifted), target)})

        if route == "/extension/policy/install":
            db_audit("extension.policy_install", actor="dashboard",
                     ip=self._client_ip())
            return self._send(200, ext_policy_install())

        if route == "/extension/policy/remove":
            db_audit("extension.policy_remove", actor="dashboard",
                     ip=self._client_ip())
            return self._send(200, ext_policy_remove())

        return self._send(404, {"ok": False, "error": "unknown endpoint"})

# ------------------------------------------------------------
# v2.0 helper views: redacted config, peers, diagnostics, dashboard
# ------------------------------------------------------------
REDACT_KEYS = ("token",)

def redacted_config():
    c = {k: CFG[k] for k in CONFIG_KEYS}
    for k in REDACT_KEYS:
        if k in c:
            c[k] = mask_token(c[k])
    peers = []
    for p in (CFG.get("peer_hubs") or []):
        q = dict(p)
        if q.get("token"):
            q["token"] = mask_token(q["token"])
        peers.append(q)
    c["peer_hubs"] = peers
    c["config_file"] = config_path()
    c["hint"] = ("POST the same keys to /config to change them;"
                 " use POST /token/rotate for the token")
    return c

_PEER_CACHE = {"t": 0.0, "v": []}

def _peer_url_norm(url):
    """v3.3.3: the dedupe key for peer_hubs entries - scheme://host:port
    with a lowercased host and no trailing slash/path. http://IP:9235,
    http://ip:9235/ and HTTP://IP:9235/ipp are the SAME peer."""
    u = str(url or "").strip().rstrip("/")
    if not u:
        return ""
    m = re.match(r"^(https?)://([^/?]+)", u, re.I)
    if not m:
        return u.lower()
    return "%s://%s" % (m.group(1).lower(), m.group(2).lower())

def _dedupe_peer_hubs(peers):
    """v3.3.3 DUPLICATE-PEER FIX: collapse peer_hubs entries that point
    at the SAME hub URL. The user-visible bug: the Connections peers
    table showed http://192.168.1.101:9235 TWICE (one row from the LAN
    PC card's lan-pc pairing, one from an older invite / config.json
    entry) and the duplicate probed with a stale token. When the group
    contains the lan-pc entry, THAT entry wins - its name is
    load-bearing (_lan_pc_peer() reads it, and a lost pairing makes the
    Share Send switch pop "Connect the LAN PC first" again); otherwise
    the first occurrence wins. A dropped entry's name survives as the
    kept entry's label when the kept one has none."""
    out, by_key = [], {}
    for p in peers or []:
        if not isinstance(p, dict):
            continue
        key = _peer_url_norm(p.get("url"))
        if not key:
            continue
        if key in by_key:
            prev_i = by_key[key]
            prev = out[prev_i]
            # a lan-pc entry always displaces a non-lan-pc one for the
            # same hub (migration: v3.3.2 could store the invite entry
            # first, lan-pc second)
            prev_is_lan = str(prev.get("name") or "") == LAN_PC_PEER_NAME
            p_is_lan = str(p.get("name") or "") == LAN_PC_PEER_NAME
            if p_is_lan and not prev_is_lan:
                out[prev_i] = p
                prev = p
            # the dropped entry's display name survives as the kept
            # entry's LABEL - never overwrite the kept entry's `name`
            # (lan-pc MUST stay lan-pc, or _lan_pc_peer() finds nothing
            # and Share Send Mode pops "Connect the LAN PC first" again)
            if prev is not None and not (prev.get("label") or ""):
                cand = str(p.get("label") or "")
                if not cand and str(p.get("name") or "") not in \
                        ("", LAN_PC_PEER_NAME):
                    cand = str(p["name"])[:60]
                if cand:
                    prev["label"] = cand
            continue
        by_key[key] = len(out)
        out.append(p)
    return out

def probe_peers(timeout=3):
    """Health-probe every configured peer hub; dead ones are reported
    (and later skipped by the forwarding logic). Cached 15 s.
    v3.3.3: entries are deduped by normalized URL first (the user
    report "same PC listed twice, both OFFLINE"), each entry now ALSO
    carries `up` (the console's peers table read p.up while the old
    code sent only `alive`, so every row rendered OFFLINE and the
    Shift-queue button stayed disabled forever) and the entry's
    name/label so the table can show WHICH PC the row is."""
    peers = _dedupe_peer_hubs(CFG.get("peer_hubs") or [])
    if not peers:
        return []
    if time.time() - _PEER_CACHE["t"] < 15 and _PEER_CACHE["v"]:
        return _PEER_CACHE["v"]
    out = []
    for peer in peers:
        url = (peer.get("url") or "").rstrip("/")
        entry = {"url": url, "up": False, "alive": False, "version": None,
                 "latency_ms": None,
                 "name": str(peer.get("name") or "")[:60],
                 "label": str(peer.get("label") or "")[:60]}
        if url:
            t0 = time.time()
            try:
                req = urllib.request.Request(
                    url + "/health",
                    headers={"X-AdvPrint-Token": peer.get("token") or "",
                             "User-Agent": "AdvPrintPro/%s" % VERSION})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
                entry["alive"] = entry["up"] = True
                entry["version"] = data.get("version")
                entry["latency_ms"] = int((time.time() - t0) * 1000)
            except Exception as e:
                entry["error"] = str(e)[:100]
        out.append(entry)
    _PEER_CACHE["t"] = time.time()
    _PEER_CACHE["v"] = out
    return out

# ------------------------------------------------------------
# v3.3.2 SHARE SEND MODE - the LAN PC pairing behind the Connections
# panel's "Another PC (LAN PC)" card. The card stores the OTHER PC's
# hub URL + token as a peer_hubs entry with name "lan-pc" (persisted
# in config.json, so a page reload / hub restart keeps the pairing -
# the lost-v3.3.1 report "reload wipes the token and shows offline").
# share_send=True forwards EVERY new job to that PC; the peer's own
# share_lan/ipp_printer states are probed live for the status line.
# ------------------------------------------------------------

LAN_PC_PEER_NAME = "lan-pc"


def _lan_pc_peer():
    """The peer_hubs entry the LAN PC card pairs with (name 'lan-pc'),
    or None. Invite-added peers (other PCs connecting TO us) carry their
    own names and are never touched by the card."""
    for p in (CFG.get("peer_hubs") or []):
        if str(p.get("name") or "") == LAN_PC_PEER_NAME:
            return p
    return None


def _peer_probe_detail(peer, timeout=4, with_printers=True):
    """Probe ONE peer hub: /health (version, host, share_lan,
    ipp_printer, default_printer) plus /printers (the remote device
    cards in the Printers panel). Never raises - a dead peer returns
    alive=False with a short error string."""
    url = (peer.get("url") or "").strip().rstrip("/")
    out = {"url": url, "label": peer.get("label") or "", "alive": False,
           "version": None, "peer_host": None, "share_lan": None,
           "ipp_printer": None, "default_printer": None,
           "printers": [], "error": ""}
    if not url:
        out["error"] = "no hub URL saved"
        return out
    tok = peer.get("token") or ""
    hdr = {"X-AdvPrint-Token": tok, "X-PrintHub-Token": tok,
           "User-Agent": "AdvPrintPro/%s" % VERSION}
    t0 = time.time()
    try:
        req = urllib.request.Request(url + "/health", headers=hdr)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            h = json.loads(r.read().decode("utf-8", "replace"))
        out["alive"] = True
        out["version"] = str(h.get("version") or "?")
        out["peer_host"] = str(h.get("host") or h.get("hostname") or "")
        out["share_lan"] = bool(h.get("share_lan"))
        out["ipp_printer"] = bool(h.get("ipp_printer", True))
        out["default_printer"] = h.get("default_printer") or None
        out["latency_ms"] = int((time.time() - t0) * 1000)
        if with_printers:
            try:
                req2 = urllib.request.Request(url + "/printers",
                                              headers=hdr)
                with urllib.request.urlopen(req2, timeout=timeout) as r2:
                    pl = json.loads(r2.read().decode("utf-8", "replace"))
                host_part = url.split("://", 1)[-1]
                for p in (pl.get("printers") or [])[:12]:
                    nm = str(p.get("name") or "").strip()
                    if not nm:
                        continue
                    out["printers"].append({
                        "name": nm,
                        "status": str(p.get("status") or "unknown"),
                        "is_default": bool(p.get("is_default")),
                        "ipp": "ipp://%s/ipp/print/%s" % (
                            host_part, quote(_ipp_queue_slug(nm), safe="")),
                    })
            except Exception:
                pass  # printer list is best-effort
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


_LANPC_PROBE_CACHE = {"t": 0.0, "v": None}
_LANPC_PROBE_TTL = 8.0          # console polls every 3 s - do not hammer
                                # the other PC; Connect/unpair force fresh


def _lan_peer_status(fresh=False):
    """Everything the Connections LAN PC card renders in one call:
    configured pairing (url + label, never the token) + live probe +
    the current share_send switch state. Probes are cached 8 s."""
    peer = _lan_pc_peer()
    st = {"ok": True, "configured": bool(peer), "share_send":
          bool(CFG.get("share_send")),
          "version": VERSION}
    if peer:
        st["url"] = peer.get("url") or ""
        st["label"] = peer.get("label") or ""
        st["token_set"] = bool(peer.get("token"))
        now = time.time()
        if (not fresh and _LANPC_PROBE_CACHE["v"] is not None and
                now - _LANPC_PROBE_CACHE["t"] < _LANPC_PROBE_TTL):
            st["peer"] = _LANPC_PROBE_CACHE["v"]
        else:
            st["peer"] = _peer_probe_detail(peer)
            _LANPC_PROBE_CACHE["t"] = now
            _LANPC_PROBE_CACHE["v"] = st["peer"]
    else:
        st["url"] = ""
        st["label"] = ""
        st["token_set"] = False
        st["peer"] = None
    return st


def _peer_pair(self, body, ip):
    """POST /peer/pair {url, token, name?}: validate + probe + persist
    the OTHER PC's hub as the lan-pc peer_hubs entry."""
    url = str(body.get("url") or "").strip()
    token = str(body.get("token") or "").strip()
    label = str(body.get("name") or "").strip()[:60]
    if url and not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    if not url or not token:
        return self._send(400, {
            "ok": False,
            "error": "both the LAN PC hub URL and its token are needed"
                     " - the token is on the OTHER PC's console"
                     " (Self PC card)"})
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower().rstrip(".")
        if not host:
            raise ValueError("no host")
        url = "%s://%s" % (u.scheme, u.netloc)
    except ValueError:
        return self._send(400, {"ok": False,
                                "error": "that URL could not be parsed"})
    # v3.3.2 BUG 4 (the "redirect own ip" report): the card must never
    # pair with THIS PC. A loopback URL or one of this hub's own
    # addresses + own port is refused with a clear message.
    own = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    try:
        own.add(str(lan_ip() or "").lower())
    except Exception:
        pass
    try:
        own.add(socket.gethostname().lower())
    except Exception:
        pass
    try:
        for _o in list_lan_ips():
            own.add(str(_o).lower())
    except Exception:
        pass
    try:
        for _o in list_lan_ips6():
            own.add(str(_o).strip("[]").lower())
    except Exception:
        pass
    if host in own and \
            (u.port or int(CFG.get("port", 9235))) == \
            int(CFG.get("port", 9235)):
        db_audit("peer.pair.denied", ip=ip,
                 details="self-pair blocked: %s" % url[:100])
        return self._send(400, {
            "ok": False,
            "error": "that is THIS PC's own hub - enter the OTHER PC's"
                     " ip:port (its hub URL is on ITS console, e.g."
                     " http://192.168.1.101:9235)"})
    probe = _peer_probe_detail({"url": url, "token": token},
                               with_printers=False)
    if not probe["alive"]:
        return self._send(400, {
            "ok": False,
            "error": "the other PC's hub did not answer (%s) - check the"
                     " URL, that AdvPrint Pro runs THERE, and the"
                     " Windows firewall rule on THAT PC"
                     % (probe["error"] or "no response")})
    if not probe["share_lan"]:
        return self._send(400, {
            "ok": False,
            "error": "the other PC answered but its LAN sharing is OFF"
                     " - enable it there first (LAN card > Enable),"
                     " then connect again"})
    # v3.3.3 DUPLICATE-PEER FIX: drop EVERY entry that already points at
    # this URL (any name) before inserting the fresh lan-pc pairing. The
    # old code only removed entries NAMED "lan-pc", so an entry for the
    # same hub saved earlier by an invite link (name = the PC's host
    # name) survived -> the peers table listed the SAME PC twice (the
    # user report: "http://192.168.1.101:9235 ... OFFLINE" x2).
    keep_label = ""
    for p in (CFG.get("peer_hubs") or []):
        if _peer_url_norm(p.get("url")) == _peer_url_norm(url) and \
                not label and p.get("label"):
            keep_label = str(p["label"])[:60]
            break
    peers = [p for p in (CFG.get("peer_hubs") or [])
             if str(p.get("name") or "") != LAN_PC_PEER_NAME and
             _peer_url_norm(p.get("url")) != _peer_url_norm(url)]
    peers.insert(0, {"url": url, "token": token, "name": LAN_PC_PEER_NAME,
                     "label": label or keep_label or probe["peer_host"]
                     or "LAN PC"})
    CFG["peer_hubs"] = peers
    try:
        write_config_file({k: CFG[k] for k in CONFIG_KEYS})
    except Exception as e:
        return self._send(500, {"ok": False,
                                "error": "config.json could not be"
                                         " written: %s" % e})
    _PEER_CACHE["t"] = 0.0
    db_audit("peer.paired", actor="dashboard", ip=ip,
             details="LAN PC paired: %s (%s) version=%s"
                     % (url, probe["peer_host"], probe["version"]))
    log("[PEER] LAN PC paired: %s (%s) v%s - Share Send Mode ready"
        % (url, probe["peer_host"], probe["version"]))
    return self._send(200, _lan_peer_status(fresh=True))


def _peer_unpair(self, ip):
    """POST /peer/unpair: forget the paired LAN PC, Share Send OFF."""
    removed = _lan_pc_peer()
    CFG["peer_hubs"] = [p for p in (CFG.get("peer_hubs") or [])
                        if str(p.get("name") or "") != LAN_PC_PEER_NAME]
    CFG["share_send"] = False
    try:
        write_config_file({k: CFG[k] for k in CONFIG_KEYS})
    except Exception as e:
        return self._send(500, {"ok": False,
                                "error": "config.json could not be"
                                         " written: %s" % e})
    _PEER_CACHE["t"] = 0.0
    _LANPC_PROBE_CACHE["v"] = None
    if removed:
        db_audit("peer.unpaired", actor="dashboard", ip=ip,
                 details="LAN PC pairing cleared: %s"
                         % (removed.get("url") or "?"))
        log("[PEER] LAN PC pairing cleared")
    return self._send(200, _lan_peer_status())


def _peer_test_page(self, body, ip):
    """POST /peer/test-page {printer}: generate a test page HERE and
    print it on the PAIRED LAN PC's named printer through the peer's
    own /print. Server-side relay - the console browser never talks to
    the other hub directly (no CORS, no token in the page)."""
    peer = _lan_pc_peer()
    if not peer or not (peer.get("url") and peer.get("token")):
        return self._send(400, {
            "ok": False,
            "error": "Connect the LAN PC first - enter its hub URL +"
                     " token and press Connect"})
    want = str(body.get("printer") or "").strip()[:120]
    try:
        data, _ = thermal_pdf_bytes(
            "#big AdvPrint Pro - LAN PC TEST"
            "\n\nIf this page came out of '%s' on the OTHER PC,"
            "\nShare Send Mode works end to end."
            "\n\nFrom: %s  Time: %s"
            % (want or "default", socket.gethostname(),
               datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "lanpc-test", paper="a4")
    except Exception as e:
        return self._send(500, {"ok": False,
                                "error": "test page could not be"
                                         " generated: %s" % e})
    url = (peer.get("url") or "").rstrip("/")
    payload = json.dumps({
        "pdf_base64": base64.b64encode(data).decode("ascii"),
        "title": "Test Page (from %s)" % socket.gethostname()[:40],
        "printer": want, "source": "remote-test"}).encode()
    try:
        req = urllib.request.Request(
            url + "/print", data=payload, headers={
                "Content-Type": "application/json",
                "X-AdvPrint-Token": peer.get("token") or "",
                "User-Agent": "AdvPrintPro/%s" % VERSION})
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return self._send(502, {"ok": False,
                                "error": "the LAN PC did not accept the"
                                         " job (%s)" % str(e)[:120]})
    if not resp.get("ok"):
        return self._send(502, {"ok": False,
                                "error": str(resp.get("error")
                                             or "job refused")[:160]})
    db_audit("peer.test_page", actor="dashboard", ip=ip, printer=want,
             details="test page printed on LAN PC %s (job %s)"
                     % (url, resp.get("job_id")))
    log("[PEER] test page -> LAN PC %s printer %r (remote job %s)"
        % (url, want, resp.get("job_id")))
    return self._send(200, {"ok": True, "job_id": resp.get("job_id"),
                            "message": "test page queued on the LAN PC"})



def _log_tail(lines=40):
    """Last N hub.log lines with any token REDACTED.
    v2.9.1 (audit M2 fix): the raw log used to be embedded into
    /diagnostics while the docstring claimed "token REDACTED" - old
    installs DO have plain tokens in hub.log (pre-2.9.1 releases printed
    them on first start). Every token=... / token: ... value is masked
    here so diagnostics can be shared safely."""
    path = os.path.join(CFG["data_dir"], "hub.log")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read().splitlines()[-lines:]
    except OSError:
        return []
    out = []
    for line in raw:
        line = re.sub(r"(token=)[A-Za-z0-9_\-]{4,}", r"\1***", line,
                      flags=re.I)
        line = re.sub(r"(\[TOKEN\]\s*token:)\s*\S+", r"\1 ***", line)
        line = re.sub(r"(dashboard\?token=)[^&\s\"']+", r"\1***", line)
        out.append(line)
    return out

def build_diagnostics():
    """Everything a support request needs - with the token REDACTED."""
    st = db_stats() if os.path.isfile(db_path()) else {}
    diag = {
        "ok": True,
        "app": APP_NAME, "version": VERSION, "branding": BRANDING,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "os": "windows" if IS_WIN else ("macos" if IS_MAC else "linux"),
        "data_dir": CFG["data_dir"],
        "config_file": config_path(),
        "uptime_s": int(time.time() - START_TS),
        "listen": "%s:%d" % (CFG["host"], CFG["port"]),
        "token": mask_token(CFG["token"]),
        "token_header_only": bool(CFG.get("token_header_only")),
        "default_token_warning": DEFAULT_TOKEN_WARNING,
        "paused": not RESUME_EVENT.is_set(),
        "db": st,
        "printers": [{"name": n, "status": s} for n, s in
                     printers_status_cached().items()],
        "default_printer": default_printer_cached(),
        "sumatra_found": (find_sumatra() is not None) if IS_WIN else None,
        "browser_found": find_browser() is not None,
        "service": service_state(),
        "autostart": autostart_enabled(),
        "peers": probe_peers(),
        "config": redacted_config(),
        "log_tail": _log_tail(),
    }
    return diag

def _debug_problems():
    """v2.3: the auto-verdict - every 'why is nothing printing' cause the
    hub can see by itself, most severe first. This is what makes /debug
    answer WHEN / WHY / WHERE instead of dumping raw data."""
    probs = []
    db_ok = os.path.isfile(db_path())
    if not (_WORKER_THREAD[0] and _WORKER_THREAD[0].is_alive()):
        probs.append({
            "level": "error", "check": "worker",
            "message": "the print worker thread is NOT running - every job"
                       " stays queued forever while the hub keeps answering"
                       " OK",
            "fix": "restart the hub (tray icon Exit, start again) - the"
                   " v2.2.1 watchdog normally revives it within 30 s"})
    if not RESUME_EVENT.is_set():
        probs.append({
            "level": "warn", "check": "queue",
            "message": "the queue is PAUSED - queued jobs wait and nothing"
                       " prints",
            "fix": "press Resume (popup / dashboard) or POST /queue/resume"})
    if IS_WIN:
        svc = service_state()
        if (svc and svc.get("installed") and not svc.get("running")
                and "pending" in (svc.get("state") or "")):
            probs.append({
                "level": "warn", "check": "Windows service",
                "message": "the OPTIONAL service 'AdvPrint' is stuck in"
                           " '%s' - a stale state left by an older service"
                           " process that was never restarted after an"
                           " upgrade (the hub actually runs from the"
                           " Startup app / tray)" % (svc.get("state") or ""),
                "fix": "services.msc > AdvPrint > Restart (or reboot),"
                       " or run service-remove - keep only ONE of"
                       " service / Startup app active"})
    st = printers_status_cached()
    if not st:
        probs.append({
            "level": "error", "check": "printers",
            "message": "no printer states detected - the OS reports no"
                       " printers to this hub",
            "fix": "check the OS printer list (lpstat -p / Windows"
                   " Settings > Printers) and the CUPS / spooler service"})
    else:
        ready = [n for n, s in st.items() if s == "ready"]
        if not ready:
            probs.append({
                "level": "warn", "check": "printers",
                "message": "no printer reports ready: " +
                           ", ".join("%s=%s" % (n, s)
                                     for n, s in sorted(st.items())),
                "fix": "bring a printer online / clear its error"})
    if IS_WIN and find_sumatra() is None:
        probs.append({
            "level": "error", "check": "sumatra",
            "message": "SumatraPDF not found - on Windows every PDF print"
                       " fails without it",
            "fix": SUMATRA_HINT})
    if find_browser() is None:
        probs.append({
            "level": "warn", "check": "browser",
            "message": "no headless browser found - html / page_url /"
                       " Bangla text renders will fail",
            "fix": "install Chrome / Edge / Chromium, or print PDFs only"})
    jobs = db_list(limit=60) if db_ok else []
    held = [j for j in jobs if j.get("status") == "held"]
    bad = [j for j in jobs if j.get("status") in ("failed", "dead")]
    if held:
        probs.append({
            "level": "warn", "check": "held jobs",
            "message": "%d job(s) HELD - %s" %
                       (len(held), held[0].get("held_reason") or
                        "printer not ready"),
            "fix": "use Print now on the job, or switch off 'Printer"
                   " status hold' in the dashboard"})
    for j in bad[:3]:
        probs.append({
            "level": "error", "check": "job #%s" % j.get("id"),
            "message": "job %s (%s): %s" %
                       (j.get("status"), j.get("title") or "untitled",
                        (j.get("error") or "unknown error")[:200]),
            "fix": "fix the cause, then Retry the job from the history"})
    if DEFAULT_TOKEN_WARNING:
        probs.append({
            "level": "warn", "check": "token",
            "message": "the DEFAULT token is still in use - anyone who"
                       " knows it can print on this PC",
            "fix": "run: %s" % cli_cmd("token-rotate")})
    if not CFG.get("debug"):
        probs.append({
            "level": "info", "check": "debug off",
            "message": "Debug mode is OFF - browser/extension (JS) errors"
                       " are NOT being collected right now",
            "fix": "turn Debug ON (dashboard Debug card, or extension"
                   " Options > Settings > Debug mode) and try again -"
                   " client reports then appear in /debug"})
    if not probs:
        probs.append({
            "level": "info", "check": "all",
            "message": "no hub-side problem found - if printing still"
                       " fails, enable Debug mode and check"
                       " client_reports for the browser-side error",
            "fix": ""})
    return probs

def build_debug_report():
    """v2.3: GET /debug - everything needed to answer 'when / why / where
    is the problem': the hub verdict, queue + worker state, recent jobs,
    and the error reports collected from the browser extension / desktop
    tool. Deliberately fast (no peer network probes)."""
    load_debug_reports()
    db_ok = os.path.isfile(db_path())
    st = db_stats() if db_ok else {}
    cur = None
    if db_ok:
        with _CURRENT_LOCK:
            if _CURRENT["id"]:
                cur = db_get(_CURRENT["id"])
    return {
        "ok": True, "app": APP_NAME, "version": VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "uptime_s": int(time.time() - START_TS),
        "debug": bool(CFG.get("debug")),
        "listen": "%s:%d" % (CFG["host"], CFG["port"]),
        "token": mask_token(CFG["token"]),
        "token_header_only": bool(CFG.get("token_header_only")),
        "worker_alive": bool(_WORKER_THREAD[0]
                             and _WORKER_THREAD[0].is_alive()),
        "paused": not RESUME_EVENT.is_set(),
        "hold_offline": bool(CFG.get("hold_offline", True)),
        "instant_auto_queue": bool(CFG.get("instant_auto_queue", True)),
        "queue": {"paused": not RESUME_EVENT.is_set(),
                  "pending": db_count_pending() if db_ok else 0,
                  "held": db_count_held() if db_ok else 0,
                  "current": cur},
        "printers": [{"name": n, "status": s}
                     for n, s in printers_status_cached().items()],
        "default_printer": default_printer_cached(),
        "sumatra_found": (find_sumatra() is not None) if IS_WIN else None,
        "sumatra_path": (SUMATRA_LAST["found"]
                         or CFG.get("sumatra_path") or ""),
        "sumatra_searched": (list(SUMATRA_LAST["tried"])
                             if (IS_WIN and not SUMATRA_LAST["found"])
                             else []),
        "browser_found": find_browser() is not None,
        "db": st,
        "recent_jobs": [{k: j.get(k) for k in
                         ("id", "created_at", "title", "printer", "status",
                          "error", "held_reason", "kind")}
                        for j in (db_list(limit=15) if db_ok else [])],
        "problems": _debug_problems(),
        "client_reports": list(_DBG_REPORTS[-50:]),
    }

# v3.2.1 THE ONE UI - the approved rev-4 All-in-One console is EMBEDDED
# in the hub file itself (single file, zero external UI dependencies):
# the exact markup/CSS the customer approved (title bar, 9 menus, 218px
# sidebar, 17 tabs, rule editor modal, QR tiles, status bar) with the
# production wiring JS already inside. console_page_bytes() only injects
# the boot JSON (__ADVPRINT_BOOT_JSON__): WHO opened the page (self =
# the hub PC's owner on loopback, center = a LAN PC connected to this
# center PC), the PC name, LAN IP, port and version. Because the UI
# lives INSIDE advprint.py it can never go "missing" the way an
# external console.html could on a partial install.
CONSOLE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AdvPrint Pro — Printing Hub · ALL-IN-ONE Console v3.2.1 — UI Design (IDM Style)</title>
<style>
/* ============================================================
   AdvPrint Pro v3.2.1 — ALL-IN-ONE CONSOLE · FIRST UI DESIGN
   ONE Windows-IDM window manages EVERYTHING:
   dashboard + printers + jobs/history + LAN sharing + DropZone
   + rules + extension switches + debug + audit + logs + settings
   Style: Windows IDM desktop classic (approved design language)
   Real install data: AI-Lab · 10.26.94.206:9235 · token auth ON
   ============================================================ */
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --navy:#1e3a8a; --blue:#1d4ed8; --blue-deep:#1e40af; --blue-soft:#eff6ff;
  --blue-line:#bfdbfe; --line:#e2e8f0; --ink:#0f172a; --ink-2:#475569;
  --muted:#94a3b8; --bg:#f5f8fc; --panel:#ffffff;
  --ok:#16a34a; --ok-bg:#dcfce7; --warn:#d97706; --warn-bg:#fef9c3;
  --err:#dc2626; --err-bg:#fee2e2; --purple:#5b21b6; --purple-bg:#ede9fe;
  --mono:'Cascadia Mono','Consolas','JetBrains Mono',monospace;
}
html,body{height:100%}
body{font-family:'Segoe UI',system-ui,-apple-system,Roboto,'Noto Sans SC',sans-serif;
  background:linear-gradient(160deg,#0b1633 0%,#12275c 45%,#0b1633 100%);
  color:var(--ink);overflow:hidden}
.desktop{height:100vh;padding:16px;display:flex;flex-direction:column}
.window{flex:1;min-height:0;max-width:1400px;width:100%;margin:0 auto;display:flex;
  flex-direction:column;border-radius:10px;overflow:hidden;border:1px solid #16307a;
  box-shadow:0 30px 80px rgba(2,8,35,.65),0 2px 8px rgba(2,8,35,.5);background:var(--bg)}
/* ---------- title bar ---------- */
.titlebar{height:38px;flex:0 0 38px;display:flex;align-items:center;
  background:linear-gradient(135deg,#1e3a8a,#1d4ed8);color:#fff;padding-left:10px;user-select:none}
.titlebar .logo{width:22px;height:22px;border-radius:5px;background:#fff;color:var(--blue);
  display:flex;align-items:center;justify-content:center;font-weight:800;font-size:11px;margin-right:9px;
  box-shadow:inset 0 0 0 1px #ffffff55}
.titlebar .t-main{font-size:12.5px;font-weight:600;letter-spacing:.2px}
.titlebar .t-main small{font-weight:400;opacity:.75;margin-left:8px;font-size:11px}
.titlebar .spacer{flex:1}
.winbtn{width:44px;height:38px;border:none;background:transparent;color:#fff;font-family:inherit;
  font-size:12px;cursor:default;display:flex;align-items:center;justify-content:center}
.winbtn:hover{background:rgba(255,255,255,.18)}
.winbtn.close:hover{background:#dc2626}
/* ---------- menu bar ---------- */
.menubar{height:26px;flex:0 0 26px;display:flex;align-items:center;gap:2px;
  background:linear-gradient(#f8fafc,#eef3fa);border-bottom:1px solid var(--line);padding:0 6px;user-select:none}
.menu-item{font-size:12px;color:var(--ink);padding:3px 9px;border-radius:3px;cursor:default}
.menu-item:hover{background:var(--blue-soft);color:var(--blue-deep)}
.menubar .m-right{margin-left:auto;font-size:11px;color:var(--muted);padding-right:8px}
/* ---------- toolbar ---------- */
.toolbar{flex:0 0 auto;display:flex;align-items:stretch;gap:2px;
  background:linear-gradient(#f2f6fc,#e2eaf5);border-bottom:1px solid #c9d6ea;
  padding:5px 8px;user-select:none;overflow-x:auto}
.tbtn{border:1px solid transparent;background:transparent;border-radius:5px;min-width:64px;
  padding:5px 10px 4px;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;font-family:inherit}
.tbtn .ic{width:26px;height:26px;border-radius:6px;display:flex;align-items:center;justify-content:center;
  background:linear-gradient(#ffffff,#e7eefb);border:1px solid #c4d4ec;box-shadow:inset 0 1px 0 #fff}
.tbtn .ic svg{width:15px;height:15px}
.tbtn span{font-size:10.5px;color:var(--ink-2);font-weight:600;white-space:nowrap}
.tbtn:hover{background:linear-gradient(#eaf3ff,#d3e6ff);border-color:var(--blue);
  box-shadow:0 0 0 1px #bfdbfe,0 2px 6px rgba(29,78,216,.25)}
.tbtn:hover span{color:var(--blue-deep)}
.tbtn.primary .ic{background:linear-gradient(135deg,#1e40af,#1d4ed8);border-color:#16307a}
.tbtn.danger .ic{color:var(--err)}
.tsep{width:1px;background:#c9d6ea;margin:4px 5px}
.tspacer{flex:1}
/* ---------- address bar ---------- */
.addrbar{flex:0 0 auto;display:flex;align-items:center;gap:8px;background:#fff;
  border-bottom:1px solid var(--line);padding:7px 10px}
.addrbar .fld{flex:1;display:flex;align-items:center;gap:8px;height:28px;border:1px solid #c4d4ec;
  border-radius:5px;background:var(--blue-soft);padding:0 10px}
.addrbar .fld .dot{width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 6px #22c55e}
.addrbar .fld .url{font-family:var(--mono);font-size:12px;color:var(--blue-deep);font-weight:600;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.addrbar .fld .lock{margin-left:auto;font-size:10px;color:var(--ok);background:var(--ok-bg);
  border:1px solid #86efac;border-radius:10px;padding:1px 8px;font-weight:700;white-space:nowrap}
.pill-btn{height:28px;padding:0 12px;border-radius:5px;border:1px solid #c4d4ec;
  background:linear-gradient(#fff,#eef3fb);font-size:11.5px;font-weight:700;color:var(--ink-2);
  cursor:pointer;font-family:inherit;white-space:nowrap}
.pill-btn.blue{background:linear-gradient(135deg,#1e40af,#1d4ed8);color:#fff;border-color:#16307a}
.pill-btn:hover{border-color:var(--blue)}
/* ---------- body split ---------- */
.body{flex:1;min-height:0;display:flex}
.sidebar{width:218px;flex:0 0 218px;background:#f0f5fb;border-right:1px solid #d5dfef;
  padding:10px 8px;overflow-y:auto;user-select:none}
.sb-group{font-size:9.5px;font-weight:800;letter-spacing:1.2px;color:var(--muted);
  padding:10px 10px 5px;text-transform:uppercase}
.sb-item{display:flex;align-items:center;gap:9px;padding:7px 10px;border-radius:6px;cursor:pointer;
  font-size:12.5px;color:var(--ink-2);border:1px solid transparent;margin-bottom:1px}
.sb-item svg{width:15px;height:15px;stroke:currentColor;flex:0 0 15px}
.sb-item .cnt{margin-left:auto;font-size:10px;font-weight:800;background:#dbe6f6;color:#3b5ea8;
  border-radius:9px;padding:1px 7px}
.sb-item .cnt.red{background:var(--err-bg);color:var(--err)}
.sb-item .cnt.grn{background:var(--ok-bg);color:var(--ok)}
.sb-item:hover{background:#e3edfb;color:var(--blue-deep)}
.sb-item.active{background:linear-gradient(135deg,#1e40af,#1d4ed8);color:#fff;font-weight:600;
  box-shadow:0 2px 8px rgba(29,78,216,.35)}
.sb-item.active .cnt{background:#ffffff2e;color:#fff}
.sb-note{margin:14px 10px;padding:9px 10px;border:1px dashed #b6c8e0;border-radius:7px;
  font-size:10.5px;color:var(--ink-2);line-height:1.5;background:#fff}
.sb-note b{color:var(--blue-deep)}
.content{flex:1;min-width:0;overflow-y:auto;padding:16px 18px 22px;background:var(--bg)}
.panel{display:none;animation:fadein .18s ease}
.panel.active{display:block}
@keyframes fadein{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.p-head{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.p-head h2{font-size:17px;font-weight:700;color:var(--ink)}
.p-head .sub{font-size:11.5px;color:var(--muted)}
.p-head .right{margin-left:auto;display:flex;gap:8px}
/* ---------- generic ---------- */
.card{background:var(--panel);border:1px solid var(--line);border-radius:9px;
  box-shadow:0 1px 2px rgba(15,23,42,.04);margin-bottom:14px}
.card .card-h{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid var(--line);
  font-size:12.5px;font-weight:700;color:var(--ink-2);flex-wrap:wrap}
.card .card-h .r{margin-left:auto;font-weight:500;font-size:11px;color:var(--muted)}
.card .card-b{padding:13px 14px}
.btn{height:28px;padding:0 12px;border-radius:5px;border:1px solid #c4d4ec;cursor:pointer;
  background:linear-gradient(#ffffff,#eef3fb);font-size:11.5px;font-weight:700;color:var(--ink-2);
  font-family:inherit;display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.btn:hover{border-color:var(--blue);color:var(--blue-deep)}
.btn.blue{background:linear-gradient(135deg,#1e40af,#1d4ed8);color:#fff;border-color:#16307a}
.btn.blue:hover{filter:brightness(1.08);color:#fff}
.btn.danger{color:var(--err)} .btn.danger:hover{border-color:var(--err);color:var(--err)}
.btn.small{height:24px;padding:0 9px;font-size:10.5px}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:700;
  border-radius:10px;padding:2px 9px;border:1px solid}
.chip.ok{color:var(--ok);background:var(--ok-bg);border-color:#86efac}
.chip.err{color:var(--err);background:var(--err-bg);border-color:#fca5a5}
.chip.warn{color:var(--warn);background:var(--warn-bg);border-color:#fcd34d}
.chip.info{color:var(--blue-deep);background:var(--blue-soft);border-color:var(--blue-line)}
.chip.gray{color:#475569;background:#e2e8f0;border-color:#cbd5e1}
.chip.purple{color:var(--purple);background:var(--purple-bg);border-color:#c4b5fd}
.chip.orange{color:#9a3412;background:#ffedd5;border-color:#fdba74}
.chip .d{width:6px;height:6px;border-radius:50%;background:currentColor}
.mono{font-family:var(--mono)}
.note{background:var(--blue-soft);border:1px solid var(--blue-line);color:var(--blue-deep);
  border-radius:8px;padding:10px 12px;font-size:11.5px;line-height:1.6;margin-top:12px}
.note.orange{background:#fff7ed;border-color:#fdba74;color:#9a3412}
.note.amber{background:var(--warn-bg);border-color:#fcd34d;color:#854d0e}
.note.grn{background:var(--ok-bg);border-color:#86efac;color:#166534}
/* ---------- dashboard stats ---------- */
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:14px}
.stat{background:#fff;border:1px solid var(--line);border-radius:9px;padding:13px 15px;position:relative;overflow:hidden}
.stat::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--blue)}
.stat.g::before{background:var(--ok)} .stat.r::before{background:var(--err)} .stat.w::before{background:var(--warn)}
.stat .v{font-size:22px;font-weight:800;color:var(--ink)}
.stat .l{font-size:10.5px;color:var(--ink-2);margin-top:2px;font-weight:600}
.stat .d{position:absolute;right:12px;top:12px;font-size:10px;color:var(--muted)}
.dash-row{display:grid;grid-template-columns:1.4fr 1fr;gap:12px;margin-bottom:14px}
.kv{display:grid;grid-template-columns:120px 1fr;row-gap:7px;column-gap:10px;font-size:12px;padding:4px 14px 12px}
.kv .k{color:var(--muted);font-weight:600}
.kv .v{color:var(--ink);font-weight:600;min-width:0;overflow:hidden;text-overflow:ellipsis}
.kv .v .chip{margin-left:6px}
/* ---------- LAN rows ---------- */
.lrow{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px dashed #eef2f8;flex-wrap:wrap}
.lrow:last-child{border-bottom:none}
.lrow .lk{min-width:210px;font-size:12.5px;font-weight:700;color:var(--ink)}
.lrow .lk small{display:block;font-size:10px;color:var(--muted);font-weight:600;margin-top:1px}
.lrow .lv{font-family:var(--mono);font-size:11px;color:var(--blue-deep);background:var(--blue-soft);
  border:1px solid var(--blue-line);border-radius:6px;padding:5px 9px;max-width:400px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lrow .lv.plain{background:#fff;color:var(--ink-2);border-color:var(--line);max-width:340px;white-space:normal;line-height:1.45}
.lrow .sp{flex:1}
.lrow .ops{display:flex;gap:6px;margin-left:auto}
/* ---------- forms ---------- */
.frow{display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
.frow label{font-weight:700;font-size:12px;color:var(--ink-2);min-width:150px}
.inp,select.inp{height:30px;border:1px solid #c4d4ec;border-radius:6px;padding:0 10px;
  font-size:12px;font-family:inherit;color:var(--ink);background:#fff;outline:none;min-width:220px}
.inp:focus{border-color:var(--blue);box-shadow:0 0 0 2px #bfdbfe}
.inp.narrow{min-width:90px;max-width:130px}
.form{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:4px 0 14px}
.f-row{background:#fff;border:1px solid var(--line);border-radius:8px;padding:11px 14px}
.f-row label{display:block;font-size:11px;font-weight:800;color:var(--ink-2);margin-bottom:6px}
.f-row .inp,.f-row select{width:100%;height:30px;border:1px solid #c4d4ec;border-radius:6px;
  padding:0 10px;font-size:12px;font-family:inherit;color:var(--ink);background:#fff;outline:none}
.f-row .hint{font-size:10px;color:var(--muted);margin-top:5px}
.radio{display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border:1px solid #c4d4ec;
  border-radius:8px;background:#fff;cursor:pointer;font-size:12px;font-weight:600;color:var(--ink-2)}
.radio.on{border-color:var(--blue);background:var(--blue-soft);color:var(--blue-deep);box-shadow:0 0 0 1px var(--blue-line)}
.radio .rdot{width:14px;height:14px;border-radius:50%;border:2px solid #94a3b8;position:relative;flex:0 0 14px}
.radio.on .rdot{border-color:var(--blue)}
.radio.on .rdot::after{content:'';position:absolute;inset:2px;border-radius:50%;background:var(--blue)}
/* ---------- toggle rows ---------- */
.tgl{display:flex;gap:12px;align-items:flex-start;padding:9px 0;border-bottom:1px dashed #eef2f8}
.tgl:last-child{border-bottom:none}
.tgl .sw{flex:0 0 40px;padding-top:2px}
.switch{position:relative;display:inline-block;width:40px;height:20px;border-radius:10px;background:#cbd5e1;
  cursor:pointer;transition:.15s;vertical-align:middle}
.switch::after{content:'';position:absolute;left:2px;top:2px;width:16px;height:16px;border-radius:50%;
  background:#fff;transition:.15s;box-shadow:0 1px 3px rgba(0,0,0,.25)}
.switch.on{background:var(--blue)}
.switch.on::after{left:22px}
.switch.green.on{background:var(--ok)}
.tgl b{font-size:12.5px;color:var(--ink)}
.tgl p{font-size:11px;color:var(--muted);line-height:1.5;margin-top:2px;max-width:640px}
/* ---------- tables ---------- */
table.tbl{width:100%;border-collapse:collapse;font-size:12px}
.tbl th{text-align:left;font-size:10px;letter-spacing:.8px;text-transform:uppercase;color:var(--muted);
  padding:8px 10px;border-bottom:1px solid var(--line);background:#f8fafc;font-weight:800;white-space:nowrap}
.tbl td{padding:7px 10px;border-bottom:1px solid #eef2f8;color:var(--ink-2);vertical-align:middle}
.tbl tr:last-child td{border-bottom:none}
.tbl tr:hover td{background:var(--blue-soft)}
.tbl .doc{color:var(--ink);font-weight:600;max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tbl .id{font-family:var(--mono);color:var(--muted);font-size:11px}
.filters{display:flex;gap:7px;margin-bottom:12px;align-items:center;flex-wrap:wrap}
.fchip{font-size:11px;font-weight:700;padding:4px 12px;border-radius:14px;border:1px solid #c4d4ec;
  background:#fff;color:var(--ink-2);cursor:pointer}
.fchip.on{background:linear-gradient(135deg,#1e40af,#1d4ed8);color:#fff;border-color:#16307a}
.fchip .n{opacity:.75;font-weight:800;margin-left:3px}
/* ---------- progress ---------- */
.prog{width:130px;height:12px;border:1px solid #b6c8e0;border-radius:7px;background:#eef2f8;overflow:hidden;position:relative}
.prog i{display:block;height:100%;background:linear-gradient(90deg,#1d4ed8,#3b82f6);border-radius:6px;position:relative}
.prog i::after{content:'';position:absolute;inset:0;
  background:repeating-linear-gradient(45deg,rgba(255,255,255,.28) 0 6px,transparent 6px 12px);
  animation:crawl 1s linear infinite}
.prog.done i{background:linear-gradient(90deg,#16a34a,#22c55e)}.prog.done i::after{display:none}
.prog.fail i{background:#ef4444}.prog.fail i::after{display:none}
@keyframes crawl{from{background-position:0 0}to{background-position:17px 0}}
/* ---------- printers ---------- */
.pgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.pcard{background:#fff;border:1px solid var(--line);border-radius:9px;padding:13px 15px;position:relative}
.pcard .top{display:flex;align-items:center;gap:10px}
.pcard .picon{width:38px;height:38px;border-radius:8px;background:var(--blue-soft);border:1px solid var(--blue-line);
  display:flex;align-items:center;justify-content:center;flex:0 0 38px}
.pcard .picon svg{width:19px;height:19px;stroke:var(--blue-deep)}
.pcard .nm{font-size:13.5px;font-weight:700;color:var(--ink)}
.pcard .mdl{font-size:11px;color:var(--muted);margin-top:1px}
.pcard .badge{position:absolute;top:12px;right:12px;font-size:9.5px;font-weight:800;letter-spacing:.6px;
  background:linear-gradient(135deg,#1e40af,#1d4ed8);color:#fff;border-radius:9px;padding:2px 9px}
.pcard .st{margin:10px 0;display:flex;gap:14px;font-size:11px;color:var(--ink-2);flex-wrap:wrap}
.pcard .st b{color:var(--ink)}
.pcard .url{font-family:var(--mono);font-size:10.5px;color:var(--blue-deep);background:var(--blue-soft);
  border:1px solid var(--blue-line);border-radius:6px;padding:6px 9px;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;display:flex;align-items:center;gap:8px}
.pcard .url .cp{margin-left:auto;border:none;background:none;cursor:pointer;color:var(--blue-deep);
  font-size:10px;font-weight:800;font-family:inherit}
.pcard .ops{display:flex;gap:7px;margin-top:11px;flex-wrap:wrap}
.pcard.off{opacity:.82}
/* ---------- logs ---------- */
.logbox{background:#0d1731;border:1px solid #16307a;border-radius:9px;padding:12px 14px;
  font-family:var(--mono);font-size:11.5px;line-height:1.75;color:#c7d6f5;max-height:430px;overflow:auto}
.logbox .ts{color:#5b6f9e}
.logbox .lv{font-weight:800;display:inline-block;width:52px}
.logbox .lv.I{color:#4ade80}.logbox .lv.W{color:#fbbf24}.logbox .lv.E{color:#f87171}
.logbox .hl{color:#7cb1ff}
/* ---------- kpi row + section headings (Options design family) ---------- */
.kpi{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.kpi .kc{flex:1;min-width:130px;background:#fff;border:1px solid var(--line);border-radius:9px;
  padding:11px 14px;position:relative;overflow:hidden}
.kpi .kc::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--blue)}
.kpi .kc.g::before{background:var(--ok)}.kpi .kc.r::before{background:var(--err)}.kpi .kc.w::before{background:var(--warn)}
.kpi .kc b{font-size:19px;color:var(--ink)}
.kpi .kc small{display:block;font-size:9.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.7px;font-weight:800;margin-top:2px}
.kpi .kc .chip{position:absolute;right:10px;top:10px}
.h3sec{font-size:12.5px;font-weight:800;color:var(--blue-deep);margin:16px 0 8px;
  padding-bottom:5px;border-bottom:1px dashed var(--blue-line)}
/* ---------- status bar ---------- */
.statusbar{flex:0 0 auto;height:24px;display:flex;align-items:stretch;gap:1px;
  background:linear-gradient(#eef3fb,#dde7f5);border-top:1px solid #b6c8e0;padding:0 6px;user-select:none;overflow:hidden}
.sb-pane{display:flex;align-items:center;gap:6px;padding:0 11px;font-size:10.5px;color:var(--ink-2);
  border-right:1px solid #c4d2e8;font-weight:600;white-space:nowrap}
.sb-pane .dot{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 5px #22c55e}
.sb-pane.grow{flex:1;border-right:none;color:var(--muted);font-weight:500}
.sb-pane b{color:var(--ink)}
/* ---------- menubar dropdowns ---------- */
.menubar{position:relative;z-index:50}
.menu{position:relative;height:100%;display:flex;align-items:center}
.menu-label{font-size:12px;color:var(--ink);padding:3px 9px;border-radius:3px;cursor:default;white-space:nowrap}
.menu:hover .menu-label{background:var(--blue-soft);color:var(--blue-deep)}
.menu.open .menu-label{background:linear-gradient(135deg,#1e40af,#1d4ed8);color:#fff}
.dd{display:none;position:absolute;top:25px;left:0;min-width:252px;background:#fff;
  border:1px solid #c4d4ec;border-radius:6px;box-shadow:0 14px 34px rgba(15,23,42,.24);
  padding:5px;z-index:900}
.menu.open .dd{display:block;animation:fadein .12s ease}
.dd-it{display:flex;align-items:center;gap:9px;padding:6px 10px;font-size:12px;color:var(--ink);
  border-radius:4px;cursor:pointer;white-space:nowrap}
.dd-it .ic{width:17px;text-align:center;flex:0 0 17px;font-size:12.5px}
.dd-it .sc{margin-left:auto;font-size:10.5px;color:var(--muted);padding-left:18px}
.dd-it:hover{background:var(--blue-soft);color:var(--blue-deep)}
.dd-it.dis{color:var(--muted);pointer-events:none}
.dd-it.chk::after{content:'\2713';color:var(--blue);font-weight:800;margin-left:auto;font-size:11px}
.dd-it.chk:hover::after{color:var(--blue-deep)}
.dd-sep{height:1px;background:var(--line);margin:4px 6px}
.dd-title{font-size:9.5px;font-weight:800;letter-spacing:1px;color:var(--muted);
  text-transform:uppercase;padding:5px 10px 3px}
/* ---------- QR tiles ---------- */
.qr-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.qr-tile{background:#fff;border:1px solid var(--line);border-radius:9px;padding:12px;text-align:center;
  cursor:zoom-in;position:relative}
.qr-tile:hover{border-color:var(--blue);box-shadow:0 4px 14px rgba(29,78,216,.18)}
.qr-tile .qbox{width:116px;height:116px;margin:0 auto;background:#fff;border:1px solid var(--line);
  border-radius:6px;padding:6px}
.qr-tile .qbox svg{width:100%;height:100%;display:block}
.qr-tile b{display:block;font-size:12px;color:var(--ink);margin-top:8px}
.qr-tile small{display:block;font-size:10px;color:var(--muted);margin-top:3px;line-height:1.45}
.qr-tile .zoom{position:absolute;top:8px;right:8px;font-size:9.5px;color:var(--blue-deep);
  background:var(--blue-soft);border:1px solid var(--blue-line);border-radius:9px;
  padding:1px 7px;font-weight:800}
/* ---------- modal ---------- */
.modal-back{position:fixed;inset:0;background:rgba(4,10,30,.55);display:none;
  align-items:center;justify-content:center;z-index:1000}
.modal-back.show{display:flex;animation:fadein .15s ease}
.modal{background:#fff;border-radius:12px;box-shadow:0 40px 90px rgba(2,8,35,.5);
  width:min(460px,92vw);overflow:hidden;border:1px solid #16307a;max-height:88vh;overflow-y:auto}
.modal.wide{width:min(740px,94vw)}
.modal .re-step{display:flex;align-items:center;gap:8px;margin:14px 0 8px}
.modal .re-step:first-child{margin-top:0}
.modal .re-step .n{width:20px;height:20px;flex:0 0 20px;border-radius:50%;background:linear-gradient(135deg,#1e40af,#1d4ed8);
  color:#fff;font-size:11px;font-weight:800;display:flex;align-items:center;justify-content:center}
.modal .re-step b{font-size:12px;color:var(--blue-deep);letter-spacing:.4px;text-transform:uppercase}
.modal .re-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.modal .re-grid .full{grid-column:1/-1}
.modal label.rl{display:block;font-size:10px;font-weight:800;color:var(--ink-2);margin-bottom:4px;letter-spacing:.4px}
.modal .inp2{width:100%;height:29px;border:1px solid #c4d4ec;border-radius:6px;padding:0 9px;font-size:11.5px;
  font-family:inherit;color:var(--ink);background:#fff;outline:none}
.modal .inp2:focus{border-color:var(--blue);box-shadow:0 0 0 2px #bfdbfe}
.modal .hint2{font-size:9.5px;color:var(--muted);margin-top:3px;line-height:1.4}
.pattern-chip{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:10.5px;
  color:var(--blue-deep);background:var(--blue-soft);border:1px solid var(--blue-line);border-radius:6px;
  padding:4px 9px;cursor:pointer;margin:0 6px 6px 0}
.pattern-chip small{font-family:'Segoe UI',sans-serif;color:var(--muted);font-size:9.5px}
.pattern-chip:hover{border-color:var(--blue);background:#dbeafe}
.pattern-chip .use{font-size:9px;font-weight:800;color:#fff;background:var(--blue);border-radius:4px;padding:1px 6px}
.modal .m-h{height:38px;flex:0 0 38px;background:linear-gradient(135deg,#1e3a8a,#1d4ed8);color:#fff;
  display:flex;align-items:center;padding:0 14px;font-size:13px;font-weight:700;gap:8px;position:sticky;top:0}
.modal .m-h .x{margin-left:auto;width:26px;height:26px;border:none;background:transparent;color:#fff;
  font-size:14px;cursor:pointer;border-radius:5px;font-family:inherit}
.modal .m-h .x:hover{background:#dc2626}
.modal .m-b{padding:16px;text-align:center}
.modal .m-b .mq{width:232px;height:232px;margin:0 auto;border:1px solid var(--line);
  border-radius:8px;padding:10px;background:#fff}
.modal .m-b .mq svg{width:100%;height:100%;display:block}
.modal .m-b .murl{font-family:var(--mono);font-size:11px;color:var(--blue-deep);background:var(--blue-soft);
  border:1px solid var(--blue-line);border-radius:7px;padding:8px 10px;margin-top:12px;
  word-break:break-all;line-height:1.5;text-align:left}
.modal .m-b .mops{display:flex;gap:8px;justify-content:center;margin-top:12px}
.modal .m-b .mnote{font-size:10.5px;color:var(--muted);margin-top:10px;line-height:1.5}
.mtable{width:100%;border-collapse:collapse;font-size:12px;text-align:left;margin-top:4px}
.mtable td{padding:6px 8px;border-bottom:1px dashed #eef2f8;color:var(--ink-2)}
.mtable td:first-child{font-family:var(--mono);color:var(--blue-deep);font-weight:700;white-space:nowrap;width:130px}
/* ---------- toasts ---------- */
#toasts{position:fixed;right:18px;bottom:34px;z-index:1200;display:flex;flex-direction:column;gap:8px}
.toast{background:#0f172a;color:#e2e8f0;font-size:12px;padding:9px 14px;border-radius:8px;
  box-shadow:0 10px 26px rgba(2,8,35,.4);border-left:3px solid var(--blue);max-width:360px;
  animation:fadein .18s ease;line-height:1.45}
.toast.ok{border-left-color:var(--ok)} .toast.warn{border-left-color:var(--warn)}
.design-note{position:fixed;right:20px;bottom:8px;color:#5b74b8;font-size:10.5px;letter-spacing:.4px;z-index:99}
@media (max-width:1100px){
  .stats{grid-template-columns:repeat(2,1fr)}
  .pgrid{grid-template-columns:1fr}
  .dash-row{grid-template-columns:1fr}
  .form{grid-template-columns:1fr}
}
</style>
<script id="bootjson" type="application/json">__ADVPRINT_BOOT_JSON__</script>
</head>
<body>
<div class="desktop">
  <div class="window">

    <!-- ================= TITLE BAR ================= -->
    <div class="titlebar">
      <div class="logo">AP</div>
      <div class="t-main">AdvPrint Pro — Printing Hub <small>· All-in-One Console v3.2.1 · AI-Lab · THE ONE UI</small></div>
      <div class="spacer"></div>
      <button class="winbtn">&#x2500;</button>
      <button class="winbtn">&#x25A1;</button>
      <button class="winbtn close">&#x2715;</button>
    </div>

    <!-- ================= MENU BAR (working dropdowns) ================= -->
    <div class="menubar">
      <div class="menu">
        <span class="menu-label">File</span>
        <div class="dd">
          <div class="dd-it" data-goto="queue"><span class="ic">&#9889;</span>New print job&#8230;<span class="sc">Ctrl+N</span></div>
          <div class="dd-it" data-goto="dropzone"><span class="ic">&#128449;</span>Open DropZone folder<span class="sc">Ctrl+D</span></div>
          <div class="dd-it" data-goto="rules"><span class="ic">&#128196;</span>Import auto-print rules&#8230;</div>
          <div class="dd-it" data-goto="hub"><span class="ic">&#11015;</span>Export settings (config.json)</div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-goto="debug"><span class="ic">&#128424;</span>Print test page<span class="sc">Ctrl+T</span></div>
          <div class="dd-it" data-toast="Demo: opens the phone Send portal QR in the real app"><span class="ic">&#128241;</span>Share Send portal&#8230;</div>
          <div class="dd-sep"></div>
          <div class="dd-it dis"><span class="ic">&#128682;</span>Exit hub (stops printing)<span class="sc">Alt+F4</span></div>
        </div>
      </div>
      <div class="menu">
        <span class="menu-label">View</span>
        <div class="dd">
          <div class="dd-title">Tabs — the one UI</div>
          <div class="dd-it" data-goto="dashboard"><span class="ic">&#9635;</span>Dashboard<span class="sc">Ctrl+1</span></div>
          <div class="dd-it" data-goto="queue"><span class="ic">&#9776;</span>Queue<span class="sc">Ctrl+2</span></div>
          <div class="dd-it" data-goto="history"><span class="ic">&#128218;</span>History<span class="sc">Ctrl+3</span></div>
          <div class="dd-it" data-goto="printers"><span class="ic">&#128424;</span>Printers<span class="sc">Ctrl+4</span></div>
          <div class="dd-it" data-goto="lan"><span class="ic">&#127760;</span>LAN Sharing<span class="sc">Ctrl+5</span></div>
          <div class="dd-it" data-goto="dropzone"><span class="ic">&#128449;</span>DropZone<span class="sc">Ctrl+6</span></div>
          <div class="dd-it" data-goto="connections"><span class="ic">&#128279;</span>Connections<span class="sc">Ctrl+7</span></div>
          <div class="dd-it" data-goto="hub"><span class="ic">&#9881;</span>Hub<span class="sc">Ctrl+8</span></div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-goto="rules"><span class="ic">&#9878;</span>Rules</div>
          <div class="dd-it" data-goto="power"><span class="ic">&#9889;</span>Power Switches</div>
          <div class="dd-it" data-goto="debug"><span class="ic">&#128295;</span>Debug &amp; Tools</div>
          <div class="dd-it" data-goto="audit"><span class="ic">&#128220;</span>Audit trail</div>
          <div class="dd-it" data-goto="logs"><span class="ic">&#128220;</span>Logs</div>
          <div class="dd-it" data-goto="settings"><span class="ic">&#9881;</span>Settings</div>
          <div class="dd-it" data-goto="about"><span class="ic">&#8505;</span>About</div>
          <div class="dd-sep"></div>
          <div class="dd-it chk" data-chk="1"><span class="ic">&#9635;</span>Status bar<span class="sc">F5</span></div>
          <div class="dd-it" data-toast="Demo: full-screen hides the desktop backdrop"><span class="ic">&#9974;</span>Full screen<span class="sc">F11</span></div>
        </div>
      </div>
      <div class="menu">
        <span class="menu-label">Queue</span>
        <div class="dd">
          <div class="dd-it" data-toast="Queue PAUSED — new jobs wait until resumed" data-ttype="warn"><span class="ic">&#9208;</span>Pause queue</div>
          <div class="dd-it" data-toast="Queue RESUMED — held jobs start printing" data-ttype="ok"><span class="ic">&#9654;</span>Resume queue</div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-goto="history"><span class="ic">&#8635;</span>Reprint last job</div>
          <div class="dd-it" data-goto="debug" data-toast="ALL held jobs released to their printers" data-ttype="ok"><span class="ic">&#10006;</span>Release ALL held jobs</div>
          <div class="dd-it" data-goto="history"><span class="ic">&#129529;</span>Clear finished jobs</div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-goto="queue"><span class="ic">&#8594;</span>Open Queue tab<span class="sc">Ctrl+2</span></div>
        </div>
      </div>
      <div class="menu">
        <span class="menu-label">History</span>
        <div class="dd">
          <div class="dd-it" data-goto="history"><span class="ic">&#8635;</span>Reprint selected jobs</div>
          <div class="dd-it" data-act="export-history"><span class="ic">&#11015;</span>Export CSV&#8230;</div>
          <div class="dd-it" data-act="queue-clear-finished"><span class="ic">&#128465;</span>Clear ALL finished jobs&#8230;</div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-goto="history"><span class="ic">&#8594;</span>Open History tab<span class="sc">Ctrl+3</span></div>
        </div>
      </div>
      <div class="menu">
        <span class="menu-label">Printers</span>
        <div class="dd">
          <div class="dd-it" data-goto="printers"><span class="ic">&#128424;</span>Printers tab<span class="sc">Ctrl+4</span></div>
          <div class="dd-it" data-goto="lan"><span class="ic">&#10133;</span>Add IP printer&#8230;</div>
          <div class="dd-it" data-goto="printers"><span class="ic">&#9733;</span>Set default printer</div>
          <div class="dd-it" data-goto="printers"><span class="ic">&#9208;</span>Printer status hold</div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-goto="debug"><span class="ic">&#128424;</span>Print test page<span class="sc">Ctrl+T</span></div>
        </div>
      </div>
      <div class="menu">
        <span class="menu-label">Network</span>
        <div class="dd">
          <div class="dd-it" data-goto="connections"><span class="ic">&#128279;</span>Connections tab<span class="sc">Ctrl+7</span></div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-qr="send"><span class="ic">&#128241;</span>Send portal QR&#8230;</div>
          <div class="dd-it" data-qr="invite"><span class="ic">&#128101;</span>Invite another PC (QR)&#8230;</div>
          <div class="dd-it" data-qr="ipp"><span class="ic">&#128424;</span>IPP printer URL (QR)&#8230;</div>
          <div class="dd-it" data-qr="hub"><span class="ic">&#9635;</span>Hub console QR&#8230;</div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-act="copy-hub-url"><span class="ic">&#128203;</span>Copy hub URL</div>
          <div class="dd-it" data-act="fw-allow"><span class="ic">&#128293;</span>Allow hub port in firewall</div>
          <div class="dd-it" data-act="fw-status"><span class="ic">&#128246;</span>Test LAN</div>
        </div>
      </div>
      <div class="menu">
        <span class="menu-label">Hub</span>
        <div class="dd">
          <div class="dd-it" data-goto="hub"><span class="ic">&#9881;</span>Hub settings tab<span class="sc">Ctrl+8</span></div>
          <div class="dd-it" data-act="restart"><span class="ic">&#128260;</span>Restart hub</div>
          <div class="dd-it" data-act="rotate-token"><span class="ic">&#128273;</span>Rotate token&#8230;</div>
          <div class="dd-it" data-tool="service-install"><span class="ic">&#128295;</span>Install as Windows service</div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-tool="check-update"><span class="ic">&#11014;</span>Check for updates</div>
          <div class="dd-it" data-goto="hub"><span class="ic">&#8594;</span>Open Hub tab</div>
        </div>
      </div>
      <div class="menu">
        <span class="menu-label">Tools</span>
        <div class="dd">
          <div class="dd-it" data-act="testprint"><span class="ic">&#9889;</span>REAL test print<span class="sc">Ctrl+T</span></div>
          <div class="dd-it" data-goto="debug"><span class="ic">&#129514;</span>Full self-test</div>
          <div class="dd-it" data-goto="debug"><span class="ic">&#128027;</span>Debug mode</div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-goto="logs"><span class="ic">&#128220;</span>Open Logs</div>
          <div class="dd-it" data-goto="audit"><span class="ic">&#128220;</span>Open Audit trail</div>
          <div class="dd-it" data-goto="hub"><span class="ic">&#128193;</span>Open config.json</div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-goto="extension"><span class="ic">&#128279;</span>Extension pairing</div>
        </div>
      </div>
      <div class="menu">
        <span class="menu-label">Help</span>
        <div class="dd">
          <div class="dd-it" data-act="open-docs"><span class="ic">&#10067;</span>Quick start guide</div>
          <div class="dd-it" data-modal="keys"><span class="ic">&#9000;</span>Keyboard shortcuts</div>
          <div class="dd-it" data-act="open-github"><span class="ic">&#127760;</span>GitHub repository</div>
          <div class="dd-sep"></div>
          <div class="dd-it" data-goto="about"><span class="ic">&#8505;</span>About AdvPrint Pro<span class="sc">F1</span></div>
        </div>
      </div>
      <span class="m-right"><b>AdvPrint Pro Printing Hub</b> · 10.26.94.206:9235 · token auth ON</span>
    </div>

    <!-- ================= TOOLBAR =================
         v3.2.3 ONE UI, ONE BUTTON: only the four REAL actions here -
         every tab switch lives in the sidebar (the ten nav buttons that
         duplicated it are gone), LAN/IPP state shows as status chips. -->
    <div class="toolbar">
      <button class="tbtn primary" id="tbNew">
        <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg></span><span>New Job</span>
      </button>
      <button class="tbtn" id="tbPause">
        <span class="ic"><svg viewBox="0 0 24 24" fill="none"><rect x="6" y="5" width="4" height="14" rx="1" fill="#d97706"/><rect x="14" y="5" width="4" height="14" rx="1" fill="#d97706"/></svg></span><span>Pause Queue</span>
      </button>
      <button class="tbtn" id="tbRelease">
        <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2"><polygon points="7 4 19 12 7 20" fill="#16a34a"/></svg></span><span>Release ALL</span>
      </button>
      <button class="tbtn" id="tbTest">
        <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="#1e40af" stroke-width="2"><path d="M6 9V3h12v6M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8" rx="1"/></svg></span><span>Test Page</span>
      </button>
      <div class="tspacer"></div>
      <span class="chip ok" id="chipLan" style="font-size:11.5px">LAN &#8212; ON</span>
      <span class="chip ok" id="chipIpp" style="font-size:11.5px">IPP &#8212; READY</span>
    </div>

    <!-- ================= ADDRESS BAR ================= -->
    <div class="addrbar">
      <div class="fld">
        <span class="dot"></span>
        <span class="url">http://10.26.94.206:9235/ui — AdvPrint Printing Hub · ALL-IN-ONE</span>
        <span class="lock">&#128274; token ok</span>
      </div>
      <!-- v3.2.3: the five pill buttons are GONE - QRs live in the Network
           menu + LAN tab, tab navigation lives in the sidebar -->
    </div>

    <!-- ================= BODY ================= -->
    <div class="body">

      <!-- -------- SIDEBAR TREE -------- -->
      <aside class="sidebar">
        <div class="sb-group">Overview</div>
        <div class="sb-item active" data-tab="dashboard">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/></svg>
          Dashboard
        </div>
        <div class="sb-item" data-tab="queue">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/></svg>
          Queue <span class="cnt">4</span>
        </div>
        <div class="sb-item" data-tab="history">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>
          History <span class="cnt">12</span>
        </div>
        <div class="sb-group">Devices</div>
        <div class="sb-item" data-tab="printers">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M6 9V3h12v6M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8" rx="1"/></svg>
          Printers <span class="cnt">4</span>
        </div>
        <div class="sb-item" data-tab="lan">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M10 14a5 5 0 007.07 0l3.18-3.18a5 5 0 00-7.07-7.07L11.7 5.23"/><path d="M14 10a5 5 0 00-7.07 0L3.75 13.18a5 5 0 007.07 7.07l1.47-1.47"/></svg>
          LAN Sharing <span class="cnt grn">ON</span>
        </div>
        <div class="sb-item" data-tab="dropzone">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/><path d="M12 11v6M9 14l3 3 3-3"/></svg>
          DropZone <span class="cnt">0</span>
        </div>
        <div class="sb-group">Network</div>
        <div class="sb-item" data-tab="connections">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M10 14a5 5 0 007.07 0l3.18-3.18a5 5 0 00-7.07-7.07L11.7 5.23"/><path d="M14 10a5 5 0 00-7.07 0L3.75 13.18a5 5 0 007.07 7.07l1.47-1.47"/></svg>
          Connections <span class="cnt">2</span>
        </div>
        <div class="sb-item" data-tab="hub">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 8h.01M7 17h.01"/></svg>
          Hub
        </div>
        <div class="sb-group">Automation</div>
        <div class="sb-item" data-tab="rules">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M13 3l-2 6H7l4 5-1 7 6-8h4l-3-6h-2l2-4z"/></svg>
          Rules <span class="cnt">6</span>
        </div>
        <div class="sb-group">Extension</div>
        <div class="sb-item" data-tab="power">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M13 2L4 14h6l-1 8 9-12h-6z"/></svg>
          Power Switches
        </div>
        <div class="sb-item" data-tab="browser">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.6 3 14.4 0 18M12 3c-3 3.6-3 14.4 0 18"/></svg>
          Browser
        </div>
        <div class="sb-item" data-tab="extension">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M14 7V3h-4v4H6v4h4v4h4v-4h4V7z"/></svg>
          Extension <span class="cnt">2</span>
        </div>
        <div class="sb-group">System</div>
        <div class="sb-item" data-tab="debug">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="12" cy="13" r="5"/><path d="M12 8V4M9 9L6 6M15 9l3-3M7 13H3M18 13h3M9 17l-3 3M15 17l3 3"/></svg>
          Debug <span class="cnt red">1</span>
        </div>
        <div class="sb-item" data-tab="audit">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/></svg>
          Audit
        </div>
        <div class="sb-item" data-tab="logs">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M4 17l5-5-5-5M12 19h8"/></svg>
          Logs
        </div>
        <div class="sb-item" data-tab="settings">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 00-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 00-2-1.2L14 3h-4l-.5 2.6a7 7 0 00-2 1.2l-2.4-1-2 3.4 2 1.6a7 7 0 000 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 002 1.2L10 21h4l.5-2.6a7 7 0 002-1.2l2.4 1 2-3.4-2-1.6c.06-.4.1-.8.1-1.2z"/></svg>
          Settings
        </div>
        <div class="sb-item" data-tab="about">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M12 11v6"/></svg>
          About
        </div>
      </aside>

      <!-- -------- CONTENT -------- -->
      <main class="content">

        <!-- ============ DASHBOARD ============ -->
        <section class="panel active" id="p-dashboard">
          <div class="p-head">
            <h2>Dashboard</h2><span class="sub">AI-Lab · live · every feature in ONE window</span>
            <div class="right"><button class="btn blue">&#8635; Refresh</button></div>
          </div>

          <div class="stats">
            <div class="stat"><div class="d">today</div><div class="v">38</div><div class="l">Jobs Today</div></div>
            <div class="stat g"><div class="d">7 days</div><div class="v">94.7%</div><div class="l">Success Rate</div></div>
            <div class="stat w"><div class="d">live</div><div class="v">4</div><div class="l">In Queue</div></div>
            <div class="stat r"><div class="d">1 offline</div><div class="v">3/4</div><div class="l">Printers Ready</div></div>
            <div class="stat"><div class="d">hub</div><div class="v">v3.2.1</div><div class="l">Version</div></div>
          </div>

          <!-- v3.2.3: the Quick-actions card is GONE - all six of its
               buttons were sidebar duplicates (Open DropZone, Open Queue,
               History, Send portal QR, Connections, Hub settings). -->

          <div class="dash-row">
            <div class="card">
              <div class="card-h">&#9889; Print Hub Status <span class="r">uptime 04:12:37</span></div>
              <div class="kv">
                <span class="k">Service</span><span class="v">Running <span class="chip ok"><span class="d"></span>HEALTHY</span></span>
                <span class="k">Listen</span><span class="v mono">0.0.0.0:9235</span>
                <span class="k">LAN sharing</span><span class="v"><span class="chip ok">ON</span> <span class="mono" style="font-size:11px">http://10.26.94.206:9235</span></span>
                <span class="k">IPP printer</span><span class="v"><span class="chip ok">READY</span> <span class="mono" style="font-size:11px">/ipp/print</span></span>
                <span class="k">RAW port</span><span class="v"><span class="chip ok">LISTENING</span> <span class="mono" style="font-size:11px">10.26.94.206:9100</span></span>
                <span class="k">DropZone</span><span class="v"><span class="chip ok">ON</span> watching 1 folder</span>
                <span class="k">Connections</span><span class="v"><span class="chip info">2 PCs</span> <span class="chip info">2 peers</span> see Connections tab</span>
                <span class="k">Token</span><span class="v mono">mPz5&#8230;nXs <span class="chip info">auth on</span></span>
              </div>
            </div>
            <div class="card">
              <div class="card-h">&#128424; Default Printer</div>
              <div class="kv">
                <span class="k">Name</span><span class="v">HP Laser 103 107 108</span>
                <span class="k">Status</span><span class="v"><span class="chip err"><span class="d"></span>OFFLINE</span></span>
                <span class="k">Hold</span><span class="v">jobs wait while printer is offline <span class="chip info">status hold ON</span></span>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-h">&#128203; Recent Jobs <span class="r">last 6 of 38 today</span></div>
            <table class="tbl">
              <tr><th>ID</th><th>Document</th><th>Printer</th><th>Pages</th><th>Status</th><th style="width:150px">Progress</th><th>Time</th></tr>
              <tr><td class="id">#2047</td><td class="doc">lab-report-nov.pdf</td><td>HP Laser 103 107 108</td><td>12</td><td><span class="chip info"><span class="d"></span>PRINTING</span></td><td><div class="prog"><i style="width:64%"></i></div></td><td>14:22:08</td></tr>
              <tr><td class="id">#2046</td><td class="doc">invoice-2026-11.pdf</td><td>Microsoft Print to PDF</td><td>2</td><td><span class="chip ok"><span class="d"></span>DONE</span></td><td><div class="prog done"><i style="width:100%"></i></div></td><td>14:19:41</td></tr>
              <tr><td class="id">#2045</td><td class="doc">scanned-pp.oxps</td><td>AdvPrint Pro @ AI-Lab</td><td>4</td><td><span class="chip warn"><span class="d"></span>QUEUED</span></td><td><div class="prog"><i style="width:0%"></i></div></td><td>14:19:02</td></tr>
              <tr><td class="id">#2044</td><td class="doc">presentation.pptx</td><td>OneNote (Desktop)</td><td>18</td><td><span class="chip ok"><span class="d"></span>DONE</span></td><td><div class="prog done"><i style="width:100%"></i></div></td><td>14:11:55</td></tr>
              <tr><td class="id">#2043</td><td class="doc">manual-de.pdf</td><td>HP Laser 103 107 108</td><td>64</td><td><span class="chip err"><span class="d"></span>FAILED</span></td><td><div class="prog fail"><i style="width:31%"></i></div></td><td>13:58:12</td></tr>
              <tr><td class="id">#2042</td><td class="doc">receipt.html</td><td>HP Laser 103 107 108</td><td>1</td><td><span class="chip ok"><span class="d"></span>DONE</span></td><td><div class="prog done"><i style="width:100%"></i></div></td><td>13:55:30</td></tr>
            </table>
          </div>
        </section>

        <!-- ============ QUEUE (separate tab) ============ -->
        <section class="panel" id="p-queue">
          <div class="p-head">
            <h2>Live Queue</h2><span class="sub">what the Printing Hub is printing right now · auto-refresh 3 s · held jobs wait here</span>
            <div class="right"><button class="btn">&#8635; Refresh now</button><button class="btn">&#9724; Pause queue</button><button class="btn danger">&#128465; Clear queue</button></div>
          </div>
          <div class="kpi">
            <div class="kc w"><b>1</b><small>Printing</small><span class="chip warn">QUEUE ON</span></div>
            <div class="kc"><b>1</b><small>Queued</small></div>
            <div class="kc r"><b>2</b><small>Held · printer offline</small></div>
            <div class="kc g"><b>9</b><small>Done today</small></div>
          </div>
          <div class="filters">
            <span class="fchip on">All <span class="n">13</span></span>
            <span class="fchip">Printing <span class="n">1</span></span>
            <span class="fchip">Queued <span class="n">1</span></span>
            <span class="fchip">Held <span class="n">2</span></span>
            <span class="fchip">Completed <span class="n">9</span></span>
            <span class="fchip">Saved <span class="n">7</span></span>
            <span class="fchip">Failed <span class="n">1</span></span>
          </div>
          <div class="card">
            <div class="card-h"><span class="chip ok"><span class="d"></span>RUNNING</span> Queue mode <b>ON</b> — jobs print in order (Pause holds them back) <span class="r">hub #2047 in progress</span></div>
            <div class="frow" style="margin-bottom:4px">
              <button class="btn small danger" id="queueCancelSel" disabled>&#10006; Cancel selected</button>
              <button class="btn small">&#9932; Clear selected</button>
              <span class="id" id="queueSelInfo" style="color:#64748b">nothing ticked</span>
              <span style="flex:1"></span>
              <span style="font-size:12px;color:#64748b">ticked rows stay ticked across the 3 s refresh</span>
            </div>
            <table class="tbl">
              <tr><th style="width:30px"><input type="checkbox" data-qall></th><th>ID</th><th>Document</th><th>Printer</th><th>Kind</th><th>Status</th><th style="width:150px">Progress</th><th></th></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2047</td><td class="doc">lab-report-nov.pdf</td><td>HP Laser 103 107 108</td><td><span class="chip info">PDF</span></td><td><span class="chip info"><span class="d"></span>PRINTING</span></td><td><div class="prog"><i style="width:64%"></i></div></td><td><button class="btn small danger">Cancel</button></td></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2045</td><td class="doc">scanned-pp.oxps</td><td>AdvPrint Pro @ AI-Lab</td><td><span class="chip gray">XPS</span></td><td><span class="chip gray"><span class="d"></span>QUEUED</span></td><td><div class="prog"><i style="width:0%"></i></div></td><td><button class="btn small danger">Cancel</button></td></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2042</td><td class="doc">discharge-summary.pdf</td><td>HP Laser 103 107 108</td><td><span class="chip info">PDF</span></td><td><span class="chip warn"><span class="d"></span>HELD · OFFLINE</span></td><td><div class="prog"><i style="width:0%"></i></div></td><td><button class="btn small">&#9889; Release</button></td></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2041</td><td class="doc">label-4711.zpl</td><td>AdvPrint Pro @ AI-Lab</td><td><span class="chip purple">ZPL</span></td><td><span class="chip warn"><span class="d"></span>HELD · OFFLINE</span></td><td><div class="prog"><i style="width:0%"></i></div></td><td><button class="btn small">&#9889; Release</button></td></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2046</td><td class="doc">invoice-2026-11.pdf</td><td>Microsoft Print to PDF</td><td><span class="chip info">PDF</span></td><td><span class="chip ok"><span class="d"></span>DONE</span></td><td><div class="prog done"><i style="width:100%"></i></div></td><td><button class="btn small">&#8635; Reprint</button></td></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2044</td><td class="doc">presentation.pptx</td><td>OneNote (Desktop)</td><td><span class="chip gray">DOC</span></td><td><span class="chip ok"><span class="d"></span>DONE</span></td><td><div class="prog done"><i style="width:100%"></i></div></td><td><button class="btn small">&#8635; Reprint</button></td></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2043</td><td class="doc">manual-de.pdf</td><td>HP Laser 103 107 108</td><td><span class="chip info">PDF</span></td><td><span class="chip err"><span class="d"></span>FAILED</span></td><td><div class="prog fail"><i style="width:31%"></i></div></td><td><button class="btn small">&#8635; Retry</button></td></tr>
            </table>
          </div>
          <div class="note">Queue mode is switched in <b>Power Switches</b> — flip it and it saves instantly:
            <b>ON</b> = jobs print in order (Pause holds them back); <b>OFF</b> = instant print — every job goes straight to the printer.
            If no printer is active the job is auto-queued instead of failing. Release ALL held jobs: <b>Queue</b> tab.</div>
        </section>

        <!-- ============ HISTORY (separate tab) ============ -->
        <section class="panel" id="p-history">
          <div class="p-head">
            <h2>Job History</h2><span class="sub">hub SQLite · bulk reprint manager · waiting jobs are never touched</span>
            <div class="right"><button class="btn blue">&#8635; Reprint selected</button><button class="btn">&#8635; Reprint non-printed</button><button class="btn danger">Clear ALL history</button></div>
          </div>
          <div class="card">
            <div class="card-h">&#128218; Saved history <span class="r">last 12 of 1 284 · reprint needs the original file on disk (Hub &#8594; Keep printed files)</span></div>
            <div class="card-b" style="padding-bottom:4px">
              <div class="frow" style="margin-bottom:4px">
                <select class="inp" style="min-width:150px"><option>All statuses</option><option>Printed</option><option>Queued</option><option>Saved (file)</option><option>Failed</option><option>Canceled</option></select>
                <input class="inp" type="text" placeholder="Search title / printer / #id" style="min-width:210px">
                <select class="inp" style="min-width:130px"><option>load last 100</option><option>last 50</option><option>last 300</option></select>
                <span style="flex:1"></span>
                <span class="id" id="histSelInfo" style="color:#64748b">nothing ticked</span>
                <button class="btn small danger" id="histCancelSel" disabled>&#10006; Cancel selected</button>
                <button class="btn small">&#9932; Clear selected</button>
                <button class="btn blue small">&#8635; Reprint selected</button>
                <button class="btn small">Export CSV</button>
              </div>
            </div>
            <table class="tbl">
              <tr><th style="width:30px"><input type="checkbox" data-hall></th><th>#</th><th>Time</th><th>Title</th><th>Printer</th><th>Kind</th><th>Status</th><th></th></tr>
              <tr><td><input type="checkbox" checked></td><td class="id">#2046</td><td class="id">14:19:41</td><td class="doc">invoice-2026-11.pdf</td><td>Microsoft Print to PDF</td><td><span class="chip info">PDF</span></td><td><span class="chip ok">PRINTED</span></td><td><button class="btn small">&#8635; Reprint</button></td></tr>
              <tr><td><input type="checkbox" checked></td><td class="id">#2044</td><td class="id">14:11:55</td><td class="doc">presentation.pptx</td><td>OneNote (Desktop)</td><td><span class="chip gray">DOC</span></td><td><span class="chip ok">PRINTED</span></td><td><button class="btn small">&#8635; Reprint</button></td></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2043</td><td class="id">13:58:12</td><td class="doc">manual-de.pdf</td><td>HP Laser 103 107 108</td><td><span class="chip info">PDF</span></td><td><span class="chip err">FAILED</span></td><td><button class="btn small">&#8635; Reprint</button></td></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2040</td><td class="id">13:40:27</td><td class="doc">receipt-881.pdf</td><td>Microsoft Print to PDF</td><td><span class="chip info">PDF</span></td><td><span class="chip warn">SAVED (file)</span></td><td><button class="btn small">Open file</button></td></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2039</td><td class="id">13:38:10</td><td class="doc">scan-batch.pdf</td><td>—</td><td><span class="chip info">PDF</span></td><td><span class="chip warn">SCHEDULED 15:00</span></td><td><button class="btn small">Edit</button></td></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2038</td><td class="id">13:12:44</td><td class="doc">lab-request-form.pdf</td><td>HP Laser 103 107 108</td><td><span class="chip info">PDF</span></td><td><span class="chip purple">DROPZONE</span></td><td><button class="btn small">&#8635; Reprint</button></td></tr>
              <tr><td><input type="checkbox"></td><td class="id">#2037</td><td class="id">12:41:19</td><td class="doc">receipt-scan.pdf</td><td>Microsoft Print to PDF</td><td><span class="chip info">PDF</span></td><td><span class="chip ok">PRINTED</span></td><td><button class="btn small">&#8635; Reprint</button></td></tr>
            </table>
          </div>
          <div class="note"><b>Tick rows</b> and reprint in bulk — or clear the whole finished history.
            Waiting jobs (queued / held) are never touched by Clear. Reprinted copies can carry a visible REPRINT stamp (Hub tab &#8594; Reprint &amp; audit).</div>
        </section>

        <!-- ============ PRINTERS ============ -->
        <section class="panel" id="p-printers">
          <div class="p-head">
            <h2>Printers</h2><span class="sub">destination, default options, PDF engine — all printer settings in one tab</span>
            <div class="right"><button class="btn">&#128269; Re-scan</button></div>
          </div>

          <div class="card">
            <div class="card-h">&#128101; Other PCs &amp; devices from a different IP <span class="r">their printers appear below with a source badge</span></div>
            <div class="card-b">
              <div class="frow" style="margin-bottom:0">
                <span class="tgl"><span class="sw"><span class="switch" id="showRemoteSw"></span></span></span>
                <b>Show other PCs (LAN / IPP)</b>
                <span class="note" style="margin:0 0 0 8px">Lists the paired LAN PC's printers (Connections &rarr; Another PC) with a
                  <b>LAN PC &middot; IPP</b> badge, its ip:port and a ipp:// URL per device &mdash; test-page them right from here.</span>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-h">&#127919; Print destination <span class="r">where jobs go when no rule matches · per-job printer always wins</span></div>
            <div class="card-b">
              <div class="frow" style="margin-bottom:8px">
                <span class="radio on"><span class="rdot"></span>Default printer</span>
                <span class="radio"><span class="rdot"></span>Selected printer</span>
                <span class="radio"><span class="rdot"></span>IP printer (IPP)</span>
              </div>
              <div class="frow" style="margin-bottom:0">
                <label>Default printer</label>
                <select class="inp" style="min-width:300px">
                  <option>OS default — HP Laser 103 107 108</option>
                  <option>AdvPrint Pro @ AI-Lab</option>
                  <option>Microsoft Print to PDF</option>
                  <option>OneNote (Desktop)</option>
                </select>
                <button class="btn small">&#8632; Reload list</button>
                <span class="chip err"><span class="d"></span>HP Laser offline — 2 jobs held</span>
              </div>
            </div>
          </div>

          <div class="pgrid">
            <div class="pcard">
              <span class="badge">DEFAULT</span>
              <div class="top">
                <div class="picon"><svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M6 9V3h12v6M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8" rx="1"/></svg></div>
                <div><div class="nm">HP Laser 103 107 108</div><div class="mdl">HP Laser MFP · USB · driver: hp-laser</div></div>
              </div>
              <div class="st"><span>State <b>Offline</b></span><span>Jobs <b>31</b></span><span><span class="chip err"><span class="d"></span>OFFLINE</span></span></div>
              <div class="url mono">10.26.94.206:9235/ipp/print/HP-Laser<button class="cp">COPY</button></div>
              <div class="ops"><button class="btn blue">Test Page</button><button class="btn">Set Default</button><button class="btn">Wake / Check</button></div>
            </div>
            <div class="pcard">
              <div class="top">
                <div class="picon"><svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M6 9V3h12v6M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8" rx="1"/></svg></div>
                <div><div class="nm">AdvPrint Pro @ AI-Lab</div><div class="mdl">Virtual PDF printer · port: ADVPRINT</div></div>
              </div>
              <div class="st"><span>State <b>Ready</b></span><span>Jobs <b>142</b></span><span><span class="chip ok"><span class="d"></span>ONLINE</span></span></div>
              <div class="url mono">10.26.94.206:9235/ipp/print/AI-Lab<button class="cp">COPY</button></div>
              <div class="ops"><button class="btn blue">Test Page</button><button class="btn">Set Default</button><button class="btn">Details</button></div>
            </div>
            <div class="pcard">
              <div class="top">
                <div class="picon"><svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M6 9V3h12v6M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8" rx="1"/></svg></div>
                <div><div class="nm">Microsoft Print to PDF</div><div class="mdl">Virtual · saves PDF to hub output</div></div>
              </div>
              <div class="st"><span>State <b>Ready</b></span><span>Jobs <b>9</b></span><span><span class="chip ok"><span class="d"></span>ONLINE</span></span></div>
              <div class="url mono">10.26.94.206:9235/ipp/print/Print-to-PDF<button class="cp">COPY</button></div>
              <div class="ops"><button class="btn blue">Test Page</button><button class="btn">Set Default</button><button class="btn">Details</button></div>
            </div>
            <div class="pcard off">
              <div class="top">
                <div class="picon"><svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M6 9V3h12v6M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8" rx="1"/></svg></div>
                <div><div class="nm">OneNote (Desktop)</div><div class="mdl">Virtual · sends to OneNote</div></div>
              </div>
              <div class="st"><span>State <b>Idle</b></span><span>Jobs <b>4</b></span><span><span class="chip warn"><span class="d"></span>BUSY</span></span></div>
              <div class="url mono">10.26.94.206:9235/ipp/print/OneNote<button class="cp">COPY</button></div>
              <div class="ops"><button class="btn blue">Test Page</button><button class="btn">Set Default</button><button class="btn">Details</button></div>
            </div>
          </div>

          <div class="card">
            <div class="card-h">&#128196; PDF engine — SumatraPDF override <span class="r">fallback renderer when a driver fails</span></div>
            <div class="card-b">
              <div class="frow" style="margin-bottom:0">
                <label>SumatraPDF.exe</label>
                <input class="inp mono" style="flex:1;min-width:280px;font-size:11px" value="C:\Program Files\SumatraPDF\SumatraPDF.exe">
                <span class="chip ok">DETECTED</span>
                <button class="btn small">Browse&#8230;</button>
                <button class="btn small">Reset</button>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-h">&#9881; Default print options <span class="r">sent with EVERY job · the extension defaults, rules &amp; page scripts can override</span></div>
            <div class="card-b">
              <div class="frow"><label>Copies</label><input class="inp narrow" value="1">
                <label style="min-width:auto">Pages</label><select class="inp" style="min-width:150px"><option>All pages</option><option>Odd pages only</option><option>Even pages only</option><option>Custom range&#8230;</option></select>
                <input class="inp narrow" placeholder="1-3,5"></div>
              <div class="frow"><label>Quality</label><select class="inp" style="min-width:170px"><option>Printer default</option><option>Draft</option><option>Normal</option><option>High / Best</option><option>300 dpi</option><option>600 dpi</option></select>
                <label style="min-width:auto">Per sheet (n-up)</label><select class="inp" style="min-width:120px"><option>1 per sheet</option><option>2</option><option>4</option><option>6</option></select></div>
              <div class="frow"><label>Duplex (two sides)</label><select class="inp" style="min-width:170px"><option>Printer default</option><option>One side (simplex)</option><option>Two sides, long edge</option><option>Two sides, short edge</option></select>
                <label style="min-width:auto">Layout</label><select class="inp" style="min-width:130px"><option>Auto (portrait)</option><option>Portrait</option><option>Landscape</option></select></div>
              <div class="frow" style="margin-bottom:0"><label>Scale %</label><input class="inp narrow" placeholder="100">
                <label style="min-width:auto">Paper</label><select class="inp" style="min-width:130px"><option>Printer default</option><option>A4</option><option>A5</option><option>A3</option><option>Letter</option><option>Legal</option></select></div>
            </div>
          </div>
        </section>

        <!-- ============ LAN SHARING ============ -->
        <section class="panel" id="p-lan">
          <div class="p-head">
            <h2>LAN Sharing &amp; Other PCs</h2><span class="sub">v3.2.6 · share printing over the network · the UI stays on this PC — LAN PCs print via Send / IPP</span>
            <div class="right"><button class="btn" id="lanTopToggle">Disable</button><button class="btn" id="ippTopToggle">IPP: ON</button><button class="btn blue">Copy URL</button></div>
          </div>

          <div class="card">
            <div class="card-h">&#127760; Sharing status <span class="r">every row is one old dashboard card — same words, one place</span></div>
            <div class="lrow"><span class="lk">LAN sharing <small>share this hub with LAN PCs</small></span><span class="chip ok">ON</span><span class="lv">http://10.26.94.206:9235</span><span class="sp"></span><span class="ops"><button class="btn small">Disable</button><button class="btn small blue">Copy URL</button></span></div>
            <div class="lrow"><span class="lk">Send portal (phones) <small>print from any phone browser</small></span><span class="chip ok">QR READY</span><span class="lv">http://10.26.94.206:9235/send?token=mPz5&#8230;nXs</span><span class="sp"></span><span class="ops"><button class="btn small blue">Copy send URL</button><button class="btn small" data-qr="send">QR code</button></span></div>
            <div class="lrow"><span class="lk">Connect another PC <small>1-click invite, connects itself</small></span><span class="chip ok">1-CLICK</span><span class="lv">http://10.26.94.206:9235/connect?t=mPz5&#8230;nXs&amp;n=AI-Lab</span><span class="sp"></span><span class="ops"><button class="btn small blue">Copy invite link</button><button class="btn small" data-qr="invite">QR</button></span></div>
            <div class="lrow"><span class="lk">IP Printer mode <small>this PC becomes a network printer</small></span><span class="chip info">ACTIVE</span><span class="lv plain">every PC or phone adds this PC as their network printer &#8594; jobs print to (default printer)</span><span class="sp"></span><span class="ops"><button class="btn small" data-qr="ipp">QR</button></span></div>
            <div class="lrow"><span class="lk">Network printer (IPP) <small>built-in IPP Class Driver, no tools</small></span><span class="chip ok">READY</span><span class="lv">http://10.26.94.206:9235/ipp/print</span><span class="sp"></span><span class="ops"><button class="btn small ipp-tgl">Disable</button><button class="btn small blue">Copy printer URL</button><button class="btn small" data-qr="ipp">QR</button></span></div>
            <div class="lrow" id="row-mdns"><span class="lk">AirPrint / mDNS discovery <small>the printer appears BY ITSELF in phone &amp; PC lists</small></span><span class="chip gray">STARTING</span><span class="lv plain">Bonjour/_ipp._tcp broadcast on the LAN</span><span class="sp"></span><span class="ops"></span></div>
            <div class="lrow" id="row-ipp631"><span class="lk">Standard IPP port 631 <small>mirror of /ipp/print — Android &amp; printer defaults</small></span><span class="chip gray">STARTING</span><span class="lv plain">http://IP:631/ipp/print answers like a real printer</span><span class="sp"></span><span class="ops"></span></div>
            <div class="lrow" id="row-hubips"><span class="lk">Hub addresses <small>v3.3.0 — EVERY interface IP, IPv4 + IPv6; pick the one YOUR PC reaches</small></span><span class="chip info">ALL IPs</span><span class="lv plain" id="hubIpList"></span><span class="sp"></span><span class="ops"></span></div>
            <div class="lrow"><span class="lk">RAW printer port <small>JetDirect, port 9100</small></span><span class="chip ok">LISTENING</span><span class="lv">10.26.94.206:9100</span><span class="sp"></span><span class="ops"><button class="btn small">How to add</button></span></div>
            <div class="lrow"><span class="lk">Windows firewall <small>inbound rule for LAN PCs</small></span><span class="chip ok">ALLOWED</span><span class="lv plain">inbound TCP 9235 allowed for LAN PCs</span><span class="sp"></span><span class="ops"><button class="btn small">Test LAN</button></span></div>
            <div class="lrow"><span class="lk">Printer status hold <small>pause jobs while a printer is offline</small></span><span class="chip ok">ON</span><span class="lv plain">jobs wait while the printer reports offline</span><span class="sp"></span><span class="ops"><button class="btn small">Disable</button></span></div>
            <div class="note" id="lanSecurityNote" style="margin-top:10px"><b>&#128274; v3.2.6 security:</b> the console UI and every setting answer <b>only on this PC</b> (loopback or this machine's own IP). Other PCs and phones keep full print access &#8212; Send portal, IPP printer URL, print API, ports 9235/631/9100 &#8212; exactly per the Allowed-IPs list below; they simply cannot open the UI or change anything. Opening the share URL from another PC shows a friendly locked page with the print instructions. Switching LAN sharing ON also turns the IPP printer ON automatically.</div>
          </div>

          <div class="card">
            <div class="card-h">&#128274; Allowed IPs &#8212; who may reach this hub <span class="r">v3.2.3 · * = every device on this LAN · once you add IPs, ONLY those may connect</span></div>
            <div class="card-b">
              <div class="frow" style="margin-bottom:6px">
                <span class="chip ok" id="aclMode">ALL LAN (*)</span>
                <input class="inp mono" id="aclInput" placeholder="add an IP: 10.26.94.100 &#8212; or a subnet: 10.26.94.0/24 &#8212; or 10.26.*" style="flex:1;min-width:260px;font-size:11.5px">
                <button class="btn small blue" id="aclAdd">Add IP</button>
                <button class="btn small" id="aclAllowAll">Allow ALL (*)</button>
              </div>
              <div id="aclList" style="display:flex;gap:8px;flex-wrap:wrap;min-height:6px"></div>
              <div class="note">The hub PC itself (<span class="mono">127.0.0.1</span>) can ALWAYS reach the hub. Any device NOT on the list gets <b>403 access denied</b> &#8212; the console, the send portal, the API, IPP printing (9235 + 631) and the RAW 9100 port included. Every denial lands in the Audit trail (<span class="mono">acl.denied</span>).</div>
            </div>
          </div>

          <div class="card">
            <div class="card-h">&#128241; Scan &amp; connect <span class="r">live hub QRs — click any code to enlarge · printed also on hub start</span></div>
            <div class="card-b">
              <div class="qr-grid">
                <div class="qr-tile" data-qr="send"><span class="zoom">&#10538; enlarge</span><div class="qbox" data-qr-draw="send"></div><b>Send portal — phones</b><small>scan &#8594; open the send page in any phone browser &#8594; print here. No app needed.</small></div>
                <div class="qr-tile" data-qr="invite"><span class="zoom">&#10538; enlarge</span><div class="qbox" data-qr-draw="invite"></div><b>Invite — another PC</b><small>scan/open on the other PC &#8594; it configures itself and connects to this hub.</small></div>
                <div class="qr-tile" data-qr="ipp"><span class="zoom">&#10538; enlarge</span><div class="qbox" data-qr-draw="ipp"></div><b>IPP printer URL</b><small>add once as a network printer (Windows IPP Class Driver, Android print service).</small></div>
              </div>
              <div class="note">QRs are generated by the hub from the <b>real URLs + current token</b> — regenerating after <b>Rotate token</b> invalidates old codes automatically. Enlarged view shows the raw link + a Copy button for devices without a camera.</div>
            </div>
          </div>

          <div class="card">
            <div class="card-h">&#128421; Add this PC as a printer — EVERY device, both URL styles <span class="r">v3.2.3 · ipp:// and http:// both work</span></div>
            <div class="card-b" style="font-size:11.5px;color:var(--ink-2);line-height:1.7">
              <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
                <span class="mono" id="ippUrlIpp" style="background:#f1f5f9;border:1px solid #e2e8f0;border-radius:4px;padding:2px 8px;color:var(--blue-deep)">ipp://10.26.94.206:9235/ipp/print</span>
                <button class="btn small blue" data-act="copy-ipp-url">Copy ipp:// URL</button>
                <span class="mono" id="ippUrlHttp" style="background:#f1f5f9;border:1px solid #e2e8f0;border-radius:4px;padding:2px 8px;color:var(--blue-deep)">http://10.26.94.206:9235/ipp/print</span>
                <button class="btn small blue" data-act="copy-ipp-http">Copy http:// URL</button>
                <button class="btn small" data-qr="ipp">QR code</button>
              </div>
              <table class="tbl" style="width:100%">
                <tr><th style="width:110px">Device</th><th>How to add this printer</th></tr>
                <tr><td><b>Windows 10 / 11</b></td><td>
                  Settings &#8594; Bluetooth &amp; devices &#8594; Printers &amp; scanners &#8594; <b>Add device</b> — the printer appears by itself (mDNS discovery), click it.
                  Or: <b>Add manually</b> &#8594; &ldquo;Add a printer using an IP address or hostname&rdquo; &#8594; Device type <b>IPP Device</b> &#8594; paste <span class="mono" id="ippGuideWin">http://10.26.94.206:9235/ipp/print</span> &#8594; Next — Windows installs it with the built-in <b>IPP Class Driver</b>.</td></tr>
                <tr><td><b>macOS</b></td><td>
                  System Settings &#8594; Printers &amp; Scanners &#8594; it appears in the <b>Bonjour list</b> — click it.
                  Or: IP tab &#8594; Protocol <b>IPP</b> &#8594; Address <span class="mono" id="ippGuideMacHost">10.26.94.206:9235</span> &#8594; Queue <span class="mono">ipp/print</span>.</td></tr>
                <tr><td><b>iPhone / iPad</b></td><td>
                  Open anything printable &#8594; Share &#8594; <b>Print</b> &#8594; Select Printer — <b>AdvPrint Pro appears by itself</b> (AirPrint) while the phone is on the same Wi-Fi.</td></tr>
                <tr><td><b>Android</b></td><td>
                  Print from any app &#8594; <b>Default Print Service / Mopria</b> — the printer is discovered automatically (mDNS).
                  Manual add: Default Print Service &#8594; &#8942; &#8594; Add printer &#8594; <b>IP address</b> &#8594; <span class="mono" id="ippGuideAndroid">10.26.94.206</span> — Android tries the standard port <b>631</b> first, where this hub mirrors <span class="mono" id="ippGuideAndroid631">http://10.26.94.206:631/ipp/print</span> (v3.2.2 fix — Android ignores custom ports on manual add).</td></tr>
              </table>
              <div class="note" style="margin:10px 0 0">RAW / JetDirect lovers: add a <b>Standard TCP/IP port</b> — IP <span class="mono" id="ippGuideRawIp">10.26.94.206</span>, port <span class="mono">9100</span>, device type <b>Generic Network Card</b>. Prints go to THIS PC's printer through the AdvPrint Pro hub — 100% local, no cloud.</div>
            </div>
          </div>

          <div class="card">
            <div class="card-h">&#128279; Peer PCs <span class="r">fixed hub-to-hub peers</span></div>
            <div class="card-b" style="font-size:11.5px;color:var(--ink-2);line-height:1.7">
              <b>Easiest:</b> press <b>Copy invite link</b> above and open it on the other PC — it connects itself.
              <b>Advanced:</b> add fixed peer PCs (<span class="mono">"peer_hubs"</span>) in <span class="mono">config.json</span> — see Docs.
              <div class="note" style="margin-top:10px;margin-bottom:0">No fixed peers yet — every connection so far came from invite links. Fixed peers survive hub restarts without re-inviting.</div>
            </div>
          </div>
        </section>

        <!-- ============ CONNECTIONS (from Options design v3.1.2) ============ -->
        <section class="panel" id="p-connections">
          <div class="p-head">
            <h2>Connections</h2><span class="sub">this PC · other PCs · website API permissions — the old options tab, now in the ONE UI</span>
            <div class="right"><button class="btn blue">&#128190; Save settings</button></div>
          </div>
          <div class="card">
            <div class="card-h">&#128421; This PC (Self PC) — the main Printing Hub <span class="r"><span class="chip ok"><span class="d"></span>CONNECTED · 12 ms</span></span></div>
            <div class="card-b">
              <div class="frow"><label>Hub URL</label><input class="inp mono" value="http://127.0.0.1:9235"></div>
              <div class="frow" style="margin-bottom:4px"><label>Token</label><input class="inp mono" type="password" value="mPz5HFOsB9xaJ36isQ7kDfjaaNrERnXs" style="min-width:260px">
                <button class="btn blue">Connect</button><button class="btn">Detect token</button></div>
              <div class="note" style="margin-bottom:0">New installs get a <b>private random token</b> — read it with
                <span class="mono">python advprint.py token</span> or in this console. <b>Detect token</b> fills the current token
                automatically from the running hub (one-click fix). Same profile is used by every tab in this console.</div>
            </div>
          </div>
          <div class="card">
            <div class="card-h">&#128444; Another PC (LAN PC) — print over the network
              <span class="r"><span class="chip gray" id="lanPcChip"><span class="d"></span>OFFLINE</span></span></div>
            <div class="card-b">
              <div class="frow"><label>LAN PC hub URL</label><input class="inp mono" id="lanPcHubUrl"
                placeholder="http://192.168.1.101:9235" style="min-width:230px"></div>
              <div class="frow" style="margin-bottom:4px"><label>LAN PC token</label><input class="inp mono" id="lanPcToken" type="password"
                placeholder="the other PC's hub token" style="min-width:170px">
                <button class="btn blue" id="lanPcConnect">Connect</button><button class="btn danger" id="lanPcClear">Clear</button></div>
              <div class="note" id="lanPcStatus" style="margin-bottom:6px">Enter the <b>OTHER PC's</b> hub URL and token, then Connect.
                The pairing is saved on this PC — it survives page reloads and hub restarts.</div>
              <div class="frow" style="margin-bottom:0;border-top:1px solid var(--line);padding-top:8px">
                <span class="tgl"><span class="sw"><span class="switch" id="shareSendSw"></span></span></span>
                <b>Share Send Mode</b>
                <span class="note" style="margin:0 0 0 8px">ON sends <b>every print job</b> to that PC &middot; OFF (default) prints on the Self PC above.
                  Receiving is the OTHER PC's side (its LAN sharing stays ON).</span>
              </div>
            </div>
          </div>
          <div class="card">
            <div class="card-h">&#127760; LAN sharing — let other PCs &amp; phones print through this one
              <span class="r" style="display:flex;gap:8px"><span class="chip ok"><span class="d"></span>ON</span>
              <button class="btn small">Disable</button><button class="btn small">Copy URL</button></span></div>
            <div class="card-b">
              <div class="frow" style="margin-bottom:6px"><span class="mono" style="font-size:12px;color:var(--blue-deep);font-weight:700">http://10.26.94.206:9235 · 4 per-printer IPP queues announced (mDNS)</span></div>
              <div class="note" style="margin-bottom:0">After enabling: <b>restart the hub</b> (tray &#8594; Exit, start AdvPrint Pro again) and allow the port once:<br>
                <span class="mono" style="font-size:10.5px">netsh advfirewall firewall add rule name="AdvPrint Pro" dir=in action=allow protocol=TCP localport=9235</span></div>
              <div class="h3sec">Other PCs (peers)</div>
              <table class="tbl" style="font-size:11.5px">
                <tr><th>PC (hub URL)</th><th>Status</th><th>Version</th><th style="width:160px"></th></tr>
                <!-- v3.3.3: the two DEMO rows (Storage-Room-PC / SHOP-PC
                     with fake 10.26.94.x addresses) are gone - they
                     flashed fake peers on every page load until the
                     first /peers answer replaced them. loadConnections()
                     renders the real rows (or "no peer hubs configured"). -->
                <tr><td class="mono doc" style="font-size:10.5px;color:var(--muted)">loading&hellip;</td><td></td><td></td><td></td></tr>
              </table>
              <div class="frow" style="margin:10px 0 0"><label style="min-width:auto">Shift whole queue to</label>
                <input class="inp mono" id="shiftTarget" style="min-width:200px;font-size:11px" value="">
                <button class="btn blue">Shift all waiting</button></div>
            </div>
          </div>
          <div class="card">
            <div class="card-h">&#128274; Website API permission — which sites may print <span class="r"><span class="chip info">2 patterns</span></span></div>
            <div class="card-b">
              <textarea class="inp mono" rows="3" style="width:100%;min-width:0;font-size:11.5px;padding:8px">*://www.htncr.org/*
https://reports.example.com/*</textarea>
              <div class="frow" style="margin:8px 0 0"><button class="btn blue small">Save site list</button>
                <span style="font-size:11px;color:var(--muted)">Empty list = the page API is OFF for every website. The extension's own pages are always allowed. v3.2.8: the SCHEME does not matter &mdash; <span class="mono">https://host/*</span> also allows the SAME host over <span class="mono">http://</span> (and the other way round), so a site that serves both always works; <span class="mono">*://host/*</span> or a bare <span class="mono">host</span> stay scheme-free as before.</span></div>
            </div>
          </div>
        </section>

        <!-- ============ HUB (from Options design v3.1.2) ============ -->
        <section class="panel" id="p-hub">
          <div class="p-head">
            <h2>Hub</h2><span class="sub">the Printing Hub engine's own settings — same as config.json · apply live</span>
            <div class="right"><button class="btn blue">Apply hub settings</button><button class="btn">&#8635; Reload from hub</button></div>
          </div>
          <div class="card">
            <div class="card-b">
              <div class="h3sec" style="margin-top:0">Queue &amp; retries</div>
              <div class="frow"><label style="min-width:190px">Retry attempts (0 = off)</label><input class="inp narrow" value="2">
                <label style="min-width:auto">First retry after (seconds)</label><input class="inp narrow" value="30"></div>
              <div class="frow"><label style="min-width:190px">Duplicate block window (minutes)</label><input class="inp narrow" value="5"></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Hold jobs while the printer reports offline</b><p>Jobs wait (status "held") until the printer is ready again — nothing is lost.</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Instant print fallback to queue</b><p>Queue mode OFF + printer not active: the job is auto-queued instead of failing.</p></div></div>

              <div class="h3sec">Security</div>
              <div class="frow"><label style="min-width:190px">Failed tokens before lockout</label><input class="inp narrow" value="10">
                <label style="min-width:auto">Lockout minutes</label><input class="inp narrow" value="5"></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Strict token mode (header only)</b><p>ON = mutating calls (POST) must send the token in the X-PrintHub-Token header (the extension does this anyway).</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch on" style="opacity:.55;pointer-events:none"></span></span>
                <div><b>Never lock out this PC (127.0.0.1)</b><p>ALWAYS ON since v2.6.4 — built into the hub, cannot be switched off.</p></div></div>
              <div class="frow" style="margin-top:8px"><label>Allowed origins</label><input class="inp" placeholder="(empty = all websites may print) e.g. https://www.htncr.org"></div>

              <div class="h3sec">Reprint &amp; audit</div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Stamp REPRINT on reprinted pages</b><p>Reprinted copies carry a visible REPRINT mark — nobody mistakes them for originals.</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch"></span></span>
                <div><b>Require a reason for reprints</b><p>Every reprint asks for a reason that is written to the audit log (compliance).</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Audit trail</b><p>Log every print / who / what to the audit log (view: Audit tab).</p></div></div>

              <div class="h3sec">Thermal / raw text printing</div>
              <div class="frow"><label style="min-width:190px">Non-Latin text engine</label><select class="inp" style="min-width:200px"><option>Auto (recommended)</option><option>Built-in only (fast, Latin scripts)</option><option>Browser render (Bangla &amp; complex scripts)</option></select>
                <label style="min-width:auto">ESC/POS codepage</label><select class="inp" style="min-width:120px"><option>cp437</option><option>cp850</option><option>cp866</option><option>cp1251</option><option>cp1252</option></select></div>

              <div class="h3sec">Save-as-PDF destination &amp; files</div>
              <div class="frow"><label style="min-width:190px">Folder (empty = Downloads/AdvPrint)</label><input class="inp mono" value="C:\Users\Admin\Documents\Reports" style="min-width:260px;font-size:11px"></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Keep printed files (needed for Reprint)</b><p>Every job's file stays on disk so it can be re-printed from the History tab.</p></div></div>

              <div class="h3sec">Windows print engine</div>
              <div class="frow" style="margin-bottom:0"><label style="min-width:190px">SumatraPDF.exe path</label><input class="inp mono" placeholder="(empty = auto-find)" style="min-width:260px;font-size:11px" value="C:\Program Files\SumatraPDF\SumatraPDF.exe">
                <span class="chip ok">DETECTED</span></div>
            </div>
          </div>
        </section>

        <!-- ============ DROPZONE ============ -->
        <section class="panel" id="p-dropzone">
          <div class="p-head">
            <h2>DropZone</h2><span class="sub">v2.8 · print WITHOUT the extension — save a PDF into the folder, AdvPrint prints it (works from any Windows app, MS Word style)</span>
            <div class="right"><button class="btn">Disable</button></div>
          </div>

          <div class="stats" style="grid-template-columns:repeat(4,1fr)">
            <div class="stat g"><div class="d">done\</div><div class="v">0</div><div class="l">Printed (done folder)</div></div>
            <div class="stat"><div class="d">watching</div><div class="v">1</div><div class="l">Folder Watched</div></div>
            <div class="stat w"><div class="d">after print</div><div class="v">move</div><div class="l">Delete-After-Print OFF</div></div>
            <div class="stat"><div class="d">privacy</div><div class="v">100%</div><div class="l">Local — no cloud</div></div>
          </div>

          <div class="card">
            <div class="card-h">&#128449; Folder settings <span class="r">watched folder · done folder · delete-after-print</span></div>
            <div class="card-b">
              <div class="frow"><label style="min-width:210px">DropZone folder</label>
                <input class="inp mono" style="flex:1;min-width:280px;font-size:11px" value="C:\Users\Admin\.advprint\DropZone" readonly>
                <button class="btn small">&#128193; Open folder</button></div>
              <div class="frow"><label style="min-width:210px">Watched folder <span style="color:var(--muted);font-weight:500">(empty = data folder + DropZone)</span></label>
                <input class="inp mono" style="flex:1;min-width:280px;font-size:11px" value="C:\Users\you\Desktop\DropZone">
                <button class="btn small blue">Save</button></div>
              <div class="frow" style="margin-bottom:0"><label style="min-width:210px">After printing</label>
                <span class="tgl" style="padding:0;border:none;flex:1">
                  <span class="sw"><span class="switch on green"></span></span>
                  <span style="font-size:12px;color:var(--ink-2)"><b>delete the PDF after printing</b> — otherwise it is moved to <span class="mono">done\</span></span>
                </span></div>
            </div>
          </div>

          <div class="note">
            <b>Print from ANY app without the extension:</b> Print &#8594; choose <b>Microsoft Print to PDF</b> &#8594; save the PDF into the DropZone folder.
            AdvPrint Pro prints it seconds later (the file moves to <span class="mono">done\</span>).
            Phones/tablets print through the <b>Send portal</b> button above (or <span class="mono">/send</span>) — also 100% local.
          </div>

          <div class="card">
            <div class="card-h">&#128203; Recent DropZone prints <span class="r">files that came in through the folder</span></div>
            <table class="tbl">
              <tr><th>File</th><th>Printer</th><th>Result</th><th>Time</th></tr>
              <tr><td class="doc">lab-request-form.pdf</td><td>HP Laser 103 107 108</td><td><span class="chip ok">PRINTED</span></td><td class="id">13:12:44</td></tr>
              <tr><td class="doc"> discharge-summary.pdf</td><td>HP Laser 103 107 108</td><td><span class="chip warn">HELD — printer offline</span></td><td class="id">13:09:01</td></tr>
              <tr><td class="doc">receipt-scan.pdf</td><td>Microsoft Print to PDF</td><td><span class="chip ok">PRINTED</span></td><td class="id">12:41:19</td></tr>
            </table>
          </div>
        </section>

        <!-- ============ RULES ============ -->
        <section class="panel" id="p-rules">
          <div class="p-head">
            <h2>Auto-Print Rules</h2><span class="sub">the multi-printer control center · hidden silent printing, fully managed</span>
            <div class="right"><button class="btn blue" data-new-rule>&#43; New rule</button><button class="btn">Save rules</button></div>
          </div>

          <!-- HOW A RULE IS SET -->
          <div class="card">
            <div class="card-h">&#128218; How you set which rule for which <span class="r">3 steps, one dialog — press New rule or Edit on any row</span></div>
            <div class="card-b" style="font-size:11.5px;color:var(--ink-2);line-height:1.65">
              <b style="color:var(--blue-deep)">1. Match by</b> — <b>URL / address filter</b> (Chrome match pattern, e.g. <span class="mono">*://www.htncr.org/lab/*</span>),
              optional <b>page content</b> (text the page must contain, e.g. <span class="mono">ZPL</span> or <span class="mono">Patient Report</span>) and
              <b>URL type</b> (any / PDF link / web page / plain text). All conditions must pass.
              <b style="color:var(--blue-deep);margin-left:6px">2. Then print</b> — pick the <b>printer</b>, <b>what to print</b> (whole page, linked PDF, raw stream, selected element),
              <b>copies</b> and <b>paper</b>. <b style="color:var(--blue-deep);margin-left:6px">3. When</b> — <b>On</b> enables the rule,
              <b>Auto</b> prints silently without any dialog; optional schedule (e.g. evenings only). Rules run <b>top to bottom</b> —
              first match wins, drag rows to re-order. Every firing is logged in the activity log below.
            </div>
          </div>

          <!-- SUGGESTED URL / ADDRESS FILTERS -->
          <div class="card">
            <div class="card-h">&#128161; Suggested URL / address filters <span class="r">click a chip &#8594; opens the rule editor with the pattern filled in</span></div>
            <div class="card-b">
              <span class="pattern-chip" data-use-url="*://www.htncr.org/lab/*"><span class="use">USE</span>*://www.htncr.org/lab/*<small>lab section only</small></span>
              <span class="pattern-chip" data-use-url="*://*.htncr.org/*"><span class="use">USE</span>*://*.htncr.org/*<small>whole site, all subdomains</small></span>
              <span class="pattern-chip" data-use-url="*://*/*.pdf"><span class="use">USE</span>*://*/*.pdf<small>any PDF link anywhere</small></span>
              <span class="pattern-chip" data-use-url="*://billing.local/pos/*"><span class="use">USE</span>*://billing.local/pos/*<small>POS screens</small></span>
              <span class="pattern-chip" data-use-url="*://intranet/certificates/*"><span class="use">USE</span>*://intranet/certificates/*<small>certificate pages</small></span>
              <span class="pattern-chip" data-use-url="https://reports.example.com/invoice-*"><span class="use">USE</span>https://reports.example.com/invoice-*<small>prefix match</small></span>
              <div class="note" style="margin-bottom:0"><b>Syntax</b> = Chrome match patterns: <span class="mono">scheme://host/path</span> with <span class="mono">*</span> wildcards
                (<span class="mono">*</span> = any scheme, <span class="mono">*.host</span> = subdomains, trailing <span class="mono">*</span> = any path).
                <b>Learned from History</b> (top printed this week): <span class="mono">www.htncr.org/lab/&#8230;</span> 47 jobs ·
                <span class="mono">billing.local/pos/&#8230;</span> 23 · <span class="mono">intranet/certificates/&#8230;</span> 9 — press a chip above to turn one into a rule.</div>
            </div>
          </div>

          <!-- TEST BOX -->
          <div class="card">
            <div class="card-h">&#128269; Test which rule fires <span class="r">prints nothing — safe</span></div>
            <div class="card-b">
              <div class="frow" style="margin-bottom:6px">
                <label style="min-width:auto">Test a URL</label>
                <input class="inp mono" style="flex:1;min-width:260px;font-size:11px" value="https://www.htncr.org/lab/medical_reports/pdf/4711">
                <button class="btn blue">Which rule fires?</button>
              </div>
              <div class="frow" style="margin-bottom:0">
                <label style="min-width:auto">Test label / receipt text</label>
                <input class="inp mono" style="flex:1;min-width:260px;font-size:11px" value="^XA^LL200^FO30^FDLAB-4711^FS^XZ">
                <button class="btn blue">Which rule fires?</button>
              </div>
              <div class="note" style="margin-top:10px;margin-bottom:0">&#128269; URL test result: fires <b>Rule 1 "Lab PDF reports"</b> &#8594; printer <b>HP Laser 103 107 108</b>, action <b>PDF</b>, paper <b>A5</b>, 1 copy. The URL was fetched once (with your login) — content type detected: <span class="mono">application/pdf</span>. Nothing was printed.</div>
            </div>
          </div>

          <!-- RULES TABLE -->
          <div class="card">
            <div class="card-h">&#9881; Rules <span class="r">run top to bottom · first match wins · per-job printer always wins over the Print destination card</span></div>
            <table class="tbl" style="font-size:10px">
              <tr><th style="width:20px">#</th><th style="min-width:84px">Rule</th><th style="min-width:110px">URL / address filter</th><th>Match by</th><th>Page content</th><th>URL type</th><th style="min-width:90px">Printer</th><th>What to print</th><th style="width:30px">Cpl</th><th style="width:40px">Paper</th><th style="width:30px">On</th><th style="width:34px">Auto</th><th style="width:58px">Runs</th><th style="width:86px"></th></tr>
              <tr>
                <td class="id">&#9776; 1</td><td class="doc"><b>Lab PDF reports</b></td><td class="mono doc" style="max-width:112px;font-size:9.5px">*://www.htncr.org/lab/*</td><td><span class="chip info">URL</span></td><td>&mdash;</td><td>PDF</td>
                <td><b>HP Laser 103 107 108</b></td><td>Auto (PDF)</td><td>1</td><td>A5</td>
                <td><span class="switch on"></span></td><td><span class="switch on"></span></td>
                <td class="id">128 runs<br>last 14:22</td>
                <td><button class="btn small blue" data-edit-rule="0">Edit</button> <button class="btn small danger" data-del-rule="0">Del</button></td>
              </tr>
              <tr>
                <td class="id">&#9776; 2</td><td class="doc"><b>Zebra labels</b></td><td class="mono doc" style="font-size:9.5px">(any page)</td><td><span class="chip purple">CONTENT</span></td><td><span class="chip purple">ZPL label</span></td><td>any</td>
                <td><b>Zebra GK420d</b></td><td>Raw ZPL/ESC-POS</td><td>2</td><td>4&times;6&Prime;</td>
                <td><span class="switch on"></span></td><td><span class="switch on"></span></td>
                <td class="id">86 runs<br>last 14:18</td>
                <td><button class="btn small blue" data-edit-rule="1">Edit</button> <button class="btn small danger" data-del-rule="1">Del</button></td>
              </tr>
              <tr>
                <td class="id">&#9776; 3</td><td class="doc"><b>POS receipts</b></td><td class="mono doc" style="max-width:112px;font-size:9.5px">*://billing.local/pos/*</td><td><span class="chip purple">CONTENT</span></td><td><span class="chip warn">Receipt</span></td><td>text</td>
                <td><b>XP-58 Thermal</b></td><td>ESC-POS receipt</td><td>1</td><td>58mm</td>
                <td><span class="switch on"></span></td><td><span class="switch"></span></td>
                <td class="id">41 runs<br>last 14:12</td>
                <td><button class="btn small blue" data-edit-rule="2">Edit</button> <button class="btn small danger" data-del-rule="2">Del</button></td>
              </tr>
              <tr>
                <td class="id">&#9776; 4</td><td class="doc"><b>Certificates</b></td><td class="mono doc" style="max-width:112px;font-size:9.5px">*://intranet/certificates/*</td><td><span class="chip info">URL</span></td><td>&mdash;</td><td>Web</td>
                <td><b>AdvPrint Pro @ AI-Lab</b></td><td>Web page</td><td>1</td><td>A4</td>
                <td><span class="switch"></span></td><td><span class="switch on"></span></td>
                <td class="id">12 runs<br>last 11:02</td>
                <td><button class="btn small blue" data-edit-rule="3">Edit</button> <button class="btn small danger" data-del-rule="3">Del</button></td>
              </tr>
              <tr>
                <td class="id">&#9776; 5</td><td class="doc"><b>Invoices &#8594; PDF</b></td><td class="mono doc" style="max-width:112px;font-size:9.5px">https://reports.example.com/invoice-*</td><td><span class="chip info">URL</span></td><td>&mdash;</td><td>PDF</td>
                <td><b>Microsoft Print to PDF</b></td><td>PDF (save)</td><td>1</td><td>A4</td>
                <td><span class="switch on"></span></td><td><span class="switch on"></span></td>
                <td class="id">7 runs<br>last 09:44</td>
                <td><button class="btn small blue" data-edit-rule="4">Edit</button> <button class="btn small danger" data-del-rule="4">Del</button></td>
              </tr>
              <tr>
                <td class="id">&#9776; 6</td><td class="doc"><b>Night reports</b></td><td class="mono doc" style="font-size:9.5px">(any page)</td><td><span class="chip purple">CONTENT</span> <span class="chip info">URL</span></td><td><span class="chip purple">Patient Report</span></td><td>Web</td>
                <td><b>HP Laser 103 107 108</b></td><td>Web page</td><td>2</td><td>A4</td>
                <td><span class="switch on"></span></td><td><span class="switch on"></span></td>
                <td class="id">3 runs<br>18&#8211;08h</td>
                <td><button class="btn small blue" data-edit-rule="5">Edit</button> <button class="btn small danger" data-del-rule="5">Del</button></td>
              </tr>
            </table>
            <div class="note" style="margin:0 14px 12px">Every row is fully editable: <b>Edit</b> opens the 3-step rule editor pre-filled, <b>Del</b> asks twice then removes,
              the <b>On</b> switch pauses a rule without deleting, and <b>Auto</b> decides silent vs. one confirm dialog. Drag <span class="mono">&#9776;</span> to change priority.</div>
          </div>

          <div class="card">
            <div class="card-h">&#128203; Rule activity log <span class="r">sent / FAILED + why</span>
              <span class="r" style="margin-left:12px"><button class="btn small">&#8635; Refresh</button> <button class="btn small danger">Clear log</button></span></div>
            <table class="tbl">
              <tr><th style="width:110px">Time</th><th style="width:26%">Rule</th><th style="width:110px">Action</th><th style="width:20%">Printer</th><th>Page / result</th></tr>
              <tr><td class="id">14:22:08</td><td class="doc">Lab PDF reports (URL)</td><td><span class="chip info">PDF</span></td><td>HP Laser 103 107 108</td><td><span class="chip ok">SENT</span> lab-report-nov.pdf · A5</td></tr>
              <tr><td class="id">14:18:45</td><td class="doc">Zebra labels (content)</td><td><span class="chip purple">ZPL</span></td><td>Zebra GK420d</td><td><span class="chip ok">SENT</span> raw 212 B · ^XA&#8230;^XZ byte-for-byte</td></tr>
              <tr><td class="id">14:12:31</td><td class="doc">POS receipts (content)</td><td><span class="chip warn">ESC-POS</span></td><td>XP-58 Thermal</td><td><span class="chip ok">SENT</span> receipt + auto cut</td></tr>
              <tr><td class="id">13:58:12</td><td class="doc">Lab PDF reports (URL)</td><td><span class="chip info">PDF</span></td><td>HP Laser 103 107 108</td><td><span class="chip err">FAILED</span> media-out · retried 1/2</td></tr>
            </table>
          </div>
        </section>

        <!-- ============ POWER SWITCHES ============ -->
        <section class="panel" id="p-power">
          <div class="p-head">
            <h2>Power Switches</h2><span class="sub">every silent / background behavior of the extension — one switch each · v3.2.2: every switch SAVES the moment you flip it</span>
          </div>
          <div class="card">
            <div class="card-h">&#9889; Power switches <span class="r">same switches as the extension options — now in the ONE UI</span></div>
            <div class="card-b">
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>AdvPrint enabled (master switch)</b><p>OFF = the extension stops completely: no printing, no auto-print, no window.print() hook, no page API, no context menu. A gray OFF badge shows on the toolbar icon.</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Queue mode (jobs wait in order)</b><p>ON = every job goes through the hub queue in order (Pause/Resume works, big jobs line up). OFF = instant print. If no printer is active the job is auto-queued instead of failing.</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Auto-print rules (silent background printing)</b><p>The power switch for every rule in the Rules tab. OFF (paused) = NO rule auto-prints; manual prints keep working.</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Intercept window.print() (web app prints go silent)</b><p>Web apps (Odoo, POS, dashboards) that call window.print() print silently through the hub instead of opening the dialog. Also intercepts Ctrl+P / Cmd+P.</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch"></span></span>
                <div><b>Debug mode — find problems fast</b><p>ON = the extension reports every error to the hub and the hub logs verbosely. Open the Debug tab to see WHEN / WHY / WHERE printing fails.</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Retry when the hub comes back</b><p>If the hub is offline, jobs are kept in the browser and sent automatically as soon as the hub answers again (checked every minute).</p></div></div>
              <div class="tgl"><span class="sw"><select class="inp" style="min-width:110px"><option>Automatic</option><option>English</option><option>&#2476;&#2494;&#2434;&#2455;&#2509;&#2482;&#2494;</option></select></span>
                <div><b>UI language</b><p>English or &#2476;&#2494;&#2434;&#2455;&#2509;&#2482;&#2494; for the extension pages and notifications. "Automatic" follows the browser language.</p></div></div>
            </div>
          </div>
          <div class="note">These switches live in the paired browsers. Flip a switch and it is saved <b>instantly</b> — every paired Chrome/Edge adopts the new settings within a minute, no save button needed (v3.2.2: the switches finally work).</div>
        </section>

        <!-- ============ BROWSER BEHAVIOR ============ -->
        <section class="panel" id="p-browser">
          <div class="p-head">
            <h2>Browser Behavior</h2><span class="sub">what happens around the printing — tabs, menus, badges</span>
          </div>
          <div class="card">
            <div class="card-h">&#127760; Browser behavior</div>
            <div class="card-b">
              <div class="tgl"><span class="sw"><span class="switch"></span></span>
                <div><b>Print every PDF opened in the browser (simple mode)</b><p>ANY PDF you open is printed silently and its tab closes. No dialog, no rules needed.</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch"></span></span>
                <div><b>Close tab after auto-print (default OFF)</b><p>ON: when a rule auto-prints an opened URL, the tab closes right after the job is queued — zero browser view, the paper just comes out.</p></div></div>
              <div class="tgl"><span class="sw"><select class="inp" style="min-width:170px"><option>Open the URL in a new tab</option><option>Stay silent (no tab)</option></select></span>
                <div><b>When a page print call fails</b><p>Controls the automatic fallback: open the URL in a normal tab so the browser prints it the default way, or stay completely silent.</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Right-click menu</b><p>Adds "AdvPrint Pro" to the right-click menu: print page / print selection / print linked PDF / print screenshot.</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Toolbar badge (green OK / red !)</b><p>Shows OK or ! on the extension icon for a few seconds after every job.</p></div></div>
            </div>
          </div>
          <div class="note">Context-menu and badge changes apply to new pages immediately; the PDF simple-mode switch re-checks open PDF tabs on the next navigation.</div>
        </section>

        <!-- ============ EXTENSION ============ -->
        <section class="panel" id="p-extension">
          <div class="p-head">
            <h2>Extension</h2><span class="sub">paired browsers, silent install, hub token</span>
            <div class="right"><button class="btn">&#128273; New Token</button></div>
          </div>
          <div class="dash-row">
            <div class="card">
              <div class="card-h">&#128274; Paired Browsers <span class="r">2 connected</span></div>
              <table class="tbl">
                <tr><th>Client</th><th>Extension</th><th>Last seen</th><th>Status</th></tr>
                <tr><td><b>AI-Lab-PC · Chrome</b></td><td>v3.2.1</td><td>just now</td><td><span class="chip ok"><span class="d"></span>PAIRED</span></td></tr>
                <tr><td><b>client-laptop · Edge</b></td><td>v3.2.1</td><td>2 min ago</td><td><span class="chip ok"><span class="d"></span>PAIRED</span></td></tr>
              </table>
              <div class="note orange" style="margin:10px 14px 12px">
                <b style="display:block;margin-bottom:3px">&#9888; Two extension installs detected on this PC</b>
                Policy CRX <span class="mono">likldbk&#8230;bbnohc</span> and a dev/unpacked copy <span class="mono">honpjjb&#8230;mjbjo</span> are both loaded.
                Disable one in <span class="mono">chrome://extensions</span> to avoid double jobs.
              </div>
            </div>
            <div class="card">
              <div class="card-h">&#128273; Hub Token</div>
              <div class="kv">
                <span class="k">Token</span><span class="v mono">mPz5HFOsB9xaJ36isQ7kDfjaaNrERnXs</span>
                <span class="k">Auth</span><span class="v"><span class="chip ok"><span class="d"></span>X-PrintHub-Token</span></span>
                <span class="k">Rotate</span><span class="v" style="color:var(--warn);font-weight:700">&#9888; rotating token un-pairs browsers</span>
              </div>
            </div>
          </div>
          <div class="card">
            <div class="card-h">&#128231; Silent install — deploy the CRX to every PC without Chrome Web Store <span class="r">works on every Chromium browser</span></div>
            <div class="card-b">
              <div class="note orange" id="extStaleWarn" style="display:none;margin:0 0 10px">
                <b style="display:block;margin-bottom:3px">&#9888; Stale CRX — your browsers are NOT auto-updating</b>
                <span id="extStaleTxt">The hub serves an older extension than the hub itself. Chrome checks updates.xml, sees no higher version and keeps the OLD extension running (old bugs included — e.g. the http-page API refusal). Fix: re-run the Setup, or copy the current AdvPrint-Pro.crx over hub/extension/AdvPrint-Pro.crx — no restart needed.</span>
              </div>
              <div class="frow" style="margin-bottom:8px">
                <span class="chip ok"><span class="d"></span>CRX v3.2.1 READY</span>
                <span class="mono" style="font-size:11px;color:var(--blue-deep)">AdvPrint-Pro.crx</span>
                <span style="flex:1"></span>
                <button class="btn small">Download CRX</button>
              </div>
              <div class="frow" style="margin-bottom:6px">
                <label style="min-width:150px">Forcelist value</label>
                <span class="mono" style="font-size:10.5px;color:var(--blue-deep);background:var(--blue-soft);border:1px solid var(--blue-line);border-radius:6px;padding:5px 9px">kppjdmdbbnaaibjjbbnohcjkabmifana;http://10.26.94.206:9235/updates.xml</span>
                <button class="btn small">Copy value</button>
              </div>
              <div class="frow" style="margin-bottom:0">
                <label style="min-width:150px">Updates XML</label>
                <span class="mono" style="font-size:10.5px;color:var(--blue-deep)">http://10.26.94.206:9235/updates.xml</span>
                <button class="btn small">Copy URL</button>
                <span style="font-size:10.5px;color:var(--muted)">served by this hub — CRX auto-updates even without the Web Store</span>
              </div>
            </div>
            <table class="tbl" style="font-size:10.5px">
              <tr><th style="min-width:120px">Browser (Chromium)</th><th>Policy registry path — same value, one row per browser</th><th style="width:120px">Status</th><th style="width:150px"></th></tr>
              <tr>
                <td><b>Google Chrome</b></td>
                <td class="mono doc" style="font-size:9.5px">HKLM\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist</td>
                <td><span class="chip ok"><span class="d"></span>INSTALLED</span></td>
                <td><button class="btn small">Apply HKLM</button> <button class="btn small">Apply HKCU</button></td>
              </tr>
              <tr>
                <td><b>Microsoft Edge</b></td>
                <td class="mono doc" style="font-size:9.5px">HKLM\SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist</td>
                <td><span class="chip ok"><span class="d"></span>INSTALLED</span></td>
                <td><button class="btn small">Apply HKLM</button> <button class="btn small">Apply HKCU</button></td>
              </tr>
              <tr>
                <td><b>Brave</b></td>
                <td class="mono doc" style="font-size:9.5px">HKLM\SOFTWARE\Policies\BraveSoftware\Brave\ExtensionInstallForcelist</td>
                <td><span class="chip warn">NOT SET</span></td>
                <td><button class="btn small">Apply HKLM</button> <button class="btn small">Apply HKCU</button></td>
              </tr>
              <tr>
                <td><b>Vivaldi</b></td>
                <td class="mono doc" style="font-size:9.5px">HKLM\SOFTWARE\Policies\Vivaldi\ExtensionInstallForcelist</td>
                <td><span class="chip info">SUPPORTED</span></td>
                <td><button class="btn small">Apply HKLM</button> <button class="btn small">Apply HKCU</button></td>
              </tr>
              <tr>
                <td><b>Chromium</b></td>
                <td class="mono doc" style="font-size:9.5px">HKLM\SOFTWARE\Policies\Chromium\ExtensionInstallForcelist</td>
                <td><span class="chip info">SUPPORTED</span></td>
                <td><button class="btn small">Apply HKLM</button> <button class="btn small">Apply HKCU</button></td>
              </tr>
              <tr>
                <td><b>Opera / others</b></td>
                <td class="mono doc" style="font-size:9.5px">HKLM\SOFTWARE\Policies\Opera Software\Opera\ExtensionInstallForcelist <span style="color:var(--muted)">(verify once — some builds ignore forcelist)</span></td>
                <td><span class="chip gray">TEST</span></td>
                <td><button class="btn small">Apply HKLM</button> <button class="btn small">Apply HKCU</button></td>
              </tr>
            </table>
            <div class="card-b" style="padding-top:10px">
              <div class="note" style="margin-bottom:10px"><b>One CRX, every Chromium browser.</b> The same <span class="mono">AdvPrint-Pro.crx</span> installs into Chrome, Edge, Brave, Vivaldi, Chromium and Opera —
                only the policy key path differs (table above). <b>Apply HKLM</b> = machine-wide for every user of this PC (needs admin);
                <b>Apply HKCU</b> = only the current user. The browser force-installs the CRX silently on next start and keeps it
                auto-updated from <span class="mono">/updates.xml</span> served by this hub — <b>no drag &amp; drop, no Web Store, no developer mode</b>.</div>
              <div class="note orange" style="margin-bottom:0"><b>Not Chromium browsers:</b> Firefox uses the same WebExtension codebase packaged as <span class="mono">.xpi</span>
                (deploy with the Firefox enterprise policy <span class="mono">HKLM\SOFTWARE\Policies\Mozilla\Firefox\Extensions</span> or install manually);
                Safari is not supported. If a Chromium fork ignores forcelist, drag-install the CRX on that browser once — pairing still works.</div>
            </div>
          </div>

          <div class="card">
            <div class="card-h">&#9888; Chrome message: "This extension is not listed in the Chrome Web Store and may have been added without your knowledge" <span class="r">expected — explained</span></div>
            <div class="card-b">
              <div style="background:#fff7ed;border:1px solid #fdba74;border-radius:8px;padding:9px 12px;font-size:11.5px;color:#9a3412;line-height:1.5;margin-bottom:10px">
                &#9888; This extension is not listed in the Chrome Web Store and may have been added without your knowledge.
              </div>
              <div style="font-size:11.5px;color:var(--ink-2);line-height:1.65">
                <b>What it means:</b> the browser shows this banner for <b>any extension installed outside the Web Store</b> — your own
                <span class="mono">AdvPrint-Pro.crx</span> deployed by policy or drag &amp; drop. <b>It is not a virus warning and printing is not affected.</b><br>
                <b>Why you see it:</b> AdvPrint Pro is a private, self-hosted extension for this organisation — it is intentionally not on the Web Store.
                The banner disappears when a Web Store listing is published.<br>
                <b>What to do:</b> nothing — keep it, or make the banner vanish by installing the CRX through the
                <b>policy table above</b> (policy-installed extensions show as "Installed by your administrator" instead of the warning).
                Check <span class="mono">chrome://extensions</span> — the extension ID must match the forcelist value above.
              </div>
            </div>
          </div>
        </section>

        <!-- ============ DEBUG ============ -->
        <section class="panel" id="p-debug">
          <div class="p-head">
            <h2>Debug &amp; Tools</h2><span class="sub">find out WHEN / WHY / WHERE printing fails</span>
            <div class="right"><span class="chip warn">DEBUG MODE OFF</span><button class="btn">Enable debug</button></div>
          </div>

          <div class="card">
            <div class="card-h">&#9888; Service check <span class="r">Windows service state</span></div>
            <div class="card-b" style="font-size:12px;color:var(--ink-2)">
              Windows service <b>'AdvPrint'</b> is <span class="chip warn">START PENDING</span>
              — a stale state from an old install. The hub itself is healthy (running in tray mode).
              <div style="display:flex;gap:8px;margin-top:10px">
                <button class="btn small blue">Run service-remove</button>
                <button class="btn small">Re-check</button>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-h">&#128220; Client error reports <span class="r">sent by the extension when a job fails</span></div>
            <table class="tbl">
              <tr><th>Time</th><th>Source</th><th>Problem</th><th></th></tr>
              <tr><td class="id">14:05:22</td><td><span class="chip info">chrome-ext</span></td><td class="doc">job #11 — save-as-PDF failed: PDF still locked by antivirus/another process</td><td><button class="btn small blue">Retry now</button> <button class="btn small">Open spool</button></td></tr>
              <tr><td class="id">13:58:12</td><td><span class="chip info">hub</span></td><td class="doc">job #2043 — printer HP Laser offline (status hold kept the job)</td><td><button class="btn small">Release</button></td></tr>
            </table>
          </div>

          <div class="card">
            <div class="card-h">&#128300; Live debug &amp; test tool <span class="r">v3.2.1 · runs on this PC immediately</span></div>
            <div class="card-b" style="display:flex;gap:8px;flex-wrap:wrap">
              <button class="btn blue">&#128424; REAL test print</button>
              <button class="btn">&#9889; Release ALL held</button>
              <button class="btn">&#128300; Full self-test</button>
              <button class="btn">&#128196; Open spool folder</button>
              <button class="btn">&#128220; Export debug bundle</button>
            </div>
          </div>

          <div class="card">
            <div class="card-h">&#9881; Debug switches</div>
            <div class="card-b">
              <div class="tgl"><span class="sw"><span class="switch"></span></span>
                <div><b>Debug mode</b><p>Verbose hub logging + the extension reports every error here. Leave OFF in normal use.</p></div></div>
              <div class="tgl"><span class="sw"><span class="switch on"></span></span>
                <div><b>Client error reports</b><p>Paired browsers may attach a short report (page URL, error text) when a job fails — no document content is sent.</p></div></div>
            </div>
          </div>
        </section>

        <!-- ============ AUDIT ============ -->
        <section class="panel" id="p-audit">
          <div class="p-head">
            <h2>Audit</h2><span class="sub">who printed what — full trail</span>
            <div class="right"><button class="btn">&#8632; Export CSV</button><button class="btn danger">Clear audit</button></div>
          </div>
          <div class="card">
            <table class="tbl">
              <tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Result</th></tr>
              <tr><td class="id">14:22:08</td><td><span class="chip info">chrome-ext</span></td><td>job.submit</td><td class="doc">lab-report-nov.pdf &#8594; HP Laser</td><td><span class="chip ok">ACCEPTED</span></td></tr>
              <tr><td class="id">14:19:41</td><td><span class="chip info">chrome-ext</span></td><td>job.complete</td><td class="doc">invoice-2026-11.pdf</td><td><span class="chip ok">DONE</span></td></tr>
              <tr><td class="id">14:12:30</td><td><span class="chip info">ipp-client</span></td><td>ipp.create-job</td><td class="mono doc">/ipp/print/HP-Laser</td><td><span class="chip ok">OK</span></td></tr>
              <tr><td class="id">14:08:11</td><td><span class="chip info">dropzone</span></td><td>dropzone.print</td><td class="doc">lab-request-form.pdf</td><td><span class="chip ok">DONE</span></td></tr>
              <tr><td class="id">14:05:22</td><td><span class="chip info">chrome-ext</span></td><td>ext.error-report</td><td class="doc">job #11 · PDF locked by antivirus</td><td><span class="chip warn">REPORTED</span></td></tr>
              <tr><td class="id">13:58:12</td><td><span class="chip info">hub</span></td><td>job.failed</td><td class="doc">manual-de.pdf · media-out</td><td><span class="chip err">ERROR</span></td></tr>
              <tr><td class="id">13:41:02</td><td><span class="chip info">hub</span></td><td>auth.reject</td><td class="mono doc">wrong token from 10.26.94.77</td><td><span class="chip warn">DENIED</span></td></tr>
              <tr><td class="id">13:12:02</td><td><span class="chip info">hub</span></td><td>settings.lan</td><td class="mono doc">lan_sharing = on</td><td><span class="chip ok">OK</span></td></tr>
            </table>
          </div>
        </section>

        <!-- ============ LOGS ============ -->
        <section class="panel" id="p-logs">
          <div class="p-head">
            <h2>Logs</h2><span class="sub">hub log tail · live</span>
            <div class="right">
              <span class="fchip on">ALL</span><span class="fchip">INFO</span><span class="fchip">WARN</span><span class="fchip">ERROR</span>
              <button class="btn small" style="margin-left:6px">&#128190; Save log</button>
            </div>
          </div>
          <div class="logbox">
            <div><span class="ts">14:22:08.412</span> <span class="lv I">INFO </span> job #2047 submitted by <span class="hl">chrome-ext</span> &#8594; printer <span class="hl">HP Laser 103 107 108</span> (12 pages)</div>
            <div><span class="ts">14:22:08.470</span> <span class="lv I">INFO </span> IPP Create-Job ok · job-id=2047 uri=<span class="hl">/ipp/print/HP-Laser</span></div>
            <div><span class="ts">14:22:08.518</span> <span class="lv I">INFO </span> Send-Document chunk 1/3 (786 KB) spool &#8594; C:\Users\Admin\.advprint\spool\2047.pdf</div>
            <div><span class="ts">14:19:41.882</span> <span class="lv I">INFO </span> job #2046 completed · PDF saved &#8594; D:\PDF\invoice-2026-11.pdf</div>
            <div><span class="ts">14:08:11.774</span> <span class="lv W">WARN </span> DropZone: discharge-summary.pdf waiting — printer <span class="hl">HP Laser</span> offline (status hold)</div>
            <div><span class="ts">14:05:22.010</span> <span class="lv E">ERROR</span> ext report: job #11 save-as-PDF failed — PDF still locked by antivirus/another process</div>
            <div><span class="ts">13:58:12.905</span> <span class="lv E">ERROR</span> job #2043 failed · media-out · retried 1/2</div>
            <div><span class="ts">13:41:02.336</span> <span class="lv W">WARN </span> auth rejected from 10.26.94.77 (bad token)</div>
            <div><span class="ts">13:12:00.100</span> <span class="lv I">INFO </span> RAW JetDirect listening on <span class="hl">10.26.94.206:9100</span></div>
            <div><span class="ts">10:00:01.002</span> <span class="lv I">INFO </span> AdvPrint Pro hub v3.2.1 started · 4 printers · LAN ON · DropZone ON · tray ON</div>
          </div>
        </section>

        <!-- ============ SETTINGS ============ -->
        <section class="panel" id="p-settings">
          <div class="p-head">
            <h2>Settings</h2><span class="sub">stored in hub config · applied live</span>
          </div>
          <div class="form">
            <div class="f-row"><label>HUB PORT</label><input class="inp" value="9235"><div class="hint">Default 9235 · restart required</div></div>
            <div class="f-row"><label>AUTH TOKEN</label><input class="inp mono" value="mPz5HFOsB9xaJ36isQ7kDfjaaNrERnXs"><div class="hint">Sent as X-PrintHub-Token header · <button class="btn small" style="height:20px">Rotate token</button></div></div>
            <div class="f-row"><label>START WITH WINDOWS</label><div style="display:flex;align-items:center;gap:10px"><span class="switch on"></span><span style="font-size:11.5px;color:var(--ink-2)">Auto-start hub at login (tray mode)</span></div></div>
            <div class="f-row"><label>MINIMIZE TO TRAY</label><div style="display:flex;align-items:center;gap:10px"><span class="switch on"></span><span style="font-size:11.5px;color:var(--ink-2)">Close button hides the window</span></div></div>
            <div class="f-row"><label>LAN SHARING</label><div style="display:flex;align-items:center;gap:10px"><span class="switch on green"></span><span style="font-size:11.5px;color:var(--ink-2)">http://10.26.94.206:9235 · see LAN tab</span></div></div>
            <div class="f-row"><label>PRINTER STATUS HOLD</label><div style="display:flex;align-items:center;gap:10px"><span class="switch on"></span><span style="font-size:11.5px;color:var(--ink-2)">Jobs wait while a printer reports offline</span></div></div>
            <div class="f-row"><label>KEEP JOBS (DAYS)</label><input class="inp" value="30"><div class="hint">History older than this is cleaned up</div></div>
            <div class="f-row"><label>LOG LEVEL</label><select><option>INFO</option><option>DEBUG</option><option>WARN</option><option>ERROR</option></select></div>
            <div class="f-row"><label>THEME</label><select><option>Windows IDM (Blue)</option><option>Light</option><option>Dark</option></select></div>
            <div class="f-row"><label>DATA FOLDER</label><div class="hint" style="font-size:11px"><span class="mono">C:\Users\Admin\.advprint</span> · <button class="btn small" style="height:20px">Open data folder</button></div></div>
          </div>
          <div style="display:flex;gap:8px"><button class="btn blue">&#128190; Save &amp; Apply</button><button class="btn">Restore Defaults</button><button class="btn">&#128260; Restart hub</button></div>
        </section>

        <!-- ============ ABOUT ============ -->
        <section class="panel" id="p-about">
          <div class="p-head">
            <h2>About</h2><span class="sub">version, brand, THE ONE UI statement</span>
            <div class="right"><button class="btn blue">&#128230; Check for updates</button></div>
          </div>
          <div class="card">
            <div class="card-b" style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap">
              <div style="width:64px;height:64px;border-radius:12px;background:linear-gradient(135deg,#1e40af,#1d4ed8);color:#fff;display:flex;align-items:center;justify-content:center;font-size:26px;font-weight:800;box-shadow:0 8px 22px rgba(29,78,216,.35)">AP</div>
              <div style="flex:1;min-width:260px">
                <div style="font-size:17px;font-weight:800;color:var(--ink)">AdvPrint Pro — Printing Hub <span class="chip ok" style="margin-left:8px">v3.2.1 · UP TO DATE</span></div>
                <div style="font-size:12px;color:var(--ink-2);margin-top:4px">by <b>Bit Dream IT — Innovative Healthcare Solutions</b></div>
                <div style="font-size:11.5px;color:var(--muted);margin-top:2px">Chrome silent-print extension + local print hub · port 9235 · 100% local, no cloud</div>
                <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
                  <button class="btn small">GitHub repo</button>
                  <button class="btn small">Releases</button>
                  <button class="btn small">Docs</button>
                  <button class="btn small">Release notes</button>
                </div>
              </div>
            </div>
          </div>
          <div class="card">
            <div class="card-h">&#9635; THE ONE UI</div>
            <div class="card-b" style="font-size:12px;color:var(--ink-2);line-height:1.75">
              This console is the <b>only</b> management interface of AdvPrint Pro. The old scattered areas are now tabs here:
              the classic dashboard cards &#8594; <b>Dashboard / Printers / LAN / DropZone</b>,
              the old Jobs page &#8594; <b>separate Queue and History tabs</b>,
              the extension options switches &#8594; <b>Power Switches / Browser / Rules / Connections / Hub</b>,
              and the debug cards &#8594; <b>Debug &amp; Tools</b>.
              It is served by the hub at <span class="mono">/ui</span> with <b>zero external files</b> (the v3.1.2 "console.html was not found" error can never happen again),
              opens identically in the native window, in Chrome, and inside the extension options tab.
            </div>
          </div>
        </section>

      </main>
    </div>

    <!-- ================= STATUS BAR ================= -->
    <div class="statusbar">
      <span class="sb-pane"><span class="dot"></span> Hub Running</span>
      <span class="sb-pane mono">10.26.94.206:9235</span>
      <span class="sb-pane">Printers <b>4</b> · Ready <b>3</b></span>
      <span class="sb-pane">Queue <b>4</b></span>
      <span class="sb-pane">History <b>12</b></span>
      <span class="sb-pane">LAN <b>ON</b></span>
      <span class="sb-pane">DropZone <b>ON</b></span>
      <span class="sb-pane grow"></span>
      <span class="sb-pane">Uptime 04:12:37</span>
      <span class="sb-pane"><b>Printing Hub v3.2.1</b> · Bit Dream IT</span>
    </div>

  </div>
</div>
<!-- ================= QR ENLARGE MODAL ================= -->
<div class="modal-back" id="qrmodal">
  <div class="modal">
    <div class="m-h"><span id="qr-title">QR code</span><button class="x" data-close>&#x2715;</button></div>
    <div class="m-b">
      <div class="mq" id="qr-box"></div>
      <div class="murl" id="qr-url"></div>
      <div class="mops"><button class="btn blue" id="qr-copy">&#128203; Copy link</button><button class="btn" data-close>Close</button></div>
      <div class="mnote" id="qr-note"></div>
    </div>
  </div>
</div>

<!-- ================= IN-UI DOCS MODAL (v3.2.6 BUG FIX 6) =================
     The full guide opens INSIDE THE ONE UI - no extra old-UI tab. -->
<div class="modal-back" id="docsmodal">
  <div class="modal wide" style="width:min(860px,94vw)">
    <div class="m-h"><span id="docs-title">Docs &#8212; quick start &amp; how-to</span><button class="x" data-close>&#x2715;</button></div>
    <div class="m-b docs-body" id="docs-body" style="max-height:70vh;overflow-y:auto;text-align:left;padding:16px 20px"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;padding:10px 16px;border-top:1px solid #e2e8f0;background:#f8fafc">
      <button class="btn small" id="docs-lnk-old">Full guide page</button>
      <button class="btn blue" data-close>Close</button>
    </div>
  </div>
</div>

<!-- ================= KEYBOARD SHORTCUTS MODAL ================= -->
<div class="modal-back" id="keysmodal">
  <div class="modal">
    <div class="m-h"><span>Keyboard shortcuts</span><button class="x" data-close>&#x2715;</button></div>
    <div class="m-b" style="text-align:left">
      <table class="mtable">
        <tr><td>Ctrl+1 … Ctrl+8</td><td>Dashboard · Queue · History · Printers · LAN · DropZone · Connections · Hub</td></tr>
        <tr><td>Ctrl+N</td><td>New print job (opens Queue)</td></tr>
        <tr><td>Ctrl+D</td><td>Open DropZone folder</td></tr>
        <tr><td>Ctrl+T</td><td>REAL test print page</td></tr>
        <tr><td>F1</td><td>About AdvPrint Pro</td></tr>
        <tr><td>F5</td><td>Show / hide the status bar</td></tr>
        <tr><td>F11</td><td>Full screen</td></tr>
        <tr><td>Esc</td><td>Close menu · close dialog</td></tr>
        <tr><td>Alt+F4</td><td>Exit hub (stops printing — jobs already queued are kept)</td></tr>
      </table>
      <div class="mnote" style="text-align:center">Shortcuts work in the native window and in the browser at /ui. The extension adds its own page-level shortcuts.</div>
    </div>
  </div>
</div>

<!-- ================= RULE EDITOR MODAL ================= -->
<div class="modal-back" id="rulemodal">
  <div class="modal wide">
    <div class="m-h"><span id="re-title">Edit rule — Lab PDF reports</span><button class="x" data-close>&#x2715;</button></div>
    <div class="m-b" style="text-align:left;padding:14px 18px 16px">

      <div class="re-step"><span class="n">1</span><b>Match by — which pages does this rule catch?</b></div>
      <div class="re-grid">
        <div class="full">
          <label class="rl">URL / ADDRESS FILTER (chrome match pattern)</label>
          <input class="inp2 mono" id="re-url" value="*://www.htncr.org/lab/*">
          <div class="hint2">Suggested: <span class="pattern-chip" data-fill-url="*://*.htncr.org/*" style="margin:0 4px 0 0">*://*.htncr.org/*</span>
            <span class="pattern-chip" data-fill-url="*://*/*.pdf" style="margin:0 4px 0 0">*://*/*.pdf</span>
            <span class="pattern-chip" data-fill-url="*://intranet/certificates/*" style="margin:0">*://intranet/certificates/*</span> — click to fill</div>
        </div>
        <div>
          <label class="rl">PAGE CONTENT MUST CONTAIN (optional)</label>
          <input class="inp2" id="re-content" placeholder="e.g. Patient Report, ZPL, invoice number…">
          <div class="hint2">Leave empty = any page content.</div>
        </div>
        <div>
          <label class="rl">URL TYPE</label>
          <select class="inp2" id="re-type"><option selected>PDF link</option><option>Web page</option><option>Plain text / stream</option><option>Any</option></select>
          <div class="hint2">PDF link = the job is the .pdf file itself.</div>
        </div>
        <div class="full">
          <div class="note" style="margin:0;font-size:10.5px">&#128269; Live test: <span class="mono">https://www.htncr.org/lab/medical_reports/pdf/4711</span> &#8594; <b style="color:var(--ok)">matches</b> this rule (scheme &#10003; host &#10003; path &#10003; content-type application/pdf).</div>
        </div>
      </div>

      <div class="re-step"><span class="n">2</span><b>Then print — where and how</b></div>
      <div class="re-grid">
        <div>
          <label class="rl">PRINTER</label>
          <select class="inp2" id="re-printer"><option selected>HP Laser 103 107 108</option><option>Microsoft Print to PDF</option><option>OneNote</option><option>Zebra GK420d</option><option>XP-58 Thermal</option><option>AdvPrint Pro @ AI-Lab (IPP virtual)</option></select>
        </div>
        <div>
          <label class="rl">WHAT TO PRINT</label>
          <select class="inp2" id="re-what"><option selected>Auto (PDF as-is)</option><option>Entire web page</option><option>Selected element only</option><option>Raw text / ZPL / ESC-POS stream</option><option>Linked PDF only</option></select>
        </div>
        <div>
          <label class="rl">COPIES</label>
          <input class="inp2" id="re-copies" type="number" min="1" max="99" value="1">
        </div>
        <div>
          <label class="rl">PAPER</label>
          <select class="inp2" id="re-paper"><option>A4</option><option selected>A5</option><option>Letter</option><option>Legal</option><option>4&times;6&Prime; label</option><option>58mm receipt</option><option>Driver default</option></select>
        </div>
        <div>
          <label class="rl">COLOR</label>
          <select class="inp2"><option>Driver default</option><option>Black &amp; white</option><option>Color</option></select>
        </div>
        <div>
          <label class="rl">DUPLEX</label>
          <select class="inp2"><option selected>Simplex</option><option>Long-edge duplex</option><option>Short-edge duplex</option></select>
        </div>
      </div>

      <div class="re-step"><span class="n">3</span><b>When — how the rule runs</b></div>
      <div class="re-grid">
        <div>
          <label class="rl">RULE ON?</label>
          <div style="display:flex;align-items:center;gap:10px;height:29px"><span class="switch on" id="re-on"></span><span style="font-size:11px;color:var(--ink-2)">enabled</span></div>
        </div>
        <div>
          <label class="rl">AUTO (SILENT — NO DIALOG)?</label>
          <div style="display:flex;align-items:center;gap:10px;height:29px"><span class="switch on" id="re-auto"></span><span style="font-size:11px;color:var(--ink-2)">auto — prints without asking</span></div>
        </div>
        <div>
          <label class="rl">SCHEDULE (OPTIONAL)</label>
          <select class="inp2" id="re-sched"><option selected>Always</option><option>Working hours 08:00&ndash;18:00</option><option>Nights 18:00&ndash;08:00</option><option>Weekends only</option></select>
        </div>
        <div>
          <label class="rl">PRIORITY</label>
          <input class="inp2" id="re-priority" type="number" min="1" max="99" value="1">
          <div class="hint2">Lower number = checked first. First match wins.</div>
        </div>
      </div>

      <div style="display:flex;gap:8px;margin-top:16px;align-items:center">
        <button class="btn blue" id="re-save">&#128190; Save rule</button>
        <button class="btn" data-close>Cancel</button>
        <span style="flex:1"></span>
        <button class="btn danger" id="re-delete">&#128465; Delete rule</button>
      </div>
    </div>
  </div>
</div>

<!-- ================= TOASTS ================= -->
<div id="toasts"></div>

<script>
"use strict";
/* ============================================================
   AdvPrint Pro v3.2.1 - THE ONE UI (rev-4 design markup)
   Production wiring: the approved All-in-One design markup is
   served byte-for-byte; THIS script replaces the design demo
   script and feeds live hub data into it. Same token auth, same
   endpoints, same 14 tools as v3.2.0 - new face per rev-4.
   by Bit Dream IT - Innovative Healthcare Solutions
   ============================================================ */

/* ---------- boot data injected by the hub ---------- */
var BOOT = { view: "self", host: "this PC", lan_ip: "", port: "", version: "" };
try {
  var _bj = document.getElementById("bootjson");
  if (_bj) BOOT = Object.assign(BOOT, JSON.parse(_bj.textContent || "{}"));
} catch (e) { /* served as a plain file - defaults are fine */ }
window.ADVPRINT_BOOT = BOOT;
var qs = new URLSearchParams(location.search);
var VIEW_OVERRIDE = (qs.get("view") || "").toLowerCase();
if (VIEW_OVERRIDE === "center" || VIEW_OVERRIDE === "self") BOOT.view = VIEW_OVERRIDE;
var IS_CENTER = BOOT.view === "center";
var VIEW_LABEL = IS_CENTER ? "CENTER PC UI" : "SELF PC UI";

var TOKEN = qs.get("token") || localStorage.getItem("advprintHubToken") || "";
var BASE = location.origin;
var pollTimer = null, cfgCache = {}, jobFilter = "", auditRows = [], printersCache = [];
/* v3.2.5 BUG FIXES 2 + 3: checkbox selections that SURVIVE the 3 s poll.
   Every re-render used to force the boxes back to unchecked - the user
   ticked rows, the poll wiped them ("Job History select it auto refresh
   not select"). histSel / queueSel remember the ticked job ids and every
   render re-applies them. */
var histSel = {}, queueSel = {}, histSelCount = 0, queueSelCount = 0;
var rulesCache = [], ruleEditIdx = -1, pausedState = false, hubStartTime = null;
var dirtyKeys = {};   /* inputs touched but not saved yet - poll must not overwrite */
var EXT_ID = "likldbkamojokkfdlcjibiljpgbbnohc";
var SVG_PAUSE = '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><rect x="6" y="5" width="4" height="14" rx="1" fill="#d97706"/><rect x="14" y="5" width="4" height="14" rx="1" fill="#d97706"/></svg>';
var SVG_PLAY = '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><polygon points="7 4 20 12 7 20" fill="#1d4ed8"/></svg>';
var PR_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M6 9V3h12v6M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8" rx="1"/></svg>';

function $(id){ return document.getElementById(id); }
function qsa(sel, root){ return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
function esc(s){ return String(s == null ? "" : s).replace(/[&<>"']/g,
  function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }

async function api(path, opts){
  opts = opts || {};
  var h = Object.assign({"X-AdvPrint-Token": TOKEN}, opts.headers || {});
  if (opts.body) h["Content-Type"] = "application/json";
  var r = await fetch(BASE + path, { method: opts.method || "GET",
    headers: h, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (r.status === 401) { showTokenCard(true); throw new Error("auth"); }
  var d = {};
  try { d = await r.json(); } catch(_){}
  /* v3.2.5 BUG FIX 5: surface the server's REAL message. The old line
     showed a blind "HTTP 200" whenever the hub answered {ok:false} with
     only a message field (e.g. policy-install on a locked-down PC) - the
     user could never see WHY it failed. error > message > status now. */
  if (!r.ok || d.ok === false)
    throw new Error(d.error || d.message || ("HTTP " + r.status));
  return d;
}

/* ---------- token card (injected - invisible in the design until needed) ---------- */
function showTokenCard(show){
  var c = $("tokenCard");
  if (!c) {
    c = document.createElement("div");
    c.id = "tokenCard";
    c.style.cssText = "display:none;position:fixed;inset:0;z-index:60;background:rgba(15,23,42,.45);" +
      "align-items:center;justify-content:center";
    c.innerHTML = '<div class="card" style="width:430px;max-width:92vw;background:#fff">' +
      '<div class="card-h">\uD83D\uDD11 Hub token needed</div><div class="card-b">' +
      '<div class="note" style="margin-bottom:10px">This console talks to the hub with your private ' +
      'token. Paste it once - it is remembered in this browser.</div>' +
      '<input class="inp mono" id="tokInp" style="width:100%" placeholder="paste the hub token">' +
      '<div style="display:flex;gap:8px;margin-top:10px">' +
      '<button class="btn blue" id="bTokGo">Connect</button>' +
      '<span class="mono" style="font-size:10.5px;color:var(--muted);align-self:center">' +
      'python advprint.py token</span></div></div></div>';
    document.body.appendChild(c);
    $("bTokGo").addEventListener("click", async function(){
      TOKEN = $("tokInp").value.trim();
      if (!TOKEN) return;
      localStorage.setItem("advprintHubToken", TOKEN);
      var u = new URL(location.href); u.searchParams.set("token", TOKEN);
      history.replaceState(null, "", u);
      showTokenCard(false); boot();
    });
    $("tokInp").addEventListener("keydown", function(e){
      if (e.key === "Enter") $("bTokGo").click(); });
  }
  c.style.display = show ? "flex" : "none";
  if (show && $("tokInp")) { $("tokInp").value = TOKEN || ""; }
}

/* ---------- offline card (injected) ---------- */
function showOffline(show){
  var c = $("offlineCard");
  if (!c) {
    c = document.createElement("div");
    c.id = "offlineCard";
    c.style.cssText = "display:none;position:fixed;left:50%;top:76px;transform:translateX(-50%);" +
      "z-index:55;background:#fef3c7;border:1px solid #fcd34d;color:#92400e;border-radius:10px;" +
      "padding:10px 16px;font-size:12.5px;font-weight:600;box-shadow:0 8px 22px rgba(0,0,0,.12)";
    c.innerHTML = "\u26A0 Hub offline - retrying every 3 s \u2026";
    document.body.appendChild(c);
  }
  c.style.display = show ? "block" : "none";
}

/* ---------- toasts ---------- */
function toast(msg, type){
  var box = $("toasts");
  var t = document.createElement("div");
  t.className = "toast " + (type || "");
  t.innerHTML = msg;
  box.appendChild(t);
  while (box.children.length > 4) box.removeChild(box.firstChild);
  setTimeout(function(){ t.style.transition = "opacity .3s"; t.style.opacity = "0";
    setTimeout(function(){ if (t.parentNode) t.remove(); }, 320); }, 2800);
}

/* ---------- tabs (design behaviour + live load hooks) ---------- */
function showTab(name){
  qsa(".panel").forEach(function(p){ p.classList.remove("active"); });
  var el = $("p-" + name);
  if (el) el.classList.add("active");
  qsa(".sb-item").forEach(function(i){
    i.classList.toggle("active", i.dataset.tab === name); });
  var c = document.querySelector(".content");
  if (c) c.scrollTop = 0;
  if (name === "logs") loadLogs();
  if (name === "dropzone") loadDropzone();
  if (name === "connections") loadConnections();
  if (name === "hub") refreshHubPanel();
  if (name === "audit") renderAudit(auditRows);
  if (name === "rules") renderRules();
}
qsa("[data-tab]").forEach(function(el){
  el.addEventListener("click", function(){ showTab(el.dataset.tab); });
});
(function(){
  var m = location.hash.match(/tab=([a-z]+)/);
  if (m) showTab(m[1]);
})();

/* ---------- menubar dropdowns (design behaviour) ---------- */
function closeMenus(){ qsa(".menu.open").forEach(function(m){ m.classList.remove("open"); }); }
qsa(".menubar .menu").forEach(function(m){
  m.querySelector(".menu-label").addEventListener("click", function(e){
    e.stopPropagation();
    var was = m.classList.contains("open");
    closeMenus();
    if (!was) m.classList.add("open");
  });
  m.addEventListener("mouseenter", function(){
    if (document.querySelector(".menu.open") && !m.classList.contains("open")){
      closeMenus(); m.classList.add("open");
    }
  });
});
document.addEventListener("click", function(e){
  if (!e.target.closest(".menubar")) closeMenus();
});

/* ---------- modals (design behaviour) ---------- */
function openModal(id){ $(id).classList.add("show"); }
function closeModal(){
  qsa(".modal-back.show").forEach(function(m){ m.classList.remove("show"); });
}
qsa(".modal-back").forEach(function(back){
  back.addEventListener("click", function(e){
    if (e.target === back || e.target.closest("[data-close]")) closeModal();
  });
});
/* v3.2.6: the docs modal "Full guide page" button - the ONLY path to
   the classic /docs page, kept for deep links and printing the guide */
(function docsOldWire(){
  var b = $("docs-lnk-old");
  if (b) b.onclick = function(){
    closeModal();
    window.open(BASE + "/docs?token=" + encodeURIComponent(TOKEN), "_blank");
  };
})();

/* ---------- filter chips (queue/history/logs) ---------- */
qsa(".filters, .p-head .right").forEach(function(group){
  qsa(".fchip", group).forEach(function(ch){
    ch.addEventListener("click", function(){
      qsa(".fchip", group).forEach(function(x){ x.classList.remove("on"); });
      ch.classList.add("on");
      if (ch.closest(".filters") && ch.closest("#p-queue")) {
        var txt = ch.textContent.replace(/\s*\d+\s*$/, "").trim().toLowerCase();
        jobFilter = { all: "", printing: "printing", queued: "queued",
          held: "held", completed: "printed", saved: "saved", failed: "failed" }[txt] || "";
        renderJobs(lastJobs);
      }
      if (ch.closest("#p-logs")) { logLevelFilter = ch.textContent.trim().toUpperCase(); loadLogs(); }
    });
  });
});
var logLevelFilter = "ALL";

/* ---------- printer destination radios ---------- */
qsa("#p-printers .radio").forEach(function(r){
  r.addEventListener("click", function(){
    qsa("#p-printers .radio").forEach(function(x){ x.classList.remove("on"); });
    r.classList.add("on");
  });
});

/* ---------- copy ---------- */
function copyText(t, btn){
  function done(){ if (btn){ var o = btn.textContent;
    btn.textContent = "OK \u2713";
    setTimeout(function(){ btn.textContent = o; }, 900); } }
  if (navigator.clipboard) navigator.clipboard.writeText(t).then(done, done);
  else { var ta = document.createElement("textarea");
    ta.value = t; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch(_){} document.body.removeChild(ta); done(); }
}
function copyTxt(t){ copyText(t); }

/* ---------- QR codes (REAL SVGs served by the hub /qr) ---------- */
var QR_KINDS = {
  hub:    { title: "AdvPrint Pro \u2014 hub console (THE ONE UI)",
            note: "Open on any PC or phone \u2014 the same console, zero install. The token is embedded, so the link works until you rotate it." },
  send:   { title: "Send portal \u2014 print from phones",
            note: "Scan with the phone camera \u2192 the send page opens \u2192 paste text or upload a PDF \u2192 it prints here. No app, no account." },
  invite: { title: "Invite \u2014 connect another PC",
            note: "Open on the other PC \u2192 it fills in hub URL + token itself and appears under Connections. Works across the LAN only." },
  ipp:    { title: "IPP printer URL",
            /* v3.2.6 BUG FIX 5: the QR ENCODES the http:// URL (phone
               browsers cannot open ipp:// - they Google-search it); the
               display + Copy below stay ipp:// for printer setup. */
            note: "The QR contains the http:// printer URL - scanning opens it in any phone or PC browser (ipp:// would just trigger a Google search). The Copy button keeps the standard ipp:// URL that Windows, macOS and CUPS expect when ADDING the printer." }
};
/* v3.2.9 BUG 3: EVERY device gets ITS OWN hub ip:port. The old lanBase()
   always used BOOT.lan_ip (the hub PC's own default-route address, e.g. a
   VPN 10.x range) so every LAN PC saw the SAME possibly unreachable URL.
   Priority now:
     1. the address THIS browser actually used (location.hostname) when
        it is a real LAN address - that one is reachable by definition
     2. self_host from the hub boot JSON (the Host header of the request)
     3. the hub's best private interface IP (BOOT.lan_ip / lan_ips list)
     4. fallbacks as before */
function isLoopHost(h){
  h = String(h || "").toLowerCase();
  return !h || h === "localhost" || h === "::1" ||
    h === "127.0.0.1" || h.indexOf("127.") === 0 ||
    h.indexOf("::ffff:127.") === 0;
}
function hubIp(){
  var lh = location.hostname || "";
  if (!isLoopHost(lh)) return lh;
  if (BOOT.self_host && !isLoopHost(BOOT.self_host)) return BOOT.self_host;
  var list = (BOOT.lan_ips || []).filter(function(x){ return !isLoopHost(x); });
  if (list.length) return list[0];
  return BOOT.lan_ip || lh || "127.0.0.1";
}
/* v3.3.0 BUG 2: an IPv6 host literal needs square brackets inside a URL
   ("http://[fe80::1]:9235") - hubIp() returns the bare address. */
function hubHost(h){
  h = String(h || "");
  return (h.indexOf(":") >= 0) ? "[" + h + "]" : h;
}
function hubPort(){
  if (!isLoopHost(location.hostname || "") && location.port) return location.port;
  return BOOT.self_port || BOOT.port || location.port || "9235";
}
function lanBase(){
  return "http://" + hubHost(hubIp()) + ":" + hubPort();
}
function ippUrl(){
  /* v3.2.1 r2: the STANDARD printer URL (ipp scheme) - the form
     Windows "IPP device", macOS, iOS AirPrint and CUPS expect. */
  return lanBase().replace(/^http:/, "ipp:") + "/ipp/print";
}
function shareUrl(kind){
  if (kind === "ipp") return lanBase() + "/ipp/print";
  if (kind === "invite") return lanBase() + "/connect?t=" + encodeURIComponent(TOKEN) +
    "&n=" + encodeURIComponent(BOOT.host || "AdvPrint");
  return lanBase() + "/?token=" + encodeURIComponent(TOKEN);
}
function qrImgEl(kind){
  var img = document.createElement("img");
  img.alt = kind + " QR";
  img.style.cssText = "width:100%;height:100%;display:block";
  img.src = BASE + "/qr?kind=" + kind + "&token=" + encodeURIComponent(TOKEN);
  return img;
}
/* draw the three inline tiles on load */
qsa("[data-qr-draw]").forEach(function(box){
  box.innerHTML = "";
  box.appendChild(qrImgEl(box.dataset.qrDraw));
});
/* open the enlarge modal */
function openQR(kind){
  var d = QR_KINDS[kind]; if (!d) return;
  $("qr-title").textContent = d.title;
  var box = $("qr-box"); box.innerHTML = ""; box.appendChild(qrImgEl(kind));
  $("qr-url").textContent = (kind === "ipp") ? ippUrl() : shareUrl(kind);
  $("qr-note").textContent = (kind === "ipp")
    ? d.note + "  QR code contains: " + lanBase() +
      "/ipp/print  \u00b7  printer-add URL (copy): " + ippUrl()
    : d.note;
  $("qr-copy").onclick = function(){
    var u = (kind === "ipp") ? ippUrl() : shareUrl(kind);
    copyText(u); toast("Link copied \u2014 " + u, "ok"); };
  openModal("qrmodal");
}
document.addEventListener("click", function(e){
  var el = e.target.closest("[data-qr]");
  if (el) openQR(el.dataset.qr);
});
document.addEventListener("click", function(e){
  var op = e.target.closest("[data-open]");
  if (op) {
    /* v3.2.6 BUG FIX 2: the hub now returns the BARE queue slug in
       ipp_path - the old code prepended /ipp/print a second time and
       opened /ipp/print/ipp/print/<printer>. Empty slug (IPP printer
       mode off) lands on the general /ipp/print page. */
    var slug = op.dataset.open || "";
    window.open(BASE + "/ipp/print" + (slug ? "/" + slug : "") +
      "?token=" + encodeURIComponent(TOKEN), "_blank");
  }
});

/* ---------- status chips ---------- */
var ST_CHIP = {
  printed:["ok","PRINTED"], printing:["info","PRINTING"], queued:["gray","QUEUED"],
  held:["warn","HELD"], scheduled:["warn","SCHEDULED"], failed:["err","FAILED"],
  dead:["err","DEAD"], canceled:["gray","CANCELED"], saved:["ok","SAVED"],
  forwarded:["info","FORWARDED"], offline:["err","OFFLINE"], ready:["ok","READY"],
  done:["ok","DONE"]
};
function chip(st){
  var c = ST_CHIP[st] || ["gray", (st || "?").toUpperCase()];
  return '<span class="chip ' + c[0] + '"><span class="d"></span>' + c[1] + "</span>";
}
function kindChip(kind){
  var k = String(kind || "").toUpperCase();
  var cls = k === "PDF" ? "info" : k === "ZPL" ? "purple" :
            (k === "XPS" || k === "DOC") ? "gray" : "info";
  return '<span class="chip ' + cls + '">' + (k || "JOB") + "</span>";
}
function prog(st, pct){
  var cls = st === "printed" || st === "saved" || st === "done" || st === "ready" ? "done"
          : (st === "failed" || st === "dead") ? "fail" : "";
  var w = cls === "" ? Math.max(6, pct == null ? 0 : Math.min(100, pct)) : 100;
  return '<div class="prog ' + cls + '"><i style="width:' + w + '%"></i></div>';
}
function jobPct(j){
  if (j.status === "printing") return j.pages_total ? (j.pages_done || 0) * 100 / j.pages_total : 45;
  return 0;
}
function jobKind(j){
  var t = (j.title || "").toLowerCase();
  if (/\.(pdf)\b/.test(t) || j.kind === "pdf") return "PDF";
  if (/\.(zpl)\b/.test(t) || j.kind === "zpl") return "ZPL";
  if (/\.(oxps|xps)\b/.test(t)) return "XPS";
  if (/\.(docx?|pptx?|xlsx?)\b/.test(t)) return "DOC";
  if (j.kind) return String(j.kind).toUpperCase();
  return "PDF";
}

/* ============================================================
   RENDERERS - structure-bound to the frozen rev-4 markup
   ============================================================ */

/* ---- frame: titlebar / menubar right / address bar / statusbar / sidebar ---- */
function setCnt(tab, txt, cls){
  var it = document.querySelector('.sb-item[data-tab="' + tab + '"]');
  if (!it) return;
  var c = it.querySelector(".cnt");
  if (!c) { c = document.createElement("span"); c.className = "cnt"; it.appendChild(c); }
  c.textContent = txt;
  c.className = "cnt" + (cls ? " " + cls : "");
}
function renderFrame(h){
  var t = document.querySelector(".titlebar .t-main small");
  if (t) t.textContent = " \u00b7 All-in-One Console v" + (h.version || BOOT.version || "?") +
    " \u00b7 " + (h.host || BOOT.host || "PC") +
    (IS_CENTER ? " \u00b7 CENTER PC UI" : " \u00b7 THE ONE UI");
  var mr = document.querySelector(".m-right");
  if (mr) mr.innerHTML = "<b>AdvPrint Pro Printing Hub</b> \u00b7 " +
    esc(BASE.replace(/^http:\/\//, "")) + " \u00b7 token auth ON";
  var ab = document.querySelector(".addrbar .url");
  if (ab) ab.textContent = BASE + "/ui \u2014 AdvPrint Printing Hub \u00b7 ALL-IN-ONE" +
    (IS_CENTER ? " \u00b7 CENTER PC UI" : "");
  var lk = document.querySelector(".addrbar .lock");
  if (lk) lk.innerHTML = "\uD83D\uDD12 token ok";
  var sb = qsa(".statusbar .sb-pane");
  if (sb.length >= 10) {
    sb[0].innerHTML = '<span class="dot"></span> Hub Running';
    sb[1].textContent = (BOOT.lan_ip ? BOOT.lan_ip + ":" : "") + (BOOT.port || "9235");
    var real = printersCache.filter(function(p){ return !p.is_group; });
    var ok = real.filter(function(p){ return p.status === "ready"; }).length;
    sb[2].innerHTML = "Printers <b>" + real.length + "</b> \u00b7 Ready <b>" + ok + "</b>";
    sb[3].innerHTML = "Queue <b>" + qsa("#p-queue table.tbl tr").filter(function(tr){
      return tr.querySelector("td"); }).length + "</b>";
    sb[4].innerHTML = "History <b>" + (lastJobs.length) + "</b>";
    sb[5].innerHTML = "LAN <b>" + (cfgCache.share_lan ? "ON" : "OFF") + "</b>";
    sb[6].innerHTML = "DropZone <b>" + (cfgCache.drop_enabled ? "ON" : "OFF") + "</b>";
    sb[8].textContent = hubStartTime ? "Uptime " + fmtUptime(hubStartTime) : "Uptime \u2014";
    sb[9].innerHTML = "<b>Printing Hub v" + (h.version || BOOT.version || "?") + "</b> \u00b7 Bit Dream IT";
  }
  /* v3.2.3: live toolbar status chips (LAN / IPP) + Pause/Resume label */
  var cLan = $("chipLan");
  if (cLan) {
    cLan.textContent = "LAN \u2014 " + (cfgCache.share_lan ? "ON" : "OFF");
    cLan.className = "chip " + (cfgCache.share_lan ? "ok" : "gray");
  }
  var cIpp = $("chipIpp");
  if (cIpp) {
    var ippOn = cfgCache.ipp_printer !== false;
    cIpp.textContent = "IPP \u2014 " + (ippOn ? "READY" : "OFF");
    cIpp.className = "chip " + (ippOn ? "ok" : "gray");
  }
  var tbP = $("tbPause");
  if (tbP) {
    var lbl = tbP.querySelector("span:last-child");
    if (lbl) lbl.textContent = pausedState ? "Resume Queue" : "Pause Queue";
  }
  /* sidebar counters */
  var pend = lastJobs.filter(function(j){
    return j.status === "queued" || j.status === "printing" || j.status === "held"; }).length;
  setCnt("queue", pend);
  setCnt("history", lastJobs.length);
  var rl = printersCache.filter(function(p){ return !p.is_group; });
  setCnt("printers", rl.length);
  setCnt("lan", cfgCache.share_lan ? "ON" : "OFF", cfgCache.share_lan ? "grn" : "");
  setCnt("dropzone", dzCount != null ? dzCount : 0);
  setCnt("rules", (cfgCache.rules_mirror || []).length);
}
function fmtUptime(start){
  var s = Math.max(0, Math.floor((Date.now() - start) / 1000));
  var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  function p2(n){ return (n < 10 ? "0" : "") + n; }
  return p2(h) + ":" + p2(m) + ":" + p2(s % 60);
}

/* ---- dashboard ---- */
function renderStats(h, st, q, pr){
  var stats = qsa("#p-dashboard .stats .stat");
  var real = (pr.printers || []).filter(function(p){ return !p.is_group; });
  var ok = real.filter(function(p){ return p.status === "ready"; }).length;
  if (stats.length >= 5) {
    stats[0].querySelector(".v").textContent = st.jobs_today != null ? st.jobs_today : "0";
    stats[1].querySelector(".v").textContent = st.success_rate != null ? st.success_rate + "%" : "\u2014";
    stats[2].querySelector(".v").textContent = q.pending + (q.held ? " (+" + q.held + ")" : "");
    stats[3].querySelector(".d").textContent = (real.length - ok) ? (real.length - ok) + " offline" : "all ready";
    stats[3].querySelector(".v").textContent = ok + "/" + real.length;
    stats[4].querySelector(".v").textContent = "v" + (h.version || BOOT.version || "?");
  }
  /* quick actions + glance card are wired in bindButtons; live kv below */
  var glance = qsa("#p-dashboard .kv .k");
  glance.forEach(function(k){
    var key = k.textContent.trim().toLowerCase();
    var v = k.nextElementSibling;
    if (!v) return;
    if (key.indexOf("service") >= 0 || key.indexOf("engine") >= 0)
      v.innerHTML = "Running " + chip("printed").replace("PRINTED", "HEALTHY");
    else if (key.indexOf("listen") >= 0 || key.indexOf("address") >= 0)
      v.textContent = BASE.replace(/^http:\/\//, "");
    else if (key.indexOf("lan") >= 0)
      v.innerHTML = cfgCache.share_lan
        ? "ON \u2014 <span class='mono'>" + esc(lanBase()) + "</span>" : "OFF (127.0.0.1 only)";
    else if (key.indexOf("token") >= 0)
      v.textContent = TOKEN ? TOKEN.slice(0, 4) + "\u2026" + TOKEN.slice(-4) : "(none)";
    else if (key.indexOf("mode") >= 0)
      v.textContent = (cfgCache.instant_auto_queue === false) ? "instant print" : "queue mode";
    else if (key.indexOf("ipp") >= 0 || key.indexOf("mdns") >= 0)
      v.textContent = cfgCache.ipp_mdns ? "ON \u2014 printers announce themselves" : "OFF";
  });
}
/* ---- v3.2.1 r2 LAN tab: fill the lrows with REAL values (the
   approved markup ships with design-demo values; the hub replaces
   them live - including the STANDARD ipp:// printer URL) ---- */
function renderLanRows(){
  /* v3.2.2: fill every IPP URL / IP on the panel from the LIVE hub
     v3.2.9 BUG 3: all URLs are built per DEVICE (hubIp()/hubPort() -
     the address THIS browser reached the hub with), and the panel
     lists EVERY interface IP of the hub as one-click chips so any
     PC/phone can pick its own reachable ip:port. */
  var ipEl = function(id, val){ var e = $(id); if (e) e.textContent = val; };
  ipEl("ippUrlIpp", ippUrl());
  ipEl("ippUrlHttp", lanBase() + "/ipp/print");
  ipEl("ippGuideWin", lanBase() + "/ipp/print");
  ipEl("ippGuideMacHost", hubIp() + ":" + (hubPort() || 9235));
  ipEl("ippGuideAndroid", hubIp());
  ipEl("ippGuideAndroid631", "http://" + hubIp() + ":631/ipp/print");
  ipEl("ippGuideRawIp", hubIp());
  /* v3.2.9 BUG 3 + v3.3.0 BUG 2: every hub interface IP as a copyable
     chip - IPv4 AND IPv6 now - plus the static "LAN PC hub URL" input
     follows this device's URL too */
  var ipChips = $("hubIpList");
  if (ipChips) {
    var seen = {}, ips = [];
    (BOOT.lan_ips || []).concat(BOOT.lan_ips6 || [])
      .concat([BOOT.lan_ip || ""]).forEach(function(x){
      if (x && !seen[x] && !isLoopHost(x)) { seen[x] = 1; ips.push(x); }
    });
    if (!ips.length) ips = [hubIp()];
    ipChips.innerHTML = ips.map(function(x){
      var v6 = String(x).indexOf(":") >= 0;
      var disp = v6 ? "[" + x + "]" : x;
      var mine = x === hubIp() ? " <span class='chip ok'>THIS DEVICE</span>" : "";
      return "<button class='btn small' data-cp=\"http://" + esc(disp) + ":" +
        esc(String(hubPort() || 9235)) + "\" style='margin:2px 6px 2px 0'>" +
        esc(disp) + ":" + esc(String(hubPort() || 9235)) + "</button>" + mine;
    }).join(" ");
  }
  /* v3.3.2 BUG 4 (the "it redirects to my own IP" report): the LAN PC
     hub URL input is NEVER auto-filled with this PC's address any more -
     the old line overwrote whatever the user typed for the OTHER PC with
     lanBase() on every poll, so Connect always saw the SELF URL. The
     saved pairing now restores the OTHER PC's URL through loadLanPeer()
     below, and the token field stays empty (the token lives in
     config.json and is never rendered back). */
  /* discovery + standard-port chips (hub /health: ipp_mdns_up, ipp_std) */
  function setChip(rowId, ok, onTxt, offTxt, lvTxt){
    var row = $(rowId); if (!row) return;
    var c = row.querySelector(".chip"), lv = row.querySelector(".lv");
    if (c) { c.textContent = ok ? onTxt : offTxt;
      c.className = "chip " + (ok ? "ok" : "warn"); }
    if (lv && lvTxt) lv.textContent = lvTxt;
  }
  var mdnsUp = !!(window._lastHealth && window._lastHealth.ipp_mdns_up);
  var std = (window._lastHealth && window._lastHealth.ipp_std) || {};
  setChip("row-mdns", mdnsUp, "ON AIR", "OFF",
    mdnsUp ? ("Bonjour/_ipp._tcp broadcasting \u2014 the printer appears by itself (advprint@" +
      hubIp() + ".local)")
           : (cfgCache.ipp_mdns === false ? "discovery off in Hub settings (ipp_mdns)"
              : "starts when LAN sharing / IP Printer mode is ON"));
  /* v3.3.0 BUG 2: the chip shows the REAL bound sockets (IPv4 + IPv6) */
  var stdA = (std && std.addrs) || [];
  setChip("row-ipp631", !!std.up, "LISTENING", "OFF",
    std.up ? ("http://" + hubHost(hubIp()) + ":" + (std.port || 631) +
      "/ipp/print \u2014 IPv4 + IPv6 on every interface" +
      (stdA.length ? " (" + stdA.join(", ") + ")" : "") +
      " \u2014 Android manual add and printer defaults work")
           : (std.err || "standard port off (needs admin on macOS/Linux, or ipp_standard_port: 0)"));
  var rows = qsa("#p-lan .lrow");
  rows.forEach(function(r){
    var kEl = r.querySelector(".lk") || {};
    var k = (kEl.textContent || "").replace(/\s+/g, " ").trim();
    var v = r.querySelector(".lv");
    var t4 = TOKEN ? TOKEN.slice(0, 4) + "\u2026" + TOKEN.slice(-4) : "";
    if (k.indexOf("LAN sharing") === 0) {
      var cLan = r.querySelector(".chip");
      if (cLan) { cLan.textContent = cfgCache.share_lan ? "ON" : "OFF";
        cLan.className = "chip " + (cfgCache.share_lan ? "ok" : "gray"); }
      if (v) v.textContent = lanBase() +
        (cfgCache.share_lan ? "" : "  (LAN sharing is OFF)");
    }
    else if (k.indexOf("Send portal") === 0 && v)
      v.textContent = lanBase() + "/send?t=" + t4;
    else if (k.indexOf("Connect another PC") === 0 && v)
      v.textContent = lanBase() + "/connect?t=" + t4 + "\u2026";
    else if (k.indexOf("IP Printer mode") === 0) {
      var c0 = r.querySelector(".chip");
      if (c0) { c0.textContent = cfgCache.ipp_printer === false ? "OFF" : "ACTIVE";
        c0.className = "chip " + (cfgCache.ipp_printer === false ? "gray" : "info"); }
    } else if (k.indexOf("Network printer (IPP)") === 0) {
      /* v3.2.6: the chip + toggle follow the SAME ipp_printer key as
         the IP Printer mode row - two views of one switch. */
      var c2 = r.querySelector(".chip");
      if (c2) { c2.textContent = cfgCache.ipp_printer === false ? "OFF" : "READY";
        c2.className = "chip " + (cfgCache.ipp_printer === false ? "gray" : "ok"); }
      if (v) {
        v.innerHTML = "";
        var b = document.createElement("b");
        b.className = "mono"; b.textContent = ippUrl();
        v.appendChild(b);
        var s = document.createElement("span");
        s.style.cssText = "display:block;font-size:10.5px;color:#94a3b8;margin-top:2px";
        s.textContent = "standard printer URL \u00b7 Windows add-by-URL form: " +
          lanBase() + "/ipp/print";
        v.appendChild(s);
      }
    } else if (k.indexOf("RAW printer port") === 0 && v) {
      /* v3.3.0 BUG 2: show the REAL bound sockets (IPv4 + IPv6 on every
         interface) instead of one lan_ip guess */
      var rw = (window._lastHealth && window._lastHealth.raw_addrs) || [];
      v.textContent = rw.length ? rw.join("  \u00b7  ") : (hubHost(hubIp()) + ":9100");
    } else if (k.indexOf("Printer status hold") === 0) {
      var c1 = r.querySelector(".chip");
      if (c1) { c1.textContent = cfgCache.hold_offline === false ? "OFF" : "ON";
        c1.className = "chip " + (cfgCache.hold_offline === false ? "gray" : "ok"); }
    }
    if (!r.dataset.lanBound) {
      r.dataset.lanBound = "1";
      var dis = qsa("button.btn", r).filter(function(b){
        return b.textContent.trim() === "Disable" ||
               b.textContent.trim() === "Enable"; })[0];
      if (dis) {
        var row;
        if (k.indexOf("LAN sharing") === 0) row = ["share_lan", "LAN sharing"];
        else if (k.indexOf("IP Printer mode") === 0) row = ["ipp_printer", "IP Printer mode"];
        else if (k.indexOf("Network printer (IPP)") === 0) row = ["ipp_printer", "IPP printer"];
        else if (k.indexOf("Printer status hold") === 0) row = ["hold_offline", "Printer status hold"];
        if (row) dis.onclick = function(){
          var on = cfgCache[row[0]] === false;
          var patch = {}; patch[row[0]] = on;
          api("/config", { method: "POST", body: patch })
            .then(function(){ toast(row[1] + (on ? " ON" : " OFF \u2014 click again to re-enable"), on ? "ok" : "warn"); poll(); })
            .catch(function(e){ toast(e.message, "err"); });
        };
      }
    }
    /* keep the row button label honest (Disable vs Enable) */
    var dis2 = qsa("button.btn", r).filter(function(b){
      return b.textContent.trim() === "Disable" ||
             b.textContent.trim() === "Enable"; })[0];
    if (dis2) {
      var key = k.indexOf("LAN sharing") === 0 ? "share_lan"
        : k.indexOf("IP Printer mode") === 0 ? "ipp_printer"
        : k.indexOf("Network printer (IPP)") === 0 ? "ipp_printer"
        : k.indexOf("Printer status hold") === 0 ? "hold_offline" : null;
      if (key) dis2.textContent = cfgCache[key] === false ? "Enable" : "Disable";
    }
  });
  /* v3.2.6 BUG FIX 3 + NEW FEATURE: the PANEL HEADER buttons - the top
     Disable/Enable (LAN sharing) was never wired, and the extra IPP
     Enable/Disable toggle lives right next to it. */
  var lanTop = $("lanTopToggle"), ippTop = $("ippTopToggle");
  if (lanTop) {
    lanTop.textContent = cfgCache.share_lan === false ? "Enable" : "Disable";
    lanTop.onclick = function(){
      var on = cfgCache.share_lan === false;
      var patch = { share_lan: on };
      /* the hub auto-enables IPP with LAN sharing; mirror it in the
         request so the toggle state is never ambiguous */
      if (on && cfgCache.ipp_printer === false) patch.ipp_printer = true;
      api("/config", { method: "POST", body: patch })
        .then(function(){
          toast("LAN sharing " + (on ? "ON \u2014 IPP printer joined it" : "OFF \u2014 only this PC reaches the hub"),
                on ? "ok" : "warn");
          poll(); })
        .catch(function(e){ toast(e.message, "err"); });
    };
  }
  if (ippTop) {
    var ippOn = cfgCache.ipp_printer !== false;
    ippTop.textContent = "IPP: " + (ippOn ? "ON" : "OFF");
    ippTop.className = "btn" + (ippOn ? " blue" : "");
    ippTop.onclick = function(){
      var on = cfgCache.ipp_printer === false;
      api("/config", { method: "POST", body: { ipp_printer: on } })
        .then(function(){
          toast("IPP printer " + (on ? "ON \u2014 this PC accepts IPP print jobs" : "OFF"), on ? "ok" : "warn");
          poll(); })
        .catch(function(e){ toast(e.message, "err"); });
    };
  }
  renderAcl();
}

/* ---- v3.2.3 ALLOWED IPS - who may reach this hub ----
   Default ["*"] = the whole LAN (as always). The moment real entries are
   added ONLY those may connect: console, send portal, API, IPP 9235 +
   631 mirror, RAW 9100. 127.0.0.1 (the hub PC) is always allowed - the
   hub NEVER locks its owner out. */
function aclListNow(){
  return (cfgCache.allowed_ips && cfgCache.allowed_ips.length)
    ? cfgCache.allowed_ips : ["*"];
}
function saveAcl(list){
  if (!list || !list.length) list = ["*"];   /* never lock the owner out */
  api("/config", { method: "POST", body: { allowed_ips: list } })
    .then(function(){
      toast(list.indexOf("*") >= 0
        ? "Allowed IPs = * \u2014 the whole LAN may reach the hub"
        : "Allowed IPs saved \u2014 only " + list.length + " entr" +
          (list.length > 1 ? "ies" : "y") + " may reach the hub", "ok");
      poll(); })
    .catch(function(e){ toast(e.message, "err"); });
}
function renderAcl(){
  var mode = $("aclMode");
  var list = aclListNow();
  var restricted = list.indexOf("*") < 0;
  if (mode) {
    mode.textContent = restricted
      ? ("RESTRICTED \u2014 " + list.length + " IP" + (list.length > 1 ? "s" : ""))
      : "ALL LAN (*)";
    mode.className = "chip " + (restricted ? "warn" : "ok");
  }
  var box = $("aclList");
  if (!box) return;
  box.innerHTML = "";
  list.forEach(function(ip){
    if (ip === "*") {
      var t = document.createElement("span");
      t.className = "mono";
      t.style.cssText = "background:#f1f5f9;border:1px solid #e2e8f0;" +
        "border-radius:4px;padding:3px 10px;font-size:11.5px;color:var(--blue-deep)";
      t.textContent = "*  \u2014 every device on this LAN may connect";
      box.appendChild(t);
      return;
    }
    var chip = document.createElement("span");
    chip.className = "chip info";
    chip.style.cssText = "display:inline-flex;align-items:center;gap:6px;" +
      "padding:3px 6px 3px 10px;font-size:11.5px";
    var s = document.createElement("span");
    s.className = "mono"; s.textContent = ip;
    var x = document.createElement("button");
    x.textContent = "\u2715"; x.title = "remove " + ip;
    x.style.cssText = "height:18px;padding:0 7px;font-size:10.5px;" +
      "background:#fee2e2;border:1px solid #fecaca;color:#b91c1c;" +
      "border-radius:5px;cursor:pointer";
    x.onclick = function(){
      saveAcl(list.filter(function(v){ return v !== ip; })); };
    chip.appendChild(s); chip.appendChild(x);
    box.appendChild(chip);
  });
}
(function aclWire(){
  function addOne(){
    var inp = $("aclInput"); if (!inp) return;
    var v = (inp.value || "").trim();
    if (!v) { toast("Type an IP first \u2014 e.g. 10.26.94.100", "warn"); return; }
    if (v === "*") { inp.value = ""; saveAcl(["*"]); return; }
    var cur = aclListNow().filter(function(x){ return x !== "*"; });
    if (cur.indexOf(v) >= 0) { toast(v + " is already on the list", "warn"); return; }
    cur.push(v);
    inp.value = "";
    saveAcl(cur);
  }
  var add = $("aclAdd");
  if (add) add.onclick = addOne;
  var all = $("aclAllowAll");
  if (all) all.onclick = function(){ saveAcl(["*"]); };
  var inp = $("aclInput");
  if (inp) inp.addEventListener("keydown", function(e){
    if (e.key === "Enter") { e.preventDefault(); addOne(); } });
})();

/* ---- v3.3.2 SHARE SEND MODE - the LAN PC card ----
   The card reads the PERSISTED pairing (GET /peer/status) on every
   poll, so a page reload / hub restart always shows the real state -
   the v3.3.1 bug was a transient JS flag that vanished on reload and
   made the Share Send switch demand "Connect the LAN PC first" even
   for a paired PC. Connect/Clear talk to /peer/pair + /peer/unpair;
   NOTHING navigates the browser anywhere, so there is no way to end
   up redirected at this PC's own IP. */
var lanPeerState = null;
var _shareSendPending = false;   /* v3.3.3: a Share Send flip is in
   flight - poll/render skips mirroring the switch until it lands, so
   the 3 s poll can never visually revert what the user just clicked */

function renderLanPeer(st){
  st = st || {};
  lanPeerState = st;
  var chipEl = $("lanPcChip"), line = $("lanPcStatus");
  var url = $("lanPcHubUrl"), tok = $("lanPcToken"), sw = $("shareSendSw");
  if (st.configured) {
    if (url && document.activeElement !== url) url.value = st.url || "";
    if (tok && document.activeElement !== tok) tok.placeholder =
      "saved \u2014 leave blank to keep";
  } else {
    if (url && document.activeElement !== url) url.value = "";
    if (tok && document.activeElement !== tok) tok.placeholder =
      "the other PC's hub token";
  }
  if (sw && !_shareSendPending) sw.classList.toggle("on", !!st.share_send);
  var p = st.peer;
  if (!st.configured) {
    if (chipEl) { chipEl.className = "chip gray";
      chipEl.innerHTML = '<span class="d"></span>OFFLINE'; }
    if (line) line.innerHTML = "Enter the <b>OTHER PC's</b> hub URL and token, then Connect. " +
      "The pairing is saved on this PC \u2014 it survives page reloads and hub restarts.";
    return;
  }
  if (p && p.alive) {
    if (chipEl) { chipEl.className = "chip ok";
      chipEl.innerHTML = '<span class="d"></span>CONNECTED'; }
    if (line) line.innerHTML =
      "peer v" + esc(p.version || "?") + (p.peer_host ? " \u00b7 " + esc(p.peer_host) : "") +
      " \u00b7 LAN sharing <b>" + (p.share_lan ? "ON" : "OFF") + "</b> on that PC" +
      " \u00b7 IP printer <b>" + (p.ipp_printer ? "ON" : "OFF") + "</b> there" +
      (p.printers && p.printers.length
        ? " \u00b7 " + p.printers.length + " printer" + (p.printers.length > 1 ? "s" : "")
        : "") +
      " \u00b7 Share Send " + (st.share_send
        ? "<b>ON \u2014 every job goes to that PC</b>" : "OFF (prints on the Self PC)");
  } else {
    if (chipEl) { chipEl.className = "chip err";
      chipEl.innerHTML = '<span class="d"></span>OFFLINE'; }
    if (line) line.innerHTML =
      "paired with " + esc(st.url || "?") + " \u2014 the PC did NOT answer" +
      (p && p.error ? " (" + esc(p.error) + ")" : "") +
      ". Check that AdvPrint Pro runs THERE, LAN sharing is ON and the firewall allows port 9235.";
  }
}

function loadLanPeer(){
  api("/peer/status").then(function(st){
    renderLanPeer(st);
    renderRemotePrinters(st);
  }).catch(function(){ /* keep the last known state */ });
}
/* alias used by the Connect/Clear handlers */
function loadRemoteState(){ loadLanPeer(); }
function renderRecent(jobs){
  var tbl = document.querySelector("#p-dashboard table.tbl");
  if (!tbl) return;
  var tmpl = null, th = tbl.querySelector("tr");
  qsa("tr", tbl).forEach(function(tr){ if (tr.querySelector("td")) { if (!tmpl) tmpl = tr.cloneNode(true); tr.remove(); } });
  (jobs || []).slice(0, 6).forEach(function(j){
    var tr = tmpl.cloneNode(true);
    var td = tr.querySelectorAll("td");
    td[0].textContent = "#" + j.id;
    td[1].textContent = j.title || "job";
    td[2].textContent = j.printer || "default";
    td[3].textContent = j.pages_total || 1;
    td[4].innerHTML = chip(j.status);
    td[5].innerHTML = prog(j.status, jobPct(j));
    td[6].textContent = (j.created_at || "").replace("T", " ").slice(11, 19);
    tbl.appendChild(tr);
  });
  if (!(jobs || []).length) {
    var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
    td[0].textContent = "\u2014"; td[1].textContent = "no jobs yet";
    for (var i = 2; i < td.length; i++) td[i].innerHTML = "&nbsp;";
    tbl.appendChild(tr);
  }
}

/* ---- printers ---- */
function renderPrinters(list){
  printersCache = list || [];
  var real = printersCache.filter(function(p){ return !p.is_group; });
  var grid = document.querySelector("#p-printers .pgrid");
  if (grid) {
    var tmpl = grid.querySelector(".pcard");
    if (tmpl && !grid.dataset.tmpl) grid.dataset.tmpl = "1";
    var t0 = tmpl ? tmpl.cloneNode(true) : null;
    grid.innerHTML = "";
    real.forEach(function(p){
      if (!t0) return;
      var c = t0.cloneNode(true);
      var badge = c.querySelector(".badge");
      if (p.is_default && !badge) { badge = document.createElement("span");
        badge.className = "badge"; badge.textContent = "DEFAULT"; c.insertBefore(badge, c.firstChild); }
      if (!p.is_default && badge) badge.remove();
      c.classList.toggle("off", p.status !== "ready");
      c.querySelector(".nm").textContent = p.name;
      c.querySelector(".mdl").textContent = (p.is_default ? "OS default \u00b7 " : "") +
        (p.model || p.driver || (p.ipp_queue ? "IPP queue" : "system printer"));
      var st = c.querySelector(".st");
      st.innerHTML = "<span>State <b>" + esc(p.status || "unknown") + "</b></span>" +
        "<span>Jobs <b>" + (p.jobs != null ? p.jobs : 0) + "</b></span>" +
        "<span>" + chip(p.status === "ready" ? "ready" : p.status) + "</span>";
      var url = c.querySelector(".url");
      if (p.ipp_queue) { url.innerHTML = ""; url.appendChild(document.createTextNode(p.ipp_queue));
        var b = document.createElement("button"); b.className = "cp"; b.textContent = "COPY";
        b.setAttribute("data-cp", p.ipp_queue); url.appendChild(b); }
      else { url.style.display = "none"; }
      var ops = c.querySelector(".ops");
      ops.innerHTML = '<button class="btn blue" data-ptest="' + esc(p.name) + '">Test Page</button>' +
        '<button class="btn" data-setdef="' + esc(p.name) + '"' + (p.is_default ? " disabled" : "") +
        '>Set Default</button><button class="btn" data-open="' +
        esc(p.ipp_path || "") + '">Details</button>';
      grid.appendChild(c);
    });
    if (!real.length && t0) {
      var c = t0.cloneNode(true);
      c.querySelector(".nm").textContent = "No printers found";
      c.querySelector(".mdl").textContent = "re-scan or check the OS printer list";
      var st0 = c.querySelector(".st");
      if (st0) st0.innerHTML = "<span>State <b>unknown</b></span>";
      var u0 = c.querySelector(".url"); if (u0) u0.style.display = "none";
      var o0 = c.querySelector(".ops"); if (o0) o0.innerHTML = "";
      grid.appendChild(c);
    }
  }
  /* default printer select + offline chip */
  var sel = document.querySelector("#p-printers select.inp");
  if (sel) {
    var cur = sel.value;
    sel.innerHTML = real.map(function(p){
      return "<option" + (p.is_default ? " selected" : "") + ">" + esc(p.name) + "</option>";
    }).join("") || "<option>OS default</option>";
    if (cur && real.some(function(p){ return p.name === cur; })) sel.value = cur;
  }
  var chipOff = document.querySelector("#p-printers .card-b .chip.err, #p-printers .card-b .chip.warn");
  var off = real.filter(function(p){ return p.status !== "ready"; });
  if (chipOff && off.length) {
    chipOff.className = "chip err"; chipOff.style.display = "";
    chipOff.innerHTML = '<span class="d"></span>' + esc(off[0].name + " " + off[0].status) +
      (off.length > 1 ? " \u00b7 +" + (off.length - 1) + " more" : "");
  } else if (chipOff) chipOff.style.display = "none";
}

/* ---- v3.3.2 REMOTE DEVICES in the printers list ----
   The "Show other PCs (LAN / IPP)" switch (show_remote_printers) appends
   the PAIRED LAN PC's devices as extra cards: every device shows its
   own IP source badge (LAN PC / IPP) and the ipp:// URL the OTHER PC
   answers on, so printers "from a different IP" are visible right here
   and can be test-printed through the peer hub. Set Default is
   disabled on remote cards (an OS default belongs to that other PC). */
function renderRemotePrinters(st){
  st = st || lanPeerState || {};
  var grid = document.querySelector("#p-printers .pgrid");
  if (!grid) return;
  qsa("#p-printers .pcard[data-remote]").forEach(function(c){ c.remove(); });
  if (!cfgCache.show_remote_printers) return;
  var p = st.peer;
  if (!st.configured || !p || !p.alive) return;
  var t0 = grid.querySelector(".pcard");
  if (!t0) return;
  (p.printers || []).forEach(function(pr){
    var c = t0.cloneNode(true);
    c.setAttribute("data-remote", "1");
    var badge = c.querySelector(".badge");
    if (badge) badge.remove();
    var b = document.createElement("span");
    b.className = "badge"; b.style.background = "#e0e7ff"; b.style.color = "#3730a3";
    b.textContent = "LAN PC \u00b7 IPP";
    c.insertBefore(b, c.firstChild);
    c.classList.toggle("off", pr.status !== "ready");
    c.querySelector(".nm").textContent = pr.name;
    c.querySelector(".mdl").textContent =
      "on the other PC (" + (st.url || "").replace(/^https?:\/\//, "") + ")" +
      (pr.is_default ? " \u00b7 ITS OS default" : "");
    var stEl = c.querySelector(".st");
    if (stEl) stEl.innerHTML = "<span>State <b>" + esc(pr.status || "unknown") +
      "</b></span><span>Source <b>LAN PC</b></span><span>" +
      chip(pr.status === "ready" ? "ready" : pr.status) + "</span>";
    var url = c.querySelector(".url");
    if (url) { url.innerHTML = ""; url.appendChild(document.createTextNode(pr.ipp || ""));
      var cp = document.createElement("button"); cp.className = "cp"; cp.textContent = "COPY";
      cp.setAttribute("data-cp", pr.ipp || ""); url.appendChild(cp);
      url.style.display = ""; }
    var ops = c.querySelector(".ops");
    if (ops) ops.innerHTML =
      '<button class="btn blue" data-prtest="' + esc(pr.name) + '">Test Page</button>' +
      '<button class="btn" disabled style="opacity:.5" title="Set Default belongs to the PC that owns this printer">Set Default</button>' +
      '<button class="btn" data-prdet="' + esc(pr.name) + '">Details</button>';
    grid.appendChild(c);
  });
  /* wire the remote-card buttons (delegated - the grid re-renders) */
  qsa("#p-printers .pcard[data-remote] button").forEach(function(btn){
    var tp = btn.getAttribute("data-prtest");
    if (tp && !btn.dataset.bound) {
      btn.dataset.bound = "1";
      btn.addEventListener("click", function(){
        toast("Sending a test page to " + tp + " on the LAN PC ...");
        /* v3.3.2: the HUB relays the test page to the peer (server side,
           no cross-origin browser call, no token in the page) */
        api("/peer/test-page", { method: "POST", body: { printer: tp } })
          .then(function(j){
            toast("Test page queued on the LAN PC (job " +
                  (j.job_id || "?") + ")", "ok"); })
          .catch(function(e){ toast("Test page failed: " + e.message, "err"); });
      });
    }
    var det = btn.getAttribute("data-prdet");
    if (det && !btn.dataset.bound) {
      btn.dataset.bound = "1";
      btn.addEventListener("click", function(){
        var pr = null;
        ((lanPeerState && lanPeerState.peer && lanPeerState.peer.printers) || [])
          .forEach(function(x){ if (x.name === det) pr = x; });
        if (!pr) return;
        toast(det + " \u2014 " + (pr.ipp || "") + " \u2014 lives on " +
              ((lanPeerState && lanPeerState.url) || "the other PC"), "ok");
      });
    }
  });
}


/* ---- queue + history ---- */
var lastJobs = [];
function renderJobs(jobs){
  jobs = jobs || [];
  lastJobs = jobs;
  /* KPI row */
  var kc = qsa("#p-queue .kpi .kc");
  if (kc.length >= 4) {
    var printing = jobs.filter(function(j){ return j.status === "printing"; }).length;
    var queued = jobs.filter(function(j){ return j.status === "queued"; }).length;
    var held = jobs.filter(function(j){ return j.status === "held"; }).length;
    var doneToday = jobs.filter(function(j){
      return ["printed", "saved", "done"].indexOf(j.status) >= 0; }).length;
    kc[0].querySelector("b").textContent = printing;
    kc[1].querySelector("b").textContent = queued;
    kc[2].querySelector("b").textContent = held;
    kc[3].querySelector("b").textContent = doneToday;
    kc[0].querySelector(".chip").innerHTML = (pausedState
      ? '<span class="d"></span>QUEUE PAUSED' : '<span class="d"></span>QUEUE ON').replace('<span class="d"></span>QUEUE', '<span class="d"></span>QUEUE');
    kc[0].querySelector(".chip").className = "chip " + (pausedState ? "warn" : "ok");
  }
  /* filter chips counts */
  var fc = qsa("#p-queue .filters .fchip");
  if (fc.length >= 7) {
    var c = function(st){ return jobs.filter(function(j){ return j.status === st; }).length; };
    var done = jobs.filter(function(j){ return ["printed", "done"].indexOf(j.status) >= 0; }).length;
    fc[0].querySelector(".n").textContent = jobs.length;
    fc[1].querySelector(".n").textContent = c("printing");
    fc[2].querySelector(".n").textContent = c("queued");
    fc[3].querySelector(".n").textContent = c("held");
    fc[4].querySelector(".n").textContent = done;
    fc[5].querySelector(".n").textContent = c("saved");
    fc[6].querySelector(".n").textContent = jobs.filter(function(j){
      return ["failed", "dead"].indexOf(j.status) >= 0; }).length;
  }
  /* queue table - v3.2.5 BUG FIX 3: checkbox column (like History),
     selection survives the poll, per-row Cancel stays, and a header
     select-all box ticks every VISIBLE row */
  var tbl = document.querySelector("#p-queue table.tbl");
  if (tbl) {
    var tmpl = null;
    qsa("tr", tbl).forEach(function(tr){ if (tr.querySelector("td")) { if (!tmpl) tmpl = tr.cloneNode(true); tr.remove(); } });
    var list = jobs.filter(function(j){ return !jobFilter || j.status === jobFilter; });
    list.slice(0, 60).forEach(function(j){
      var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
      var qc = td[0].querySelector('input[type="checkbox"]');
      if (qc) { qc.checked = !!queueSel[j.id]; qc.setAttribute("data-qid", j.id); }
      td[1].textContent = "#" + j.id;
      td[2].textContent = j.title || "job";
      td[3].textContent = j.printer || "default";
      td[4].innerHTML = kindChip(jobKind(j));
      td[5].innerHTML = chip(j.status);
      td[6].innerHTML = prog(j.status, jobPct(j));
      var act = j.status === "queued" ? '<button class="btn small danger" data-cancel="' + j.id + '">Cancel</button>'
        : j.status === "held" ? '<button class="btn small" data-pnow="' + j.id + '">\u26A1 Release</button>'
        : j.status === "printing" ? '<button class="btn small danger" data-cancel="' + j.id + '">Cancel</button>'
        : ["failed", "dead"].indexOf(j.status) >= 0 ? '<button class="btn small" data-retry="' + j.id + '">\u21BB Retry</button>'
        : '<button class="btn small" data-reprint="' + j.id + '">\u21BB Reprint</button>';
      td[7].innerHTML = act;
      tbl.appendChild(tr);
    });
    if (!list.length && tmpl) {
      var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
      td[1].textContent = "\u2014"; td[2].textContent = "no jobs" +
        (jobFilter ? " with status " + jobFilter : "");
      for (var i = 3; i < td.length; i++) td[i].innerHTML = "&nbsp;";
      var e0 = td[0].querySelector('input[type="checkbox"]'); if (e0) e0.checked = false;
      tbl.appendChild(tr);
    }
    var running = jobs.filter(function(j){ return j.status === "printing"; })[0];
    var r = document.querySelector("#p-queue .card-h .r");
    if (r) r.textContent = running ? "hub #" + running.id + " in progress" : "hub idle";
    syncSelBar();
  }
  /* history table */
  var ht = document.querySelector("#p-history table.tbl");
  if (ht) {
    var htmpl = null;
    qsa("tr", ht).forEach(function(tr){ if (tr.querySelector("td")) { if (!htmpl) htmpl = tr.cloneNode(true); tr.remove(); } });
    var q2 = (document.querySelector("#p-history input.inp") || {}).value || "";
    var stSel = document.querySelectorAll("#p-history select.inp")[0];
    var stv = stSel ? stSel.value.toLowerCase() : "";
    var limSel = document.querySelectorAll("#p-history select.inp")[1];
    var lim = limSel ? parseInt((limSel.value.match(/\d+/) || [100])[0], 10) : 100;
    var hlist = jobs.filter(function(j){
      if (stv && stv !== "all statuses") {
        var map = { printed: ["printed", "done"], queued: ["queued"], "saved (file)": ["saved"],
          failed: ["failed", "dead"], canceled: ["canceled"] };
        var want = map[stv] || null;
        if (want && want.indexOf(j.status) < 0) return false;
      }
      if (q2) {
        var hay = (j.title || "") + " " + (j.printer || "") + " #" + j.id;
        if (hay.toLowerCase().indexOf(q2.toLowerCase()) < 0) return false;
      }
      return true;
    });
    hlist.slice(0, lim).forEach(function(j){
      var tr = htmpl.cloneNode(true), td = tr.querySelectorAll("td");
      /* v3.2.5 BUG FIX 2: ticked rows STAY ticked across the 3 s poll */
      td[0].firstElementChild.checked = !!histSel[j.id];
      td[0].firstElementChild.setAttribute("data-hid", j.id);
      td[1].textContent = "#" + j.id;
      td[2].textContent = (j.created_at || "").replace("T", " ").slice(11, 19);
      td[3].textContent = j.title || "job";
      td[4].textContent = j.printer || "\u2014";
      td[5].innerHTML = kindChip(jobKind(j));
      td[6].innerHTML = chip(j.status);
      var canStill = ["queued", "held", "printing"].indexOf(j.status) >= 0;
      td[7].innerHTML =
        (canStill ? '<button class="btn small danger" data-cancel="' + j.id + '">Cancel</button>'
                  : '<button class="btn small" data-reprint="' + j.id + '"' +
                    (j.file_path || ["printed", "saved"].indexOf(j.status) >= 0 ? "" : " disabled") +
                    '>\u21BB Reprint</button>');
      ht.appendChild(tr);
    });
    if (!hlist.length && htmpl) {
      var tr = htmpl.cloneNode(true), td = tr.querySelectorAll("td");
      td[1].textContent = "\u2014"; td[3].textContent = "no history yet";
      for (var i2 = 0; i2 < td.length; i2++) if (i2 !== 1 && i2 !== 3) td[i2].innerHTML = "&nbsp;";
      var h0 = td[0].querySelector('input[type="checkbox"]'); if (h0) h0.checked = false;
      ht.appendChild(tr);
    }
    var hr = document.querySelector("#p-history .card-h .r");
    if (hr) hr.textContent = "last " + Math.min(hlist.length, lim) + " of " + jobs.length +
      " \u00b7 reprint needs the original file on disk (Hub \u2192 Keep printed files)";
    syncSelBar();
  }
}

/* ---------- v3.2.5 BUG FIXES 2 + 3: SELECTION TOOLBAR ENGINE ----------
   History AND Queue now behave the same way:
     - ticked rows stay ticked across the 3 s auto-refresh
     - a live counter ("3 selected") sits next to the bulk buttons
     - Reprint selected / Cancel selected act on the ticked rows
     - Clear selected just unticks (it never touches the jobs)
   Queue gets the full set too: per-row Cancel stays, a header
   select-all box ticks every visible row, Cancel selected cancels
   every ticked job that can still be canceled. */
function selIds(sel){
  return Object.keys(sel).filter(function(k){ return sel[k]; });
}
function syncSelBar(){
  histSelCount = selIds(histSel).length;
  queueSelCount = selIds(queueSel).length;
  var h = $("histSelInfo"), q = $("queueSelInfo");
  if (h) h.textContent = histSelCount ? histSelCount + " selected" : "nothing ticked";
  if (q) q.textContent = queueSelCount ? queueSelCount + " selected" : "nothing ticked";
  var ha = $("histCancelSel"), qc = $("queueCancelSel");
  if (ha) ha.disabled = !histSelCount;
  if (qc) qc.disabled = !queueSelCount;
  /* header select-all mirrors the visible rows (queue + history) */
  qsa('#p-queue table.tbl input[type="checkbox"][data-qall]').forEach(function(a){
    var rows = qsa('#p-queue table.tbl input[type="checkbox"][data-qid]');
    if (!rows.length) { a.checked = false; a.indeterminate = false; return; }
    var n = rows.filter(function(c){ return c.checked; }).length;
    a.checked = n === rows.length;
    a.indeterminate = n > 0 && n < rows.length;
  });
  qsa('#p-history table.tbl input[type="checkbox"][data-hall]').forEach(function(a){
    var rows = qsa('#p-history table.tbl input[type="checkbox"][data-hid]');
    if (!rows.length) { a.checked = false; a.indeterminate = false; return; }
    var n = rows.filter(function(c){ return c.checked; }).length;
    a.checked = n === rows.length;
    a.indeterminate = n > 0 && n < rows.length;
  });
}
function bindSelections(){
  document.addEventListener("change", function(ev){
    var c = ev.target;
    if (!c || !c.type || c.type !== "checkbox") return;
    if (c.hasAttribute && c.hasAttribute("data-hid")) {
      histSel[c.getAttribute("data-hid")] = c.checked;
      syncSelBar(); return;
    }
    if (c.hasAttribute && c.hasAttribute("data-qid")) {
      queueSel[c.getAttribute("data-qid")] = c.checked;
      syncSelBar(); return;
    }
    if (c.hasAttribute && c.hasAttribute("data-qall")) {
      /* select-all: tick every visible queue row (and remember them) */
      qsa('#p-queue table.tbl input[type="checkbox"][data-qid]').forEach(function(r){
        r.checked = c.checked;
        queueSel[r.getAttribute("data-qid")] = c.checked;
      });
      syncSelBar(); return;
    }
    if (c.hasAttribute && c.hasAttribute("data-hall")) {
      /* history select-all: tick every visible history row */
      qsa('#p-history table.tbl input[type="checkbox"][data-hid]').forEach(function(r){
        r.checked = c.checked;
        histSel[r.getAttribute("data-hid")] = c.checked;
      });
      syncSelBar(); return;
    }
  });
}
function clearSelection(scope){
  if (scope === "history") {
    histSel = {};
    qsa('#p-history table.tbl input[type="checkbox"]').forEach(function(c){ c.checked = false; });
    toast("Selection cleared - the jobs themselves are untouched", "ok");
  } else {
    queueSel = {};
    qsa('#p-queue table.tbl input[type="checkbox"]').forEach(function(c){
      if (!c.hasAttribute("data-qall")) c.checked = false; });
    toast("Selection cleared - the jobs themselves are untouched", "ok");
  }
  syncSelBar();
}
async function cancelSelected(scope){
  var sel = scope === "history" ? histSel : queueSel;
  var ids = selIds(sel);
  if (!ids.length) return toast("Tick some rows first", "warn");
  var done = 0;
  for (var i = 0; i < ids.length; i++) {
    try { await api("/jobs/" + ids[i] + "/cancel", { method: "POST" }); done++; }
    catch (e) { /* finished jobs cannot be canceled - count only wins */ }
  }
  if (scope === "history") histSel = {}; else queueSel = {};
  toast(done + " job(s) canceled (" + (ids.length - done) +
        " already finished)", done ? "ok" : "warn");
  poll();
}

/* ---- audit ---- */
function renderAudit(rows){
  rows = rows || [];
  auditRows = rows;
  var tbl = document.querySelector("#p-audit table.tbl");
  if (!tbl) return;
  var tmpl = null;
  qsa("tr", tbl).forEach(function(tr){ if (tr.querySelector("td")) { if (!tmpl) tmpl = tr.cloneNode(true); tr.remove(); } });
  rows.slice(0, 60).forEach(function(a){
    var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
    td[0].textContent = (a.created_at || "").replace("T", " ").slice(11, 19);
    td[1].innerHTML = '<span class="chip info">' + esc(a.actor || a.ip || "client") + "</span>";
    td[2].textContent = a.action || "";
    td[3].textContent = a.details || a.printer || a.site || "";
    td[4].innerHTML = chip(/fail|error|denied/i.test(a.details || "") ? "failed" : "done")
      .replace("FAILED", "OK").replace("DONE", "OK");
    tbl.appendChild(tr);
  });
  if (!rows.length && tmpl) {
    var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
    td[0].textContent = "\u2014"; td[2].textContent = "no audit rows yet";
    for (var i = 1; i < td.length; i++) if (i !== 2) td[i].innerHTML = "&nbsp;";
    tbl.appendChild(tr);
  }
}

/* ---- rules (central rule manager) ---- */
var KIND_LABELS = { "": "Any", pdf: "PDF link", web: "Web page", text: "Plain text / stream", url: "URL type" };
var ACTION_LABELS = { auto: "Auto (PDF as-is)", web: "Entire web page", sel: "Selected element only",
  raw: "Raw text / ZPL / ESC-POS stream", pdf: "Linked PDF only" };
function renderRules(){
  var rules = cfgCache.rules_mirror || [];
  rulesCache = rules;
  setCnt("rules", rules.length);
  var tbl = document.querySelector("#p-rules table.tbl");
  if (!tbl) return;
  var tmpl = null;
  qsa("tr", tbl).forEach(function(tr){ if (tr.querySelector("td")) { if (!tmpl) tmpl = tr.cloneNode(true); tr.remove(); } });
  rules.forEach(function(r, i){
    var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
    td[0].textContent = "\u2630 " + (i + 1);
    td[1].innerHTML = "<b>" + esc(r.name || "(unnamed)") + "</b>";
    td[2].textContent = r.pattern || "*";
    td[3].innerHTML = '<span class="chip info">' + (r.match === "content" ? "CONTENT" : "URL") + "</span>";
    td[4].textContent = r.match === "content" ? (r.content || "(any content)") : "\u2014";
    td[5].textContent = KIND_LABELS[r.kind] || r.kind || "Any";
    td[6].innerHTML = "<b>" + esc(r.printer || "OS default") + "</b>";
    td[7].textContent = ACTION_LABELS[r.action] || r.action || "Auto (PDF as-is)";
    td[8].textContent = r.copies || 1;
    td[9].textContent = r.paper || "default";
    td[10].innerHTML = '<span class="switch' + (r.on !== false ? " on" : "") + '" data-rtoggle="' + i + '"></span>';
    td[11].innerHTML = '<span class="switch' + (r.auto !== false ? " on" : "") + '" data-rauto="' + i + '"></span>';
    td[12].innerHTML = (r.runs || 0) + " runs" + (r.last_run ? "<br>last " + esc(String(r.last_run).slice(11, 16)) : "");
    td[13].innerHTML = '<button class="btn small blue" data-edit-rule="' + i + '">Edit</button> ' +
      '<button class="btn small danger" data-del-rule="' + i + '">Del</button>';
    tbl.appendChild(tr);
  });
  if (!rules.length && tmpl) {
    var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
    td[1].innerHTML = "<b>no rules yet</b> \u2014 click \u201cNew rule\u201d";
    for (var i = 2; i < td.length; i++) td[i].innerHTML = "&nbsp;";
    tbl.appendChild(tr);
  }
}
/* rule editor (design modal re-*) */
function setSel(el, label, extra){
  if (!el) return;
  var opt = qsa("option", el).filter(function(o){ return o.textContent.trim() === label; })[0];
  if (opt) el.value = opt.value || opt.textContent;
  else if (extra !== undefined) {
    var o = document.createElement("option");
    o.textContent = label; o.selected = true; el.appendChild(o);
  }
}
function getSel(el){ return el ? el.options[el.selectedIndex].textContent.trim() : ""; }
function openRuleEditor(idx){
  var r = (typeof idx === "number" && rulesCache[idx]) ? rulesCache[idx]
    : { name: "", pattern: "*", content: "", kind: "", printer: "", action: "auto",
        copies: 1, paper: "", on: true, auto: true, sched: "Always", prio: rulesCache.length + 1, isNew: true };
  ruleEditIdx = typeof idx === "number" ? idx : -1;
  $("re-title").textContent = r.isNew ? "New rule \u2014 step 1: match by" : "Edit rule \u2014 " + (r.name || "");
  $("re-url").value = r.pattern === "*" ? "" : (r.pattern || "");
  $("re-content").value = r.content || "";
  setSel($("re-type"), KIND_LABELS[r.kind] || "Any");
  var sel = $("re-printer");
  sel.innerHTML = "<option>(OS default printer)</option>" +
    printersCache.filter(function(p){ return !p.is_group; }).map(function(p){
      return "<option" + (r.printer === p.name ? " selected" : "") + ">" + esc(p.name) + "</option>";
    }).join("");
  if (r.printer && !printersCache.some(function(p){ return p.name === r.printer; })) {
    var o = document.createElement("option"); o.textContent = r.printer; o.selected = true; sel.appendChild(o);
  }
  setSel($("re-what"), ACTION_LABELS[r.action] || "Auto (PDF as-is)");
  $("re-copies").value = r.copies || 1;
  setSel($("re-paper"), r.paper || "Driver default");
  var extra = document.querySelectorAll("#rulemodal select.inp2");
  /* anon selects in the modal: [0]=color, [1]=duplex (before re-sched) */
  var sched = $("re-sched");
  setSel(sched, r.sched || "Always");
  $("re-priority").value = r.prio || (idx + 1) || 1;
  $("re-on").classList.toggle("on", r.on !== false);
  $("re-auto").classList.toggle("on", r.auto !== false);
  $("re-delete").style.display = r.isNew ? "none" : "inline-flex";
  $("re-save").onclick = saveRule;
  $("re-delete").onclick = function(){
    closeModal();
    var rules = rulesCache.slice();
    if (ruleEditIdx >= 0) {
      confirmBox("Delete this rule?", rules[ruleEditIdx].name || "rule", async function(){
        rules.splice(ruleEditIdx, 1);
        try { await api("/config", { method: "POST", body: { rules_mirror: rules } });
          toast("Rule deleted", "warn"); poll(); } catch (e) { toast(e.message, "err"); }
      });
    }
  };
  openModal("rulemodal");
}
async function saveRule(){
  var rules = rulesCache.slice();
  var prio = parseInt($("re-priority").value, 10) || ruleEditIdx + 1;
  var r = {
    id: ruleEditIdx >= 0 && rulesCache[ruleEditIdx] ? rulesCache[ruleEditIdx].id : Date.now(),
    name: (ruleEditIdx >= 0 && rulesCache[ruleEditIdx] && rulesCache[ruleEditIdx].name) ||
          ($("re-url").value || "rule " + (rules.length + 1)),
    pattern: $("re-url").value.trim() || "*",
    content: $("re-content").value.trim(),
    match: $("re-content").value.trim() ? "content" :
      ($("re-type").selectedIndex === 3 ? "url" : "url"),
    kind: ["", "pdf", "web", "text"][$("re-type").selectedIndex] !== undefined
      ? ["", "pdf", "web", "text"][$("re-type").selectedIndex] : "",
    printer: $("re-printer").value === "(OS default printer)" ? "" : $("re-printer").value,
    action: ["auto", "web", "sel", "raw", "pdf"][$("re-what").selectedIndex] || "auto",
    copies: Math.max(1, parseInt($("re-copies").value, 10) || 1),
    paper: getSel($("re-paper")) === "Driver default" ? "" : getSel($("re-paper")),
    color: getSel(extraColor()),
    duplex: getSel(extraDuplex()),
    sched: getSel($("re-sched")),
    priority: prio,
    on: $("re-on").classList.contains("on"),
    auto: $("re-auto").classList.contains("on"),
    runs: ruleEditIdx >= 0 && rulesCache[ruleEditIdx] ? (rulesCache[ruleEditIdx].runs || 0) : 0
  };
  function extraColor(){ return document.querySelectorAll("#rulemodal select.inp2")[0]; }
  function extraDuplex(){ return document.querySelectorAll("#rulemodal select.inp2")[1]; }
  r.color = getSel(extraColor()) === "Driver default" ? "" : getSel(extraColor());
  r.duplex = getSel(extraDuplex()) === "Simplex" ? "simplex" :
    getSel(extraDuplex()) === "Long-edge duplex" ? "duplex-long" :
    getSel(extraDuplex()) === "Short-edge duplex" ? "duplex-short" : "";
  if (ruleEditIdx >= 0) rules[ruleEditIdx] = r; else rules.push(r);
  try {
    await api("/config", { method: "POST", body: { rules_mirror: rules } });
    closeModal();
    toast("Rule <b>" + esc(r.name) + "</b> saved \u2014 extensions pick it up automatically", "ok");
    poll();
  } catch (e) { toast("Rule save failed: " + e.message, "err"); }
}

/* ---- dropzone ---- */
var dzCount = 0;
async function loadDropzone(){
  try {
    var d = await api("/dropzone");
    dzCount = d.waiting != null ? d.waiting : (d.files || 0);
    var stats = qsa("#p-dropzone .stats .stat");
    if (stats.length >= 4) {
      stats[0].querySelector(".v").textContent = d.done != null ? d.done : 0;
      stats[1].querySelector(".v").textContent = d.enabled ? 1 : 0;
      stats[2].querySelector(".v").textContent = d.delete ? "del" : "move";
      stats[2].querySelector(".l").textContent = d.delete ? "Delete-After-Print ON" : "Delete-After-Print OFF";
    }
    var inputs = qsa("#p-dropzone input.inp");
    if (inputs[0]) inputs[0].value = d.dir || "";
    if (inputs[1] && !dirtyKeys.dzWatch) inputs[1].value = d.custom_dir || "";
    var sw = document.querySelector("#p-dropzone .switch.on.green") ||
             document.querySelector("#p-dropzone .tgl .switch");
    if (sw) sw.classList.toggle("on", !!d.delete);
    setCnt("dropzone", dzCount);
    /* recent dropzone prints: audit rows mentioning drop */
    var tbl = document.querySelector("#p-dropzone table.tbl");
    if (tbl) {
      var tmpl = null;
      qsa("tr", tbl).forEach(function(tr){ if (tr.querySelector("td")) { if (!tmpl) tmpl = tr.cloneNode(true); tr.remove(); } });
      var rows = auditRows.filter(function(a){
        return /drop/i.test((a.action || "") + " " + (a.details || "")); }).slice(0, 8);
      rows.forEach(function(a){
        var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
        td[0].textContent = (a.details || "").split("\u00b7")[0].trim() || "file";
        td[1].textContent = a.printer || "default";
        td[2].innerHTML = chip(/fail/i.test(a.details || "") ? "failed" : "printed");
        td[3].textContent = (a.created_at || "").slice(11, 19);
        tbl.appendChild(tr);
      });
      if (!rows.length && tmpl) {
        var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
        td[0].textContent = "no DropZone files printed yet";
        for (var i = 1; i < td.length; i++) td[i].innerHTML = "&nbsp;";
        tbl.appendChild(tr);
      }
    }
  } catch (e) { if (e.message !== "auth") toast("DropZone: " + e.message, "err"); }
}

/* ---- connections ---- */
async function loadConnections(){
  try {
    var peers = (await api("/peers")).peers || [];
    /* v3.3.3 DEFENSIVE DEDUPE: the hub already collapses same-URL peer
       entries - this only guards against a stale config.json that was
       written by an older build (the user report: the SAME PC listed
       twice, both rows OFFLINE). First occurrence wins. */
    var seen = {}, uniq = [];
    peers.forEach(function(p){
      var k = (p.url || "").replace(/\/+$/, "").toLowerCase();
      if (k && seen[k]) return;
      seen[k] = 1; uniq.push(p);
    });
    peers = uniq;
    var tbl = document.querySelector("#p-connections table.tbl");
    if (tbl) {
      var tmpl = null;
      qsa("tr", tbl).forEach(function(tr){ if (tr.querySelector("td")) { if (!tmpl) tmpl = tr.cloneNode(true); tr.remove(); } });
      peers.forEach(function(p){
        var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
        /* v3.3.3 OFFLINE-BUG FIX: the server answered /peers with the
           field name `alive`, but this table read `p.up` - undefined on
           EVERY response, so every peer rendered OFFLINE and its Shift
           queue button stayed disabled forever (the "conected hub
           online and on but other pc show offline why" report). Both
           sides now agree: the hub sends `up` AND `alive`. */
        var up = !!(p.up || p.alive);
        /* v3.3.3: show WHICH PC the row is (the server now returns the
           entry's name/label; every row used to read "\u00b7 PC") */
        var who = (p.label || p.name || "PC");
        td[0].textContent = (p.url || "") + " \u00b7 " + who;
        td[1].innerHTML = up ? '<span class="chip ok"><span class="d"></span>ONLINE</span>'
          : '<span class="chip err"><span class="d"></span>OFFLINE</span>';
        td[2].textContent = p.version ? "v" + p.version : "\u2014";
        td[3].innerHTML = '<button class="btn small"' + (up ? "" : " disabled") +
          ' data-shift="' + esc(p.url || "") + '">\u21C6 Shift queue</button>';
        tbl.appendChild(tr);
      });
      if (!peers.length && tmpl) {
        var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
        td[0].textContent = "no peer hubs configured";
        for (var i = 1; i < td.length; i++) td[i].innerHTML = "&nbsp;";
        tbl.appendChild(tr);
      }
    }
    setCnt("connections", peers.length);
    /* v3.3.3 SHIFT TARGET: the input kept its static demo value
       (http://10.26.94.77:9235 - a PC from the design mockup) forever
       and "Shift all waiting" read the SELF PC TOKEN field instead of
       this input (the LAN PC card had shifted the qsa() indexes). The
       input now has id=shiftTarget and is prefilled with the LAN PC's
       URL, else the first ONLINE peer. */
    var stInp = $("shiftTarget");
    if (stInp && document.activeElement !== stInp) {
      var lanUrl = (lanPeerState && lanPeerState.configured && lanPeerState.url) || "";
      var alivePeer = null;
      peers.forEach(function(p){ if (!alivePeer && (p.up || p.alive)) alivePeer = p; });
      var pre = lanUrl || (alivePeer && alivePeer.url) || "";
      if (pre && (!stInp.value || /10\.26\.94\./.test(stInp.value))) stInp.value = pre;
    }
    var chipLan = document.querySelector("#p-connections .card .chip.ok");
  } catch (e) { /* panel stays as-is */ }
  /* website API permission textarea mirrors ext_api_sites */
  var ta = document.querySelector("#p-connections textarea");
  if (ta && !dirtyKeys.sites) {
    var wl = cfgCache.ext_api_sites || [];
    ta.value = (wl.indexOf("*") >= 0) ? "*" : wl.join("\n");
  }
  var siteChip = document.querySelectorAll("#p-connections .card .r .chip");
  if (siteChip.length >= 3) {
    var wl2 = cfgCache.ext_api_sites || [];
    var all = wl2.indexOf("*") >= 0;
    siteChip[2].textContent = all ? "* ALL sites (default)" : wl2.length + " patterns";
    siteChip[2].className = "chip " + (all ? "ok" : wl2.length ? "warn" : "gray");
  }
  var con = qsa("#p-connections .card")[2];
  if (con) {
    var chipc = con.querySelector(".card-h .chip");
    if (chipc) {
      chipc.textContent = cfgCache.share_lan ? "ON" : "OFF";
      chipc.className = "chip " + (cfgCache.share_lan ? "ok" : "gray");
    }
    var mono = con.querySelector(".card-b > .frow .mono, .card-b .frow .mono");
    var nq = printersCache.filter(function(p){ return p.ipp_queue; }).length;
    if (mono) mono.textContent = lanBase() + " \u00b7 " + nq + " per-printer IPP queues announced (mDNS)";
  }
}

/* ---- hub panel ---- */
function refreshHubPanel(){
  var P = "#p-hub";
  var ins = qsa(P + " input.inp.narrow");
  if (ins.length >= 5) {
    if (document.activeElement !== ins[0]) ins[0].value = cfgCache.max_retries != null ? cfgCache.max_retries : 2;
    if (document.activeElement !== ins[1]) ins[1].value = cfgCache.retry_base_seconds != null ? cfgCache.retry_base_seconds : 30;
    if (document.activeElement !== ins[2]) ins[2].value = cfgCache.dedupe_minutes != null ? cfgCache.dedupe_minutes : 5;
    if (document.activeElement !== ins[3]) ins[3].value = cfgCache.max_auth_failures != null ? cfgCache.max_auth_failures : 10;
    if (document.activeElement !== ins[4]) ins[4].value = cfgCache.lockout_minutes != null ? cfgCache.lockout_minutes : 5;
  }
  var origins = qsa(P + ' input.inp[placeholder*="empty = all"]');
  if (origins[0] && !dirtyKeys.origins) origins[0].value = (cfgCache.allowed_origins || []).join(", ");
  var sw = qsa(P + " .tgl .switch");
  /* order: hold, instant, strict header, loopback (readonly), watermark, reason, audit, keep files */
  var map = ["hold_offline", "instant_auto_queue", "token_header_only", null,
             "reprint_watermark", "reprint_reason_required", "audit_enabled", "keep_files"];
  sw.forEach(function(s, i){
    var k = map[i]; if (!k) return;
    if (!dirtyKeys["hub_" + k]) s.classList.toggle("on", !!cfgCache[k]);
  });
  var sel = qsa(P + " select.inp");
  if (sel.length >= 2) {
    setSel(sel[0], cfgCache.thermal_text_engine === "builtin" ? "Built-in only (fast, Latin scripts)"
      : cfgCache.thermal_text_engine === "browser" ? "Browser render (Bangla & complex scripts)"
      : "Auto (recommended)");
    setSel(sel[1], (cfgCache.escpos_codepage || "cp437").toLowerCase());
  }
  var fileDir = qsa(P + ' input.inp.mono[value], ' + P + ' input.inp.mono');
  if (fileDir[0] && !dirtyKeys.fileDir) fileDir[0].value = cfgCache.file_dir || "";
  if (fileDir[1] && !dirtyKeys.sumatra) fileDir[1].value = cfgCache.sumatra_path || "";
}

/* ---- extension panel ---- */
function renderExt(audit){
  var tkv = qsa("#p-extension .kv .v");
  if (tkv[0]) tkv[0].textContent = TOKEN ? TOKEN.slice(0, 6) + "\u2026" + TOKEN.slice(-6) : "(none)";
  /* paired browsers from audit actors */
  var tbl = document.querySelector("#p-extension table.tbl");
  if (tbl) {
    var tmpl = null;
    qsa("tr", tbl).forEach(function(tr){ if (tr.querySelector("td")) { if (!tmpl) tmpl = tr.cloneNode(true); tr.remove(); } });
    var seen = {}, rows = [];
    (audit || []).forEach(function(a){
      var actor = a.actor || "";
      if (!actor || actor === "console" || actor === "dashboard") return;
      if (seen[actor]) return;
      seen[actor] = 1;
      rows.push({ who: (BOOT.host || "PC") + " \u00b7 " + actor, at: a.created_at || "" });
    });
    rows.slice(0, 6).forEach(function(r2){
      var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
      td[0].innerHTML = "<b>" + esc(r2.who) + "</b>";
      td[1].textContent = "v" + (BOOT.version || "3.3.3");
      td[2].textContent = r2.at ? r2.at.slice(11, 19) : "\u2014";
      td[3].innerHTML = '<span class="chip ok"><span class="d"></span>PAIRED</span>';
      tbl.appendChild(tr);
    });
    if (!rows.length && tmpl) {
      var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
      td[0].innerHTML = "<b>no browsers paired yet</b>";
      for (var i = 1; i < td.length; i++) td[i].innerHTML = "&nbsp;";
      tbl.appendChild(tr);
    }
  }
  /* silent-install card values */
  var mono = qsa("#p-extension .card-b .mono");
  var flVal = EXT_ID + ";" + BASE + "/extension/updates.xml";
  mono.forEach(function(m2){
    if (/;http|forcelist/i.test(m2.textContent) || m2.textContent.indexOf(";") > 0 && m2.textContent.indexOf("http") > 0)
      m2.textContent = flVal;
    if (/updates\.xml$/.test(m2.textContent) && m2.textContent.indexOf("http") === 0)
      m2.textContent = BASE + "/extension/updates.xml";
  });
  var crxChip = document.querySelector("#p-extension .frow .chip.ok");
  if (crxChip) crxChip.innerHTML = '<span class="d"></span>CRX v' + (BOOT.version || "3.3.3") + " READY";
  /* v3.2.8 STALE-CRX GUARD: ask the hub which package it really
   * serves (/extension/info is open, no token). Older than the hub
   * itself -> Chrome never updates -> browsers keep the old bugs.
   * Show the red banner AND put the REAL served version in the chip
   * (BOOT.version is the hub version, not the package version). */
  fetch(BASE + "/extension/info").then(function(r){ return r.json(); }).then(function(j){
    if (!j) return;
    var warn = document.getElementById("extStaleWarn");
    if (warn && j.stale) {
      warn.style.display = "block";
      var t = document.getElementById("extStaleTxt");
      if (t) t.textContent = "Hub v" + (j.hub_version || BOOT.version || "?") +
        " serves extension v" + (j.version || "?") + " — Chrome only updates when updates.xml shows a HIGHER version, so every paired browser is stuck on the old extension (old bugs included — e.g. the http-page API refusal of v3.2.7). Fix: re-run the Setup, or copy the current AdvPrint-Pro.crx over hub/extension/AdvPrint-Pro.crx — no restart needed.";
    }
    if (j.served && j.version) {
      var chip = document.querySelector("#p-extension .frow .chip.ok");
      if (chip) chip.innerHTML = '<span class="d"></span>CRX v' + j.version + " READY";
    }
  }).catch(function(){});
  setCnt("extension", audit ? audit.filter(function(a){
    return a.actor && a.actor.indexOf("ext") >= 0; }).length : 0);
}

/* ---- debug panel ---- */
async function loadDebugPanel(){
  try {
    var dbg = await api("/debug");
    var tbl = document.querySelector("#p-debug table.tbl");
    if (tbl) {
      var tmpl = null;
      qsa("tr", tbl).forEach(function(tr){ if (tr.querySelector("td")) { if (!tmpl) tmpl = tr.cloneNode(true); tr.remove(); } });
      var probs = dbg.problems || [];
      probs.slice(0, 12).forEach(function(p){
        var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
        td[0].textContent = (p.created_at || "").slice(11, 19) || new Date().toLocaleTimeString();
        td[1].innerHTML = '<span class="chip ' + (p.level === "error" ? "err" : "warn") + '">' +
          esc(p.check || p.level || "hub") + "</span>";
        td[2].textContent = p.what || "";
        td[3].innerHTML = '<button class="btn small" data-tool="diagnose">Diagnose</button>';
        tbl.appendChild(tr);
      });
      if (!probs.length && tmpl) {
        var tr = tmpl.cloneNode(true), td = tr.querySelectorAll("td");
        td[0].textContent = new Date().toLocaleTimeString();
        td[1].innerHTML = '<span class="chip ok"><span class="d"></span>HUB</span>';
        td[2].textContent = "all clear \u2014 worker running, queue healthy";
        td[3].innerHTML = "&nbsp;";
        tbl.appendChild(tr);
      }
    }
    setCnt("debug", (dbg.problems || []).length, (dbg.problems || []).length ? "red" : "");
    var dchip = document.querySelector("#p-debug .p-head .chip.warn");
    if (dchip) {
      dchip.textContent = dbg.debug ? "DEBUG MODE ON" : "DEBUG MODE OFF";
      dchip.className = "chip " + (dbg.debug ? "ok" : "warn");
    }
    /* service check card */
    var st = await api("/tool", { method: "POST", body: { action: "status" } }).catch(function(){ return null; });
    var svcCard = document.querySelector("#p-debug .card-b");
    if (svcCard && st && st.result) {
      var svc = st.result.service || {};
      var name = svcCard.querySelector("b");
      var schip = svcCard.querySelector(".chip");
      if (name) name.textContent = "'AdvPrint'";
      if (schip) {
        schip.className = "chip " + (svc.installed ? (svc.running ? "ok" : "warn") : "gray");
        schip.textContent = svc.installed ? (svc.running ? "RUNNING" : "INSTALLED \u00b7 NOT RUNNING") : "NOT INSTALLED (tray mode)";
      }
    }
  } catch (e) { /* ignore */ }
}

/* ---- logs ---- */
function renderLogs(dbg, jobs, audit){
  var box = document.querySelector("#p-logs .logbox");
  if (!box) return;
  var lines = [];
  (dbg.problems || []).forEach(function(p){
    lines.push(logLine(p.created_at || "", p.level === "warn" ? "W" : p.level === "error" ? "E" : "I",
      esc(p.check || "") + ": " + esc(p.what || "")));
  });
  if (!(dbg.problems || []).length)
    lines.push(logLine("", "I", "hub verdict: <span class=\"hl\">all clear</span> \u2014 worker running, queue healthy"));
  (jobs || []).slice(0, 14).forEach(function(j){
    var lv = ["failed", "dead"].indexOf(j.status) >= 0 ? "E" : j.status === "held" ? "W" : "I";
    lines.push(logLine((j.created_at || "").slice(11, 19), lv,
      "job <span class=\"hl\">#" + j.id + "</span> " + esc(j.title) + " \u2192 " +
      esc(j.printer || "default") + " \u00b7 " + esc(j.status)));
  });
  (audit || []).slice(0, 10).forEach(function(a){
    lines.push(logLine((a.created_at || "").slice(11, 19), "I",
      "audit " + esc(a.action) + " " + esc(a.details || "")));
  });
  var want = logLevelFilter;
  var html = lines.filter(function(l){
    if (want === "ALL") return true;
    if (want === "INFO") return l.indexOf('lv I') >= 0;
    if (want === "WARN") return l.indexOf('lv W') >= 0;
    return l.indexOf('lv E') >= 0;
  }).join("") || '<div><span class="lv I">INFO </span> no activity yet</div>';
  box.innerHTML = html;
  function esc2(s){ return s; }
  function logLine(ts, lv, msg){
    return '<div><span class="ts">' + (ts || new Date().toLocaleTimeString()) + '</span> <span class="lv ' +
      lv + '">' + (lv === "E" ? "ERROR" : lv === "W" ? "WARN " : "INFO ") + "</span> " + msg + "</div>";
  }
}
async function loadLogs(){
  try {
    var dbg = await api("/debug");
    var jobs = (await api("/jobs?limit=30")).jobs || [];
    renderLogs(dbg, jobs, auditRows);
  } catch (e) {
    var box = document.querySelector("#p-logs .logbox");
    if (box && e.message !== "auth") box.innerHTML =
      '<div><span class="lv E">ERROR</span> log load failed: ' + esc(e.message) + "</div>";
  }
}

/* ---- settings panel ---- */
function renderSettings(cfg){
  cfgCache = cfg || {};
  var ins = qsa("#p-settings input.inp");
  if (ins.length >= 2) {
    if (document.activeElement !== ins[0] && !dirtyKeys.port) ins[0].value = BOOT.port || cfgCache.port || 9235;
    if (document.activeElement !== ins[1] && !dirtyKeys.token) ins[1].value = TOKEN || "";
  }
  var sws = qsa("#p-settings .f-row .switch");
  /* order: autostart, minimize, LAN(green), printer hold */
  if (sws.length >= 4) {
    if (!dirtyKeys.autostart) sws[0].classList.toggle("on", !!autoStartState);
    if (!dirtyKeys.minimize) sws[1].classList.toggle("on", true);
    if (!dirtyKeys.lan) sws[2].classList.toggle("on", !!cfgCache.share_lan);
    if (!dirtyKeys.hold) sws[3].classList.toggle("on", cfgCache.hold_offline !== false);
  }
  var days = ins[2];
  if (days && document.activeElement !== days && !dirtyKeys.keepDays)
    days.value = cfgCache.history_days != null ? cfgCache.history_days : 30;
  var sels = qsa("#p-settings select");
  if (sels[0]) setSel(sels[0], (cfgCache.log_level || "INFO").toUpperCase());
  if (sels[1]) setSel(sels[1], "Windows IDM (Blue)");
  var folder = document.querySelector("#p-settings .hint .mono");
  if (folder) folder.textContent = cfgCache.data_dir || "~/.advprint";
  /* LAN hint line */
  var lanHint = qsa("#p-settings .f-row");
  lanHint.forEach(function(row){
    if (/LAN SHARING/i.test(row.textContent)) {
      var span = row.querySelector("span:last-child");
      if (span) span.innerHTML = (cfgCache.share_lan
        ? '<span class="mono">' + esc(lanBase()) + "</span> \u00b7 see LAN tab"
        : "OFF \u2014 only this PC (127.0.0.1) can reach the hub");
    }
  });
  renderRules();
}
var autoStartState = false;

/* ---- about panel ---- */
function renderAbout(h){
  var chipV = document.querySelector("#p-about .chip.ok");
  if (chipV) chipV.textContent = "v" + (h.version || BOOT.version || "?") + " \u00b7 UP TO DATE";
  qsa("#p-about .btn.small").forEach(function(b){
    var t = b.textContent.trim();
    if (t === "GitHub repo") b.onclick = function(){ window.open("https://github.com/bitdreamit/AdvPrint-Pro", "_blank"); };
    if (t === "Releases") b.onclick = function(){ window.open("https://github.com/bitdreamit/AdvPrint-Pro/releases", "_blank"); };
    /* v3.2.6 BUG FIX 6: Docs + Release notes open INSIDE the UI */
    if (t === "Docs") b.onclick = function(){ openDocs(); };
    if (t === "Release notes") b.onclick = function(){ openDocs("d-notes"); };
  });
}

/* ============================================================
   ACTIONS + the 14 tools
   ============================================================ */
function toolOut(lines){
  var box = $("toolOut");
  if (!box) {
    var card = document.querySelector("#p-debug .card:last-of-type .card-b");
    box = document.createElement("pre");
    box.id = "toolOut";
    box.style.cssText = "background:#0f172a;color:#e2e8f0;border-radius:10px;padding:12px 14px;" +
      "font:11.5px/1.65 Consolas,monospace;overflow:auto;max-height:220px;margin:10px 0 0;display:none;white-space:pre-wrap";
    if (card) card.appendChild(box); else document.body.appendChild(box);
  }
  box.style.display = "block";
  box.textContent = (lines || []).join("\n");
}
async function renderUpdate(res){
  toolOut(["GitHub update check",
    "  current:  v" + (res.current || "?"),
    "  latest:   " + (res.latest_tag || "?"),
    res.up_to_date ? "  verdict:  OK - this build is up to date" :
      "  verdict:  an update is available: " + (res.url || ""),
    res.note ? "  " + res.note : ""]);
  toast(res.up_to_date ? "v" + res.current + " is up to date" : "Update available: " + res.latest_tag,
    res.up_to_date ? "ok" : "warn");
}

/* ============================================================
   v3.2.6 BUG FIX 6 - DOCS INSIDE THE ONE UI
   The old Docs buttons opened /docs in a new tab (the "old UI view").
   openDocs() renders the guide in a modal right here instead; the
   full-page /docs stays available via the "Full guide page" button.
   ============================================================ */
function docsHtml(){
  var v = esc(BOOT.version || "3.3.3");
  var ip = esc(BOOT.lan_ip || location.hostname || "127.0.0.1");
  var port = esc(String(BOOT.port || location.port || "9235"));
  var base = "http://" + ip + ":" + port;
  return ''
  + '<style>.docs-body h3{font-size:13px;font-weight:800;color:#1e3a8a;margin:16px 0 6px;'
  + 'padding-bottom:4px;border-bottom:1px solid #e2e8f0}.docs-body h3:first-child{margin-top:0}'
  + '.docs-body p,.docs-body li{font-size:12.5px;line-height:1.65;color:#334155}'
  + '.docs-body ul,.docs-body ol{margin:4px 0 8px 20px}.docs-body code{background:#f1f5f9;border:1px solid #e2e8f0;'
  + 'border-radius:4px;padding:1px 5px;font-size:11.5px;color:#1e40af;word-break:break-all}'
  + '.docs-body .dk{display:inline-block;background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af;'
  + 'border-radius:5px;font-size:10.5px;font-weight:700;padding:1px 8px;margin-right:6px;vertical-align:1px}</style>'
  + '<h3 id="d-quick">1 · Quick start</h3>'
  + '<ol><li>The hub starts with Windows (tray icon near the clock). The console opens at <code>http://127.0.0.1:' + port + '/ui</code>.</li>'
  + '<li>Print anything from Chrome → the job lands in <b>Live Queue</b> and prints on your destination printer.</li>'
  + '<li>Pick the destination in the <b>Printers</b> tab (default printer / any installed printer / an IP printer).</li>'
  + '<li><span class="dk">TEST</span> the chain with <b>Hub → Test print</b> or press <code>Ctrl+T</code>.</li></ol>'
  + '<h3 id="d-install">2 · Install the Chrome/Edge extension</h3>'
  + '<p><b>Easiest — one click policy install (v' + v + '):</b> Console → <b>Extension</b> tab → <b>Install by policy</b>. Chrome, Edge and Brave get the extension silently — no chrome://extensions, no Developer mode. Verify at <code>chrome://policy</code> (Reload policy) — the extension appears within a minute.</p>'
  + '<p><b>Manual:</b> <code>chrome://extensions</code> → enable <i>Developer mode</i> → <b>Load unpacked</b> → pick the <code>extension</code> folder (installed at <code>C:\\Program Files\\AdvPrint Pro\\extension</code>).</p>'
  + '<p>After a token change: open the extension <b>Options</b> and paste the new token — or use the popup’s <b>Fix token</b> banner.</p>'
  + '<h3 id="d-print">3 · Printing — what happens to a job</h3>'
  + '<ul><li>Chrome print preview → the extension captures the PDF → <code>POST /print</code> on this hub → the queue worker prints it on the destination printer.</li>'
  + '<li><b>Queue mode</b> lines jobs up FIFO (held while the printer is offline — release with ⚡); <b>instant mode</b> prints immediately.</li>'
  + '<li><b>History</b> keeps every job — tick rows and Reprint in bulk; <b>Clear ALL history</b> removes finished records, waiting jobs are never touched.</li></ul>'
  + '<h3 id="d-lan">4 · LAN sharing · other PCs · security (v' + v + ')</h3>'
  + '<ul><li><b>The console UI is local-only:</b> settings, history and the queue open only on this PC (loopback or this machine’s own IP). Nobody on the LAN can change your hub settings any more.</li>'
  + '<li><b>LAN PCs and phones keep FULL print access</b> — the send portal, the IPP printer URL, the print API and ports ' + port + ' / 631 / 9100 answer normally, exactly per the <b>Allowed-IPs</b> list (<code>*</code> = whole LAN).</li>'
  + '<li>Opening the share URL from another PC shows a friendly locked page with the print instructions.</li>'
  + '<li>Switching <b>LAN sharing ON also switches the IPP printer ON</b> automatically; the extra <b>IPP: ON/OFF</b> toggle in the panel header controls it independently.</li></ul>'
  + '<h3 id="d-ipp">5 · Add this PC as a network printer (IPP)</h3>'
  + '<ul><li><b>Printer URL:</b> <code>ipp://' + ip + ':' + port + '/ipp/print</code> — or the browser-friendly <code>' + base + '/ipp/print</code>. Per-printer queues: <code>ipp://' + ip + ':' + port + '/ipp/print/&lt;printer&gt;</code>.</li>'
  + '<li><b>Windows 10/11:</b> Settings → Bluetooth &amp; devices → Printers → Add device — the hub appears by itself (AirPrint-style). Or Add manually → IPP device → paste <code>' + base + '/ipp/print</code> → the built-in IPP Class Driver installs it.</li>'
  + '<li><b>macOS:</b> System Settings → Printers — appears in the Bonjour list. <b>iPhone/iPad:</b> Share → Print — appears while on the same Wi-Fi.</li>'
  + '<li><b>Android:</b> Default Print Service finds it automatically; manual add uses the standard port 631 mirror (<code>' + base.replace(':9235', ':631') + '/ipp/print</code>).</li>'
  + '<li><b>QR codes:</b> the IPP QR contains the <code>http://</code> URL (phone browsers cannot open <code>ipp://</code> — they Google-search it). The Copy button keeps the <code>ipp://</code> printer URL.</li></ul>'
  + '<h3 id="d-send">6 · Send portal — print from any phone</h3>'
  + '<p>LAN tab → <b>Copy send URL</b> (<code>' + base + '/send?token=…</code>) → open it on the phone → pick a PDF or paste text → it prints here. No app, no account. QR in the same tab.</p>'
  + '<h3 id="d-security">7 · Tokens &amp; Allowed IPs</h3>'
  + '<ul><li>The hub token protects every print call (<code>?token=</code> or the <code>X-AdvPrint-Token</code> header). Rotate it in the <b>Hub</b> tab — then update it once in the extension options.</li>'
  + '<li><b>Allowed IPs</b> (LAN tab): <code>*</code> opens the hub for the whole LAN; add entries like <code>10.26.94.100</code>, <code>10.26.94.0/24</code> or <code>10.26.*</code> to restrict who can reach it. This PC (127.0.0.1) is always allowed.</li></ul>'
  + '<h3 id="d-trouble">8 · Troubleshooting</h3>'
  + '<ul><li><b>Extension says offline:</b> is the tray icon there? Then check the token (popup → Fix token) and the hub URL (<code>http://127.0.0.1:' + port + '</code>).</li>'
  + '<li><b>Job stuck HELD:</b> the printer reports offline — clear the paper jam, then ⚡ Release (or wait: the queue retries by itself).</li>'
  + '<li><b>LAN PC cannot print:</b> check Allowed-IPs (<code>*</code> or their IP), the Windows firewall rule (LAN tab → Test LAN) and that the token is on their side.</li>'
  + '<li><b>Logs:</b> Debug tab → live hub log + <code>hub.log</code> on disk. The A-to-Z self-test: Tools menu → LIVE TEST.</li></ul>'
  + '<h3 id="d-api">9 · Developer API — print from code (v' + v + ')</h3>'
  + '<p><b>Two doors, one pipeline</b> — a job from JavaScript and a job from curl land in the same queue, History and audit.</p>'
  + '<ul><li><b>In every web page</b> (extension injects <code>window.advprint</code>, every method returns a Promise):</li></ul>'
  + '<code>await window.advprint.status(); await window.advprint.printers(); await window.advprint.printPage({title});'
  + ' await window.advprint.printPdf(url, {title, printer}); await window.advprint.print({title, printer, copies, priority,'
  + ' pages, quality, dpi, duplex, paper_size, profile, queue, run_at, text|html|pdfBase64|pdfUrl, lang});</code>'
  + '<ul><li><b>From any language / any PC on the LAN</b> — POST <code>' + base + '/print</code> with header <code>X-AdvPrint-Token</code> (or ?token=):</li></ul>'
  + '<code>curl -X POST ' + base + '/print -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/json"'
  + ' -d \'{"pdf_base64":"JVBERi0…","title":"Invoice 42","printer":"HP LaserJet Pro","copies":2}\'</code>'
  + '<ul><li><b>Parallel printing:</b> <code>"queue": false</code> prints instantly in its own thread — receipt on the thermal roll +'
  + ' invoice on the laser at the same time; Queue Mode prints one-by-one, <code>priority: 1</code> first. One call per printer = one'
  + ' printer; group names fall back to the first ready member.</li>'
  + '<li><b>Labels:</b> <code>{"text":"^XA…^XZ","lang":"zpl"}</code> goes verbatim to the label printer (ZPL II, latin-1);'
  + ' plain <code>text</code> builds ESC/POS with the markers <code>#big</code>, <code>|center|</code>, <code>|right|</code>,'
  + ' <code>|cut|</code>, <code>|drawer|</code>, <code>|barcode:123|</code>, <code>|qr:text|</code>.</li>'
  + '<li><b>Schedule &amp; control:</b> <code>run_at: "+5m"</code> or ISO datetime · <code>pages: "1-3,5|odd|even"</code> ·'
  + ' <code>quality: "draft|normal|high|600dpi"</code> · <code>destination: "file"</code> archives as PDF ·'
  + ' <code>dedupe: false</code> allows identical repeats · <code>reason</code> lands in the audit trail.</li>'
  + '<li><b>LAN:</b> other PCs print with <code>http://&lt;lan-ip&gt;:' + port + '/print</code> (Allowed-IPs decide; the UI stays'
  + ' local-only). Per-printer IPP queues: <code>ipp://' + ip + ':' + port + '/ipp/print/&lt;printer-slug&gt;</code>.</li>'
  + '<li><b>Full guide with every case:</b> install folder <code>docs/DEVELOPER-API.md</code> — one PC many printers, many PCs one hub,'
  + ' PDF + ZPL at the same time, curl / JS / Python / PHP examples, URL &amp; token map.</li></ul>'
  + '<h3 id="d-notes">Release notes — v' + v + '</h3>'
  + '<ul><li><b>NEW — Developer API release:</b> the print API (window.advprint + POST /print) is documented A-to-Z —'
  + ' every method, every option, every response field, with worked cases: same PC many printers (parallel receipt + invoice),'
  + ' many PCs one hub, PDF + ZPL ^XA labels at the same time, scheduled prints, urgent priority, page ranges + odd/even,'
  + ' n-up, duplex, DPI, profiles, watermark reprints. Ships in THREE places: <code>docs/DEVELOPER-API.md</code>,'
  + ' the /docs page (section 9) and this modal (section 9).</li>'
  + '<li>window.advprint.print() now also passes <code>run_at</code>, <code>queue</code>, <code>dedupe</code>,'
  + ' <code>tray</code> and <code>watermark_text</code> — the extension API and the HTTP API have FULL parity.</li>'
  + '<li>Everything from v3.2.6 stays unchanged: History / Queue clear really cleans; Printer Details no longer doubles the'
  + ' <code>/ipp/print</code> path; LAN panel top switch works, Copy URL carries the token, IPP auto-ON with LAN sharing +'
  + ' independent IPP toggle; IPP QR encodes <code>http://</code> (copy keeps <code>ipp://</code>); the UI stays LOCAL-ONLY'
  + ' (loopback or own IP) while LAN PCs keep full print access per Allowed-IPs; the CLI menu is gone and the tray menu is'
  + ' Dashboard / Restart / Exit.</li></ul>';
}
function openDocs(anchor){
  var box = $("docs-body");
  if (!box) return;
  box.innerHTML = docsHtml();
  openModal("docsmodal");
  if (anchor) {
    var el = box.querySelector("#" + anchor);
    if (el) box.scrollTop = el.offsetTop - 8;
  } else {
    box.scrollTop = 0;
  }
}

var ACTIONS = {
  "poll": function(){ poll(); toast("Refreshed", "ok"); },
  "testprint": async function(){
    try { var r = await api("/testprint");
      toast("Test page queued (job #" + (r.job_id != null ? r.job_id : "?") + ")", "ok"); poll();
    } catch (e) { toast("Test page failed: " + e.message, "err"); } },
  "queue-pause-toggle": async function(){
    try { await api("/queue/" + (pausedState ? "resume" : "pause"), { method: "POST" });
      toast(pausedState ? "Queue RESUMED" : "Queue PAUSED", pausedState ? "ok" : "warn"); poll();
    } catch (e) { toast(e.message, "err"); } },
  "queue-clear": function(){
    /* v3.2.6 BUG FIX 1: clear really CLEANS - waiting jobs are canceled
       AND every finished record is removed, so the list is empty. */
    confirmBox("Clear the whole queue?",
      "Every waiting / held / printing job is canceled AND all finished "
      + "records are removed - the queue AND the history come back clean.",
      async function(){ try { await api("/queue/clear", { method: "POST" });
        toast("Queue cleared - all records removed", "warn"); poll();
      } catch (e) { toast(e.message, "err"); } }); },
  "queue-clear-finished": async function(){
    /* v3.2.6 BUG FIX 1: the old code POSTed /queue/clear {finished:true}
       - a body the hub IGNORED - so 'Clear ALL history' never cleaned.
       It now calls the real history-clear endpoint. */
    try { await api("/history/clear", { method: "POST" });
      toast("Finished history cleared \u2014 waiting jobs untouched", "ok"); poll();
    } catch (e) { toast(e.message, "err"); } },
  "release-held": async function(){
    try {
      var jobs = (await api("/jobs?limit=200")).jobs || [];
      var held = jobs.filter(function(j){ return j.status === "held"; });
      for (var i = 0; i < held.length; i++)
        await api("/jobs/" + held[i].id + "/print-now", { method: "POST" });
      toast(held.length ? held.length + " held job(s) released" : "No held jobs", "ok"); poll();
    } catch (e) { toast(e.message, "err"); } },
  "export-history": function(){
    window.open(BASE + "/export/history.csv?token=" + encodeURIComponent(TOKEN), "_blank");
    toast("history.csv exported", "ok"); },
  "export-audit": function(){
    window.open(BASE + "/export/audit.csv?token=" + encodeURIComponent(TOKEN), "_blank");
    toast("audit.csv exported", "ok"); },
  "refresh-printers": function(){ poll(); toast("Printers rescanned", "ok"); },
  "fw-allow": async function(){
    try { var r = await api("/tool", { method: "POST", body: { action: "fw-allow" } });
      toast(r.message || "Firewall rule requested \u2014 approve the UAC prompt", "ok");
    } catch (e) { toast(e.message, "err"); } },
  "fw-status": async function(){
    try { var r = await api("/lan/selftest");
      toolOut(["LAN self-test", "  URL:   " + r.url, "  result: " + (r.ok ? "PASS - listener answers" : "FAIL"),
               "  note:  " + (r.note || "")]);
      toast("LAN test OK \u2014 hub answered", "ok");
    } catch (e) { toolOut(["LAN self-test FAILED", "  " + e.message]); toast("LAN test failed: " + e.message, "err"); } },
  "copy-hub-url": function(){
    /* v3.2.6 BUG FIX 3/4: the URL carries the token - the old copy was
       a bare http://ip:9235/ui that opened the token error page. */
    var u = lanBase() + "/ui?token=" + encodeURIComponent(TOKEN);
    copyText(u); toast("Console URL copied (token included) \u2014 opens on this PC", "ok"); },
  "copy-send-url": function(){ copyText(lanBase() + "/send?token=" + encodeURIComponent(TOKEN)); toast("Send portal URL copied", "ok"); },
  "copy-invite": function(){ copyText(lanBase() + "/connect?t=" + encodeURIComponent(TOKEN)); toast("Invite link copied", "ok"); },
  "copy-ipp-url": function(){ copyText(ippUrl()); toast("IPP printer URL copied \u2014 " + ippUrl(), "ok"); },
  "copy-ipp-http": function(){ copyText(lanBase() + "/ipp/print"); toast("Windows add-by-URL copied \u2014 " + lanBase() + "/ipp/print", "ok"); },
  "copy-crx": function(){ copyText(BASE + "/extension/AdvPrint-Pro.crx"); toast("CRX URL copied", "ok"); },
  "copy-updates": function(){ copyText(BASE + "/extension/updates.xml"); toast("updates.xml URL copied", "ok"); },
  "copy-policy": function(){ copyText(EXT_ID + ";" + BASE + "/extension/updates.xml");
    toast("Policy value copied \u2014 paste it into ExtensionInstallForcelist", "ok"); },
  "copy-token": function(){ copyText(TOKEN); toast("Token copied", "ok"); },
  "rotate-token": function(){
    confirmBox("Rotate the hub token?", "A NEW token is generated and saved. Re-enter it in the "
      + "extension Options page (and on child PCs) once \u2014 the old token stops working immediately.",
      async function(){ try { var r = await api("/token/rotate", { method: "POST" });
          TOKEN = r.token || TOKEN;
          localStorage.setItem("advprintHubToken", TOKEN);
          var u = new URL(location.href); u.searchParams.set("token", TOKEN);
          history.replaceState(null, "", u);
          toast("Token rotated \u2014 update the extension + child PCs", "warn"); poll();
        } catch (e) { toast(e.message, "err"); } }); },
  "restart": function(){
    confirmBox("Restart the hub?", "Clean relaunch \u2014 printing resumes automatically in a few seconds.",
      async function(){ try { await api("/restart", { method: "POST" });
          toast("Restarting\u2026", "warn"); } catch (e) { toast(e.message, "err"); } }); },
  "open-dropzone": async function(){
    try { var r = await api("/dropzone/open", { method: "POST" });
      toast("DropZone folder opened: " + (r.dir || ""), "ok");
    } catch (e) { toast(e.message, "err"); } },
  "open-docs": function(){ openDocs(); },   /* v3.2.6: docs INSIDE the UI */
  "open-github": function(){ window.open("https://github.com/bitdreamit/AdvPrint-Pro", "_blank"); },
  "save-cfg": function(){ saveCfg(); },
  "save-hub": function(){ saveHub(); },
  "save-ext-prefs": function(){ saveExtPrefs(); },
  "save-sites": function(){ saveSites(); },
  "save-settings": function(){ saveSettingsPanel(); }
};
/* the EXACT 14 desktop tools (POST /tool) - requirement: all 14, no extras */
var TOOL_NAMES = {
  "start": "Start AdvPrint", "stop": "Stop AdvPrint", "status": "Status",
  "testprint": "Print test page", "service-install": "Windows service - install",
  "service-remove": "Windows service - remove", "autorun-toggle": "Start at logon ON/OFF",
  "check-update": "Check for updates (GitHub)", "recent-jobs": "Show recent jobs",
  "uninstall": "Uninstall / remove", "livetest": "LIVE TEST (A-to-Z)",
  "open-dashboard": "Open dashboard", "diagnose": "Diagnose & fix", "restart": "Restart AdvPrint"
};
function runTool(action){
  var name = TOOL_NAMES[action] || action;
  if (action === "stop")
    return confirmBox("Stop AdvPrint?", "The hub process stops \u2014 printing and this console "
      + "go offline until you start it again.",
      async function(){ await doTool(action); });
  if (action === "uninstall")
    return confirmBox("Uninstall AdvPrint (autostart + service)?",
      "Start-at-logon is removed and the Windows service (if installed) is un-installed. "
      + "Program files and print history stay.",
      async function(){ await doTool(action); });
  if (action === "restart") return ACTIONS.restart();
  doTool(action);
  function doTool(a){
    api("/tool", { method: "POST", body: { action: a } }).then(function(r){
      var res = r.result, msg = r.message || "";
      if (a === "status" && res) {
        toolOut(["AdvPrint Pro status",
          "  version:    v" + (res.version || "?"),
          "  service:    " + (res.service && res.service.installed
            ? (res.service.running ? "installed \u00b7 RUNNING" : "installed \u00b7 NOT running") : "not installed"),
          "  autostart:  " + (res.autostart ? "ON" : "OFF"),
          "  firewall:   " + (res.firewall ? "rule present (OK)" : "NO rule - LAN sharing blocked"),
          "  queue:      " + (res.queue ? (res.queue.pending + " waiting, " + res.queue.held + " held"
            + (res.queue.paused ? " \u00b7 PAUSED" : "")) : "?"),
          "  data dir:   " + (res.data_dir || "?")]);
      } else if (a === "livetest" && res && res.steps) {
        toolOut(res.steps.map(function(s){
          return "[" + (s.pass ? "OK" : "!!") + "] " + s.name + ": " + (s.info || ""); })
          .concat([res.all_ok ? "ALL CHECKS PASSED - AdvPrint Pro is ready for production."
                              : "Fix the [!!] items above, then run the live test again."]));
        toast(res.all_ok ? "LIVE TEST: all checks passed" : "LIVE TEST: problems found",
          res.all_ok ? "ok" : "warn");
      } else if (a === "recent-jobs" && res && res.jobs) {
        var rows = res.jobs.map(function(j){
          return " #" + j.id + "  " + (j.created_at || "").slice(0, 19) + "  " + j.status +
                 "  " + (j.printer || "-") + "  " + (j.title || "").slice(0, 34); });
        toolOut(["recent jobs (latest " + rows.length + ")"].concat(rows.length ? rows : ["  (none)"]));
      } else if (a === "check-update" && res) {
        renderUpdate(res);
      } else if (a === "diagnose" && res) {
        toolOut(["DIAGNOSE & FIX \u2014 report",
          "  hub online:   YES (this console)",
          "  service:      " + (res.service && res.service.installed
            ? (res.service.running ? "installed \u00b7 running" : "installed \u00b7 NOT running") : "not installed"),
          "  autostart:    " + (res.autostart ? "ON" : "OFF"),
          "  firewall:     " + (res.firewall ? "rule present" : "NO rule \u2014 Network \u2192 Allow in firewall"),
          "  self-check:   " + (res.problems && res.problems.length
            ? res.problems.length + " finding(s)" : "all clear")]);
        toast("Diagnosis ready \u2014 see the output box", "ok");
      } else if (a === "policy-install") {
        toolOut(["Policy install \u2014 " + (res.browser || "?") + " " + (res.hive || ""),
          "  " + (msg || "done")]);
        toast(msg || "Policy written \u2014 restart that browser", "ok");
      } else {
        toolOut(["[" + name + "]", msg || "done \u2014 see the hub log for details"]);
        toast(name + ": " + (msg || "done"), "ok");
      }
      poll();
    }).catch(function(e){
      toolOut(["[" + name + "] FAILED", "  " + e.message]);
      toast(name + " failed: " + e.message, "err");
    });
  }
}
/* inject the 14-tool grid into Debug & Tools (exactly 14 buttons) */
function injectTools(){
  var card = qsa("#p-debug .card").filter(function(c){
    return /Live debug/i.test(c.querySelector(".card-h") ? c.querySelector(".card-h").textContent : ""); })[0];
  if (!card || $("toolsGrid")) return;
  var b = document.createElement("div");
  b.id = "toolsGrid";
  b.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;margin-top:10px";
  Object.keys(TOOL_NAMES).forEach(function(a, i){
    var btn = document.createElement("button");
    btn.className = "btn small" + (i === 0 ? " blue" : "");
    btn.setAttribute("data-tool", a);
    btn.textContent = "[" + (i + 1) + "] " + TOOL_NAMES[a];
    b.appendChild(btn);
  });
  var cap = document.createElement("div");
  cap.style.cssText = "flex-basis:100%;font-size:10.5px;color:var(--muted);margin-top:2px";
  cap.textContent = "The complete AdvPrint tool menu \u2014 all 14 tools of the desktop app, right here (loopback + token).";
  b.appendChild(cap);
  card.querySelector(".card-b").appendChild(b);
}

/* ---------- confirm box (injected) ---------- */
var _cfCb = null;
function confirmBox(title, msg, cb){
  var m = $("confirmmodal");
  if (!m) {
    m = document.createElement("div");
    m.className = "modal-back"; m.id = "confirmmodal";
    m.innerHTML = '<div class="modal"><div class="m-h"><span id="cfTitle"></span>' +
      '<button class="x" data-close>\u2715</button></div>' +
      '<div style="padding:16px 18px;font-size:12.5px;color:var(--ink-2)" id="cfMsg"></div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end;padding:0 18px 16px">' +
      '<button class="btn" data-close>Cancel</button>' +
      '<button class="btn danger" id="cfOk">Confirm</button></div></div>';
    document.body.appendChild(m);
    m.addEventListener("click", function(e){
      if (e.target === m || e.target.closest("[data-close]")) closeModal(); });
    $("cfOk").addEventListener("click", function(){
      closeModal();
      if (_cfCb) { var f = _cfCb; _cfCb = null; f(); }
    });
  }
  $("cfTitle").textContent = title;
  $("cfMsg").textContent = msg;
  _cfCb = cb;
  openModal("confirmmodal");
}

/* ---------- v3.2.1 r2: import rules / export config helpers ---------- */
function importRulesFile(){
  var inp = document.createElement("input");
  inp.type = "file"; inp.accept = ".json,application/json";
  inp.onchange = function(){
    var f = inp.files && inp.files[0]; if (!f) return;
    var rd = new FileReader();
    rd.onload = function(){
      try {
        var arr = JSON.parse(rd.result);
        if (!Array.isArray(arr)) arr = [arr];
        var cur = (cfgCache.rules_mirror || []).slice();
        arr.forEach(function(r){
          if (typeof r === "string") r = { pattern: r, match: "url", kind: "pdf" };
          r.id = r.id || ("r" + Date.now() + "_" + Math.floor(Math.random() * 1e4));
          cur.push(r);
        });
        api("/config", { method: "POST", body: { rules_mirror: cur } })
          .then(function(){ toast(arr.length + " rule(s) imported \u2014 extensions adopt them automatically", "ok"); poll(); })
          .catch(function(e){ toast(e.message, "err"); });
      } catch (e) { toast("Not a valid rules JSON file: " + e.message, "err"); }
    };
    rd.readAsText(f);
  };
  inp.click();
}
function exportConfigFile(){
  api("/config").then(function(c){
    var blob = new Blob([JSON.stringify(c, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "config.json";
    document.body.appendChild(a); a.click(); a.remove();
    toast("config.json downloaded", "ok");
  }).catch(function(e){ toast(e.message, "err"); });
}

/* ---------- generic button wiring (label-bound, frozen markup) ---------- */
function bindButtons(){
  /* data-act + data-tool delegation */
  document.addEventListener("click", async function(ev){
    var t = ev.target;
    /* v3.2.2: choosing ANY menu item closes its dropdown (the old UI
       kept the dropdown hanging open until you clicked elsewhere) */
    if (t.closest && t.closest(".dd-it")) closeMenus();
    var goto = t.closest && t.closest("[data-goto]");
    if (goto) { showTab(goto.dataset.goto);
      if (goto.dataset.toast) toast(goto.dataset.toast, goto.dataset.ttype);
      if (goto.dataset.qr) openQR(goto.dataset.qr);
      return; }
    var md = t.closest && t.closest("[data-modal]");
    if (md) { openModal(md.dataset.modal); return; }
    var tk = t.closest && t.closest("[data-toast]");
    if (tk && !tk.closest(".menubar")) { toast(tk.dataset.toast, tk.dataset.ttype); }
    var cp = t.getAttribute && t.getAttribute("data-cp");
    if (cp) return copyText(cp, t);
    var sd = t.getAttribute && t.getAttribute("data-setdef");
    if (sd) { try { /* v3.2.5 BUG FIX 1: /printers/set-default performs the
                        OS-level change (Windows also opts out of "let
                        Windows manage my default printer"); the toast
                        reports the VERIFIED result, not a wish */
      var r5 = await api("/printers/set-default", { method: "POST", body: { printer: sd } });
      toast(r5.detail || (sd + " is now the OS default printer"), "ok");
    } catch (e) { toast(e.message, "err"); } poll(); }
    var pt = t.getAttribute && t.getAttribute("data-ptest");
    if (pt) { try { await api("/testprint", { method: "POST", body: { printer: pt } });
        toast("Test page queued on " + pt, "ok"); poll(); } catch (e) { toast(e.message, "err"); } }
    var pn = t.getAttribute && t.getAttribute("data-pnow");
    if (pn) { try { await api("/jobs/" + pn + "/print-now", { method: "POST" }); poll(); } catch (e) { toast(e.message, "err"); } }
    var rt = t.getAttribute && t.getAttribute("data-retry");
    if (rt) { try { await api("/jobs/" + rt + "/retry", { method: "POST" }); poll(); } catch (e) { toast(e.message, "err"); } }
    var rp = t.getAttribute && t.getAttribute("data-reprint");
    if (rp) { try { await api("/jobs/" + rp + "/reprint", { method: "POST" });
        toast("Reprint queued (job #" + rp + ")", "ok"); poll(); } catch (e) { toast(e.message, "err"); } }
    var cx = t.getAttribute && t.getAttribute("data-cancel");
    if (cx) { try { await api("/jobs/" + cx + "/cancel", { method: "POST" }); poll(); } catch (e) { toast(e.message, "err"); } }
    var sh = t.getAttribute && t.getAttribute("data-shift");
    if (sh) { try { await api("/queue/shift", { method: "POST", body: { target: sh, scope: "all" } });
        toast("Queue shifted to " + sh, "ok"); poll(); } catch (e) { toast(e.message, "err"); } }
    var tool = t.closest && t.closest("[data-tool]");
    if (tool) { runTool(tool.dataset.tool); return; }
    var act = t.closest && t.closest("[data-act]");
    if (act) { var fn = ACTIONS[act.dataset.act]; if (fn) fn(); return; }
    var rtg = t.getAttribute && t.getAttribute("data-rtoggle");
    if (rtg !== null) {
      var rules = rulesCache.slice();
      rules[+rtg].on = !rules[+rtg].on;
      try { await api("/config", { method: "POST", body: { rules_mirror: rules } });
        toast("Rule " + (rules[+rtg].on ? "ON" : "OFF"), "ok"); poll();
      } catch (e) { toast(e.message, "err"); } }
    var rau = t.getAttribute && t.getAttribute("data-rauto");
    if (rau !== null) {
      var rules2 = rulesCache.slice();
      rules2[+rau].auto = !rules2[+rau].auto;
      try { await api("/config", { method: "POST", body: { rules_mirror: rules2 } });
        toast("Auto-print " + (rules2[+rau].auto ? "ON" : "OFF") + " for this rule", "ok"); poll();
      } catch (e) { toast(e.message, "err"); } }
    var er = t.closest && t.closest("[data-edit-rule]");
    if (er) { openRuleEditor(+er.dataset.editRule); return; }
    var nr = t.closest && t.closest("[data-new-rule]");
    if (nr) { openRuleEditor(-1); return; }
    var dr = t.closest && t.closest("[data-del-rule]");
    if (dr) {
      var i3 = +dr.dataset.delRule;
      confirmBox("Delete this rule?", (rulesCache[i3] || {}).name || "rule", async function(){
        var rules3 = rulesCache.slice(); rules3.splice(i3, 1);
        try { await api("/config", { method: "POST", body: { rules_mirror: rules3 } });
          toast("Rule deleted", "warn"); poll(); } catch (e) { toast(e.message, "err"); } });
      return; }
    var uu = t.closest && t.closest("[data-use-url]");
    if (uu) { showTab("rules"); openRuleEditor(-1);
      $("re-url").value = uu.dataset.useUrl; return; }
  });

  /* label-bound buttons per panel */
  function btnIn(scope, label, fn){
    qsa(scope + " button").forEach(function(b){
      var txt = b.textContent.replace(/\s+/g, " ").trim();
      if (txt === label && !b.dataset.bound) { b.dataset.bound = "1"; b.addEventListener("click", fn); }
    });
  }
  function btnLike(scope, re, fn){
    qsa(scope + " button").forEach(function(b){
      if (re.test(b.textContent.replace(/\s+/g, " ").trim()) && !b.dataset.bound) {
        b.dataset.bound = "1"; b.addEventListener("click", fn); }
    });
  }
  /* dashboard */
  btnLike("#p-dashboard", /Refresh/, function(){ ACTIONS.poll(); });
  btnLike("#p-dashboard", /Test Page|test print/i, function(){ ACTIONS.testprint(); });
  btnLike("#p-dashboard", /Release ALL held/i, function(){ ACTIONS["release-held"](); });
  btnLike("#p-dashboard", /Full self-test/i, function(){ runTool("livetest"); });
  btnLike("#p-dashboard", /Copy invite link/i, function(){ ACTIONS["copy-invite"](); });
  btnLike("#p-dashboard", /Send portal QR/i, function(){ openQR("send"); });
  btnLike("#p-dashboard", /Open Printers/i, function(){ showTab("printers"); });
  /* queue */
  btnLike("#p-queue", /Refresh now/, function(){ ACTIONS.poll(); });
  btnLike("#p-queue", /Pause queue|Resume queue/i, function(){ ACTIONS["queue-pause-toggle"](); });
  btnLike("#p-queue", /Clear queue/i, function(){ ACTIONS["queue-clear"](); });
  /* history */
  btnLike("#p-history", /Reprint selected/i, function(){ reprintChecked(); });
  btnLike("#p-history", /Reprint non-printed/i, function(){ reprintFailed(); });
  btnLike("#p-history", /Clear ALL history/i, function(){ ACTIONS["queue-clear-finished"](); });
  btnLike("#p-history", /Export CSV/i, function(){ ACTIONS["export-history"](); });
  /* v3.2.5 BUG FIXES 2 + 3: the bulk-selection buttons (History AND Queue) */
  btnLike("#p-history", /Cancel selected/i, function(){ cancelSelected("history"); });
  btnLike("#p-history", /Clear selected/i, function(){ clearSelection("history"); });
  btnLike("#p-queue", /Cancel selected/i, function(){ cancelSelected("queue"); });
  btnLike("#p-queue", /Clear selected/i, function(){ clearSelection("queue"); });
  /* printers */
  btnLike("#p-printers", /Re-scan/i, function(){ ACTIONS["refresh-printers"](); });
  btnLike("#p-printers", /Reload list/i, function(){ ACTIONS["refresh-printers"](); });
  btnLike("#p-printers", /Browse/i, function(){ toast("Type the full SumatraPDF.exe path instead \u2014 browser file pickers cannot see printer paths", "warn"); });
  btnLike("#p-printers", /Reset/i, function(){
    qsa("#p-printers input.inp.mono")[0].value = "";
    api("/config", { method: "POST", body: { sumatra_path: "" } })
      .then(function(){ toast("SumatraPDF override reset \u2014 auto-find is active", "ok"); })
      .catch(function(e){ toast(e.message, "err"); }); });
  /* LAN rows */
  btnLike("#p-lan", /Copy URL/i, function(){ ACTIONS["copy-hub-url"](); });
  btnLike("#p-lan", /Copy send URL/i, function(){ ACTIONS["copy-send-url"](); });
  btnLike("#p-lan", /Copy invite link/i, function(){ ACTIONS["copy-invite"](); });
  btnLike("#p-lan", /Copy printer URL/i, function(){ ACTIONS["copy-ipp-url"](); });
  btnLike("#p-lan", /Test LAN/i, function(){ ACTIONS["fw-status"](); });
  btnLike("#p-lan", /Allow in firewall|firewall/i, function(){ ACTIONS["fw-allow"](); });
  /* Disable/Enable buttons are bound per-row in renderLanRows()
     (LAN sharing -> share_lan, IP Printer mode -> ipp_printer,
     Printer status hold -> hold_offline) */
  btnLike("#p-lan", /How to add/i, function(){ openQR("ipp"); });
  /* connections */
  /* v3.3.2: the LAN PC card's Connect/Clear bind FIRST (ids), so the
     generic "Connect"/"Clear" matchers below can never swallow them
     again - the v3.3.0-era generic handler read the SELF PC URL field
     for the LAN card too, which is exactly the "auto redirect own ip"
     behaviour the user reported. */
  var lanPcBtn = $("lanPcConnect");
  if (lanPcBtn && !lanPcBtn.dataset.bound) {
    lanPcBtn.dataset.bound = "1";
    lanPcBtn.addEventListener("click", function(){
      var urlEl = $("lanPcHubUrl"), tokEl = $("lanPcToken");
      var url = (urlEl && urlEl.value || "").trim();
      var tok = (tokEl && tokEl.value || "").trim();
      if (!url || !tok) return toast(
        "Enter the OTHER PC's hub URL (e.g. http://192.168.1.101:9235) and its token, then Connect", "warn");
      toast("Probing " + url + " ...");
      api("/peer/pair", { method: "POST", body: { url: url, token: tok } })
        .then(function(st){
          renderLanPeer(st);
          if (tokEl) tokEl.value = "";
          var p = st.peer || {};
          toast(p.alive
            ? "Connected to the LAN PC (" + (p.version || "?") + ") - Share Send Mode is ready"
            : "Saved, but that PC did not answer just now", p.alive ? "ok" : "warn");
          loadRemoteState();
        })
        .catch(function(e){ toast(e.message, "err"); });
    });
  }
  var lanPcClr = $("lanPcClear");
  if (lanPcClr && !lanPcClr.dataset.bound) {
    lanPcClr.dataset.bound = "1";
    lanPcClr.addEventListener("click", function(){
      api("/peer/unpair", { method: "POST", body: {} })
        .then(function(st){
          renderLanPeer(st);
          var u = $("lanPcHubUrl"), t = $("lanPcToken");
          if (u) u.value = ""; if (t) t.value = "";
          toast("LAN PC pairing cleared - Share Send Mode OFF", "warn");
          loadRemoteState();
        })
        .catch(function(e){ toast(e.message, "err"); });
    });
  }
  btnLike("#p-connections", /Save settings/i, function(){ ACTIONS["save-sites"](); });
  btnLike("#p-connections", /Save site list/i, function(){ ACTIONS["save-sites"](); });
  btnLike("#p-connections", /Detect token/i, function(){
    var inp = qsa("#p-connections input[type=password]")[0];
    if (inp) { inp.value = TOKEN; toast("Token filled from the running hub", "ok"); } });
  btnIn("#p-connections", "Connect", function(){
    var url = qsa("#p-connections input.inp.mono")[0].value.trim();
    if (url && url !== BASE) { toast("This console is served BY the hub \u2014 " + BASE + " is already connected", "ok"); }
    else toast("Connected \u2014 hub answered", "ok"); });
  btnLike("#p-connections", /Shift all waiting/i, function(){
    /* v3.3.3: read the REAL shift-target input (id=shiftTarget). The
       old qsa(...)[1] hit the Self PC token field after the LAN PC
       card was inserted above it, and the body used the key `peer`
       while the endpoint reads `target` - so Shift all waiting either
       did nothing useful or fired at a garbage "URL". */
    var inp = $("shiftTarget");
    var peer = inp ? inp.value.trim() : "";
    if (!peer) return toast("Enter the peer hub URL first", "warn");
    api("/queue/shift", { method: "POST", body: { target: peer, scope: "all" } })
      .then(function(){ toast("Queue shifted to " + peer, "ok"); poll(); })
      .catch(function(e){ toast(e.message, "err"); }); });
  /* hub panel */
  btnLike("#p-hub", /Apply hub settings/i, function(){ ACTIONS["save-hub"](); });
  btnLike("#p-hub", /Reload from hub/i, function(){ refreshHubPanel(); toast("Reloaded from hub", "ok"); });
  /* dropzone */
  btnLike("#p-dropzone", /Open folder/i, function(){ ACTIONS["open-dropzone"](); });
  btnLike("#p-dropzone", /^Disable$/, function(){
    api("/config", { method: "POST", body: { drop_enabled: false } })
      .then(function(){ toast("DropZone watch OFF", "warn"); loadDropzone(); })
      .catch(function(e){ toast(e.message, "err"); }); });
  btnLike("#p-dropzone", /^Save$/, function(){
    var inp = qsa("#p-dropzone input.inp")[1];
    api("/config", { method: "POST", body: { drop_dir: inp ? inp.value.trim() : "" } })
      .then(function(){ toast("DropZone folder saved", "ok"); loadDropzone(); })
      .catch(function(e){ toast(e.message, "err"); }); });
  /* rules */
  btnLike("#p-rules", /Import JSON/i, function(){
    var inp = document.createElement("input");
    inp.type = "file"; inp.accept = ".json";
    inp.onchange = function(){
      var f = inp.files[0]; if (!f) return;
      var rd = new FileReader();
      rd.onload = async function(){
        try {
          var list = JSON.parse(rd.result);
          if (!Array.isArray(list)) throw new Error("expected a JSON array");
          await api("/config", { method: "POST", body: { rules_mirror: list } });
          toast(list.length + " rules imported", "ok"); poll();
        } catch (e) { toast("Import failed: " + e.message, "err"); }
      };
      rd.readAsText(f);
    };
    inp.click(); });
  btnIn("#p-rules", "Match URL", function(){
    var v = qsa("#p-rules input.inp.mono")[0].value.trim();
    if (v) { openRuleEditor(-1); $("re-url").value = v; } });
  btnIn("#p-rules", "Match content", function(){
    var v = qsa("#p-rules input.inp.mono")[1].value.trim();
    if (v) { openRuleEditor(-1); $("re-content").value = v; } });
  /* power + browser */
  /* v3.2.2: the switches save themselves the moment they are flipped
     (see bindSwitches) - the two old "Save & push to browsers" buttons
     were duplicates and are gone. Keep the ACTION for one-off use. */
  /* extension */
  btnLike("#p-extension", /New Token/i, function(){ ACTIONS["rotate-token"](); });
  btnLike("#p-extension", /Download CRX/i, function(){
    window.open(BASE + "/extension/AdvPrint-Pro.crx", "_blank"); });
  btnLike("#p-extension", /Copy value/i, function(){ ACTIONS["copy-policy"](); });
  btnLike("#p-extension", /Copy URL/i, function(){ ACTIONS["copy-updates"](); });
  qsa('#p-extension table.tbl button').forEach(function(b){
    var m2 = b.textContent.match(/Apply (HKLM|HKCU)/);
    if (m2 && !b.dataset.bound) {
      b.dataset.bound = "1";
      b.addEventListener("click", function(){
        var row = b.closest("tr");
        var path = row.querySelector(".mono") ? row.querySelector(".mono").textContent.trim() : "";
        runToolPolicy(m2[1], path);
      });
    }
  });
  /* debug */
  btnLike("#p-debug", /Enable debug/i, function(){
    api("/config", { method: "POST", body: { debug: !cfgCache.debug } })
      .then(function(){ toast("Debug mode " + (!cfgCache.debug ? "ON" : "OFF"), "ok"); poll(); })
      .catch(function(e){ toast(e.message, "err"); }); });
  btnLike("#p-debug", /Run service-remove/i, function(){ runTool("service-remove"); });
  btnLike("#p-debug", /Re-check/i, function(){ poll(); toast("Service state re-checked", "ok"); });
  btnLike("#p-debug", /Release ALL held/i, function(){ ACTIONS["release-held"](); });
  btnLike("#p-debug", /Full self-test/i, function(){ runTool("livetest"); });
  btnLike("#p-debug", /Open spool folder/i, function(){
    api("/tool", { method: "POST", body: { action: "open-dashboard" } })
      .then(function(){ toast("Opening the hub\u2019s own console \u2014 the spool folder opens from Diagnose", "ok"); })
      .catch(function(e){ toast(e.message, "err"); }); });
  btnLike("#p-debug", /Export debug bundle/i, function(){
    api("/debug").then(function(d){
      var blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "advprint-debug-bundle.json";
      a.click();
      toast("Debug bundle exported", "ok");
    }).catch(function(e){ toast(e.message, "err"); }); });
  /* audit */
  btnLike("#p-audit", /Export CSV/i, function(){ ACTIONS["export-audit"](); });
  btnLike("#p-audit", /Clear audit/i, function(){
    confirmBox("Clear the audit trail?", "Compliance note: the audit log is append-only while the hub runs. " +
      "It is rotated with the hub log instead. Use Export CSV to archive it.",
      function(){ toast("Audit is append-only (compliance) \u2014 use Export CSV", "warn"); }); });
  /* logs */
  btnLike("#p-logs", /Save log/i, function(){
    var box = document.querySelector("#p-logs .logbox");
    var blob = new Blob([box.textContent], { type: "text/plain" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "advprint-hub-log.txt"; a.click();
    toast("Log saved", "ok"); });
  /* settings */
  btnLike("#p-settings", /Save & Apply/i, function(){ ACTIONS["save-settings"](); });
  btnLike("#p-settings", /Rotate token/i, function(){ ACTIONS["rotate-token"](); });
  btnLike("#p-settings", /Restart hub/i, function(){ ACTIONS.restart(); });
  btnLike("#p-settings", /Open data folder/i, function(){
    api("/tool", { method: "POST", body: { action: "open-dashboard" } })
      .then(function(){ toast("Data folder: " + (cfgCache.data_dir || "~/.advprint"), "ok"); })
      .catch(function(e){ toast(e.message, "err"); }); });
  btnLike("#p-settings", /Restore Defaults/i, function(){
    confirmBox("Restore default settings?", "Queue, LAN, IPP, DropZone and audit switches return to " +
      "the v3.2.1 defaults (website whitelist stays *).",
      async function(){
        try {
          await api("/config", { method: "POST", body: {
            share_lan: false, ipp_printer: true, ipp_mdns: true, hold_offline: true,
            instant_auto_queue: true, keep_files: true, audit_enabled: true,
            reprint_watermark: false, reprint_reason_required: false, debug: false,
            drop_enabled: false, drop_delete: false } });
          toast("Defaults restored", "ok"); poll();
        } catch (e) { toast(e.message, "err"); } }); });
  /* about */
  btnLike("#p-about", /Check for updates/i, function(){ runTool("check-update"); });
  /* toolbar buttons with real actions */
  btnLike(".toolbar", /Test Page/, function(){ ACTIONS.testprint(); });
  btnLike(".toolbar", /Pause Queue|Resume Queue/i, function(){ ACTIONS["queue-pause-toggle"](); });
  btnLike(".toolbar", /Release ALL/, function(){ ACTIONS["release-held"](); });
  btnLike(".toolbar", /New Job/, function(){ showTab("dropzone"); toast("Drop a PDF into DropZone or submit from any page", "ok"); });
  btnLike(".toolbar", /History/, function(){ showTab("history"); });
  /* menubar direct actions that carry data-toast only (firewall, restart, check updates...) */
  qsa(".menubar .dd-it").forEach(function(it){
    if (it.dataset.bound) return;
    /* v3.2.1 r2 FIX: the label must come from the ITEM TEXT ONLY -
       the icon (.ic) and shortcut (.sc) spans previously rode along
       ("\u26a1New print job\u2026Ctrl+N"), so EVERY /^...$/ regex below
       failed and no menu item was ever bound to a real action
       (the user-visible "menu some linkup missing" bug). */
    var t = (function(el){
      var c = el.cloneNode(true);
      qsa(".ic,.sc", c).forEach(function(s){ s.remove(); });
      return c.textContent.replace(/\s+/g, " ").trim();
    })(it);
    if (/^Allow TCP 9235 in firewall$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS["fw-allow"](); }); }
    else if (/^Test LAN$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS["fw-status"](); }); }
    else if (/^Restart hub$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS.restart(); }); }
    else if (/^Check for updates$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ runTool("check-update"); }); }
    else if (/^Copy hub URL$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS["copy-hub-url"](); }); }
    else if (/^Pause queue$/.test(t) || /^Resume queue$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS["queue-pause-toggle"](); }); }
    else if (/^Release ALL held jobs$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS["release-held"](); }); }
    else if (/^Clear finished jobs$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS["queue-clear-finished"](); }); }
    else if (/^Export CSV\u2026?$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS["export-history"](); }); }
    else if (/^Reprint last job$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ reprintLast(); }); }
    else if (/^Print test page$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS.testprint(); }); }
    else if (/^REAL test print/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS.testprint(); }); }
    else if (/^Full self-test$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ runTool("livetest"); }); }
    else if (/^Debug mode$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ showTab("debug"); }); }
    else if (/^Quick start guide$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS["open-docs"](); }); }
    else if (/^GitHub repository$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ window.open("https://github.com/bitdreamit/AdvPrint-Pro", "_blank"); }); }
    else if (/^Exit hub/.test(t)) { it.dataset.bound = "1"; it.classList.remove("dis");
      it.addEventListener("click", function(){ runTool("stop"); }); }
    else if (/^Install as Windows service$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ runTool("service-install"); }); }
    else if (/^Set default printer$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ showTab("printers"); }); }
    else if (/^Add IP printer\u2026?$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ showTab("printers"); openQR("ipp"); }); }
    else if (/^Rotate token\u2026?$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ ACTIONS["rotate-token"](); }); }
    else if (/^Open config.json$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ toast("config.json: " + (cfgCache.config_file || "~/.advprint/config.json"), "ok"); }); }
    else if (/^Share Send portal\u2026?$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ openQR("send"); }); }
    else if (/^New print job\u2026?$/.test(t)) { it.dataset.bound = "1";
      it.removeAttribute("data-goto");
      it.addEventListener("click", function(){ showTab("dropzone");
        toast("Drop a PDF into DropZone or submit from any page", "ok"); }); }
    else if (/^Open DropZone folder$/.test(t)) { it.dataset.bound = "1";
      it.removeAttribute("data-goto");
      it.addEventListener("click", function(){ ACTIONS["open-dropzone"](); }); }
    else if (/^Import auto-print rules\u2026?$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ importRulesFile(); }); }
    else if (/^Export settings \(config\.json\)$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ exportConfigFile(); }); }
    else if (/^Reprint selected jobs$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){ reprintChecked(); }); }
    else if (/^Clear ALL finished jobs\u2026?$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){
        confirmBox("Clear ALL finished jobs?",
          "Printed, failed and canceled jobs are removed from history. Waiting and held jobs are untouched.",
          function(){ ACTIONS["queue-clear-finished"](); }); }); }
    else if (/^Printer status hold$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){
        var on = cfgCache.hold_offline === false;
        api("/config", { method: "POST", body: { hold_offline: on } })
          .then(function(){ toast("Printer status hold " + (on
            ? "ON \u2014 jobs wait while a printer is offline" : "OFF"), on ? "ok" : "warn"); poll(); })
          .catch(function(e){ toast(e.message, "err"); }); }); }
    else if (/^Status bar$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){
        var sb = document.querySelector(".statusbar");
        if (sb) { sb.style.display = sb.style.display === "none" ? "" : "none";
          it.classList.toggle("chk", sb.style.display !== "none");
          toast(sb.style.display === "none" ? "Status bar hidden" : "Status bar shown", "ok"); } }); }
    else if (/^Full screen$/.test(t)) { it.dataset.bound = "1";
      it.addEventListener("click", function(){
        if (document.fullscreenElement) document.exitFullscreen();
        else if (document.documentElement.requestFullscreen)
          document.documentElement.requestFullscreen(); }); }
  });
  function reprintChecked(){
    var ids = qsa('#p-history table.tbl input[type=checkbox]:checked').map(function(c){
      return c.getAttribute("data-hid"); }).filter(Boolean);
    if (!ids.length) return toast("Tick some rows first", "warn");
    (async function(){
      for (var i = 0; i < ids.length; i++) {
        try { await api("/jobs/" + ids[i] + "/reprint", { method: "POST" }); } catch (e) {}
      }
      toast(ids.length + " job(s) queued for reprint", "ok"); poll();
    })();
  }
  function reprintFailed(){
    var failed = lastJobs.filter(function(j){
      return ["failed", "dead", "canceled"].indexOf(j.status) >= 0; });
    (async function(){
      for (var i = 0; i < failed.length; i++) {
        try { await api("/jobs/" + failed[i].id + "/retry", { method: "POST" }); } catch (e) {}
      }
      toast(failed.length + " failed job(s) retried", "ok"); poll();
    })();
  }
  function reprintLast(){
    var j = lastJobs[0];
    if (!j) return toast("No jobs yet", "warn");
    api("/jobs/" + j.id + "/reprint", { method: "POST" })
      .then(function(){ toast("Reprint queued (job #" + j.id + ")", "ok"); poll(); })
      .catch(function(e){ toast(e.message, "err"); });
  }
  async function runToolPolicy(hive, path){
    var browser = "chromium";
    var p = (path || "").toLowerCase();
    if (p.indexOf("google") >= 0) browser = "chrome";
    else if (p.indexOf("edge") >= 0) browser = "edge";
    else if (p.indexOf("brave") >= 0) browser = "brave";
    else if (p.indexOf("vivaldi") >= 0) browser = "vivaldi";
    else if (p.indexOf("opera") >= 0) browser = "opera";
    try {
      var r = await api("/tool", { method: "POST", body: {
        action: "policy-install", browser: browser, hive: hive } });
      toolOut(["Policy install \u2014 " + browser + " " + hive,
        "  " + (r.message || "written")]);
      toast(r.message || (browser + " policy written (" + hive + ") \u2014 restart the browser"), "ok");
    } catch (e) { toast("Policy install failed: " + e.message, "err"); }
  }
}

/* ---------- config save helpers ---------- */
async function saveCfg(){
  var patch = {};
  try {
    await api("/config", { method: "POST", body: patch });
    toast("Settings saved", "ok"); poll();
  } catch (e) { toast("Save failed: " + e.message, "err"); }
}
async function saveHub(){
  var ins = qsa("#p-hub input.inp.narrow");
  var patch = {};
  if (ins.length >= 5) {
    patch.max_retries = parseInt(ins[0].value, 10) || 0;
    patch.retry_base_seconds = parseInt(ins[1].value, 10) || 30;
    patch.dedupe_minutes = parseInt(ins[2].value, 10) || 5;
    patch.max_auth_failures = parseInt(ins[3].value, 10) || 10;
    patch.lockout_minutes = parseInt(ins[4].value, 10) || 5;
  }
  var origins = qsa('#p-hub input.inp[placeholder*="empty = all"]')[0];
  if (origins) patch.allowed_origins = origins.value.split(/[,;\s]+/).filter(Boolean);
  var sw = qsa("#p-hub .tgl .switch");
  var map = ["hold_offline", "instant_auto_queue", "token_header_only", null,
             "reprint_watermark", "reprint_reason_required", "audit_enabled", "keep_files"];
  sw.forEach(function(s, i){ var k = map[i]; if (k) patch[k] = s.classList.contains("on"); });
  var sel = qsa("#p-hub select.inp");
  if (sel.length >= 2) {
    var t = getSel(sel[0]);
    patch.thermal_text_engine = t.indexOf("Built-in") >= 0 ? "builtin"
      : t.indexOf("Browser") >= 0 ? "browser" : "auto";
    patch.escpos_codepage = getSel(sel[1]).toLowerCase();
  }
  var mono = qsa("#p-hub input.inp.mono");
  /* v3.2.3 SWITCH FIX part 1: file paths are saved only when the user
     actually changed them - the first switch save can no longer write
     the static demo placeholder paths into config.json */
  if (mono[0] && mono[0].value.trim() !== (cfgCache.file_dir || ""))
    patch.file_dir = mono[0].value.trim();
  if (mono[1] && mono[1].value.trim() !== (cfgCache.sumatra_path || ""))
    patch.sumatra_path = mono[1].value.trim();
  try {
    await api("/config", { method: "POST", body: patch });
    /* v3.2.2: saved -> clear the switch dirty flags */
    Object.keys(dirtyKeys).forEach(function(k){
      if (k.indexOf("hub_") === 0) delete dirtyKeys[k]; });
    toast("Hub settings saved \u2014 applied live", "ok"); poll();
  } catch (e) { toast("Save failed: " + e.message, "err"); }
}
/* ext_prefs uses the EXTENSION's own storage key names so background.js
   can adopt the mirror 1:1 (v3.2.1 ONE UI = master of the switches) */
function extPrefsFromPanels(){
  function swOn(i, scope){ var s = qsa(scope + " .tgl .switch")[i]; return s ? s.classList.contains("on") : null; }
  var langSel = qsa("#p-power select.inp")[0];
  var langTxt = langSel ? getSel(langSel) : "Automatic";
  var lang = langTxt.indexOf("English") >= 0 ? "en" : langTxt.indexOf("\u09ac\u09be\u0982") >= 0 ? "bn" : "auto";
  var fbSel = qsa("#p-browser select.inp")[0];
  return {
    enabled: swOn(0, "#p-power"),
    queueMode: swOn(1, "#p-power"),
    rulesPaused: swOn(2, "#p-power") === null ? null : !swOn(2, "#p-power"),
    hookPrint: swOn(3, "#p-power"),
    debugMode: swOn(4, "#p-power"),
    retryOffline: swOn(5, "#p-power"),
    lang: lang,
    autoPrintAllPdfs: swOn(0, "#p-browser"),
    closeAfterPrint: swOn(1, "#p-browser"),
    failFallback: fbSel ? (getSel(fbSel).indexOf("Open the URL") >= 0 ? "tab" : "none") : null,
    contextMenu: swOn(2, "#p-browser"),
    badge: swOn(3, "#p-browser")
  };
}
async function saveExtPrefs(){
  try {
    var prefs = extPrefsFromPanels();
    var cur = (await api("/config")).ext_prefs || {};
    prefs.print_defaults = cur.print_defaults || (cfgCache.ext_prefs || {}).print_defaults || {};
    await api("/config", { method: "POST", body: { ext_prefs: prefs } });
    /* v3.2.2: saved -> the poll may refresh the switches again */
    Object.keys(dirtyKeys).forEach(function(k){
      if (k.indexOf("#p-power") === 0 || k.indexOf("#p-browser") === 0) delete dirtyKeys[k]; });
    toast("Power/Browser switches saved \u2014 paired browsers adopt them within 5 min (or on next start)", "ok");
    poll();
  } catch (e) { toast("Save failed: " + e.message, "err"); }
}
/* apply stored ext_prefs to the Power / Browser panel switches */
function renderExtPrefs(prefs){
  prefs = prefs || {};
  function setSw(scope, i, v){
    var s = qsa(scope + " .tgl .switch")[i];
    if (s && v !== null && v !== undefined && !dirtyKeys[scope + i]) s.classList.toggle("on", !!v);
  }
  setSw("#p-power", 0, prefs.enabled);
  setSw("#p-power", 1, prefs.queueMode);
  setSw("#p-power", 2, prefs.rulesPaused === undefined ? undefined : !prefs.rulesPaused);
  setSw("#p-power", 3, prefs.hookPrint);
  setSw("#p-power", 4, prefs.debugMode);
  setSw("#p-power", 5, prefs.retryOffline);
  setSw("#p-browser", 0, prefs.autoPrintAllPdfs);
  setSw("#p-browser", 1, prefs.closeAfterPrint);
  setSw("#p-browser", 2, prefs.contextMenu);
  setSw("#p-browser", 3, prefs.badge);
}
async function saveSites(){
  try {
    var ta = document.querySelector("#p-connections textarea");
    var v = (ta.value || "").trim();
    var sites = (!v || v === "*") ? ["*"] : v.split(/\r?\n/).map(function(s){
      return s.trim(); }).filter(Boolean);
    await api("/config", { method: "POST", body: { ext_api_sites: sites } });
    toast(sites.indexOf("*") >= 0 ? "Site list = * (ALL websites may print)" :
      "Site list saved (" + sites.length + " patterns)", "ok");
    poll();
  } catch (e) { toast("Save failed: " + e.message, "err"); }
}
async function saveSettingsPanel(){
  try {
    var ins = qsa("#p-settings input.inp");
    var patch = {};
    var days = parseInt(ins[2] ? ins[2].value : "30", 10);
    if (!isNaN(days)) patch.history_days = days;
    var sels = qsa("#p-settings select");
    if (sels[0]) patch.log_level = getSel(sels[0]).toLowerCase();
    var sws = qsa("#p-settings .f-row .switch");
    if (sws[2]) patch.share_lan = sws[2].classList.contains("on");
    if (sws[3]) patch.hold_offline = sws[3].classList.contains("on");
    await api("/config", { method: "POST", body: patch });
    Object.keys(dirtyKeys).forEach(function(k){
      if (["autostart", "minimize", "lan", "hold"].indexOf(k) >= 0) delete dirtyKeys[k]; });
    var port = parseInt(ins[0].value, 10);
    if (port && port !== (BOOT.port || 9235))
      toast("Port lives in config.json / the installer \u2014 the hub rebinds on restart only (asked at install time)", "warn");
    else toast("Settings saved", "ok");
    poll();
  } catch (e) { toast("Save failed: " + e.message, "err"); }
}
/* print defaults (Printers panel) */
function bindPrintDefaults(){
  var card = qsa("#p-printers .card").filter(function(c){
    return /Default print options/i.test(c.querySelector(".card-h") ? c.querySelector(".card-h").textContent : ""); })[0];
  if (!card) return;
  function collect(){
    var ins = qsa("input.inp", card), sels = qsa("select.inp", card);
    var pd = {};
    if (ins[0]) pd.copies = parseInt(ins[0].value, 10) || 1;
    if (ins[1]) pd.pages = ins[1].value.trim();
    if (sels[0]) pd.quality = getSel(sels[0]);
    if (sels[1]) pd.nup = getSel(sels[1]);
    if (sels[2]) pd.duplex = getSel(sels[2]);
    if (sels[3]) pd.layout = getSel(sels[3]);
    if (ins[2]) pd.scale = parseInt(ins[2].value, 10) || 100;
    if (sels[4]) pd.paper = getSel(sels[4]);
    return pd;
  }
  qsa("input,select", card).forEach(function(el){
    el.addEventListener("change", async function(){
      try {
        var cur = (cfgCache.ext_prefs || {}).print_defaults || {};
        var merged = Object.assign({}, cur, collect());
        var prefs = Object.assign({}, cfgCache.ext_prefs || {}, { print_defaults: merged });
        await api("/config", { method: "POST", body: { ext_prefs: prefs } });
        toast("Default print options saved", "ok");
      } catch (e) { toast(e.message, "err"); }
    });
  });
  qsa("#p-printers input.inp.mono")[0].addEventListener("change", function(){
    var v = this.value.trim();
    api("/config", { method: "POST", body: { sumatra_path: v } })
      .then(function(){ toast("SumatraPDF path saved", "ok"); })
      .catch(function(e){ toast(e.message, "err"); });
  });
  qsa("#p-printers input.inp.narrow")[0].addEventListener("change", function(){
    var v = parseInt(this.value, 10) || 1;
    var prefs = Object.assign({}, cfgCache.ext_prefs || {});
    prefs.print_defaults = Object.assign({}, prefs.print_defaults || {}, { copies: v });
    api("/config", { method: "POST", body: { ext_prefs: prefs } })
      .then(function(){ toast("Default copies = " + v, "ok"); })
      .catch(function(e){ toast(e.message, "err"); });
  });
}
/* ---------- v3.2.2 SWITCHES THAT ACTUALLY WORK ----------
   The v3.2.1 console rendered every switch but clicking one only set a
   hidden dirty flag - the switch did not move and nothing was saved.
   Now ONE delegated handler flips every switch and saves it instantly
   (debounced 400 ms so flipping several switches = one write):
     Power / Browser switches -> ext_prefs  -> paired browsers adopt
     Hub panel switches       -> /config (same patch as Apply)
     Settings panel switches  -> /config (Start-with-Windows and
        Minimize-to-tray are managed by the service/tray - they refuse
        with a hint instead of saving)
     DropZone delete-after    -> drop_delete config key
     Rule editor switches     -> toggle only, saved with the rule form
   dirtyKeys guards every scope so the 3 s poll never overwrites a
   switch the user just flipped; every save clears them again. */
var _swTimers = {};
function swSave(scope){
  clearTimeout(_swTimers[scope]);
  _swTimers[scope] = setTimeout(function(){
    if (scope === "p-power" || scope === "p-browser") saveExtPrefs();
    else if (scope === "p-hub") saveHub();
    else if (scope === "p-settings") saveSettingsPanel();
  }, 400);
}
function swDirty(scope, s){
  if (scope === "p-power")
    dirtyKeys["#p-power" + qsa("#p-power .tgl .switch").indexOf(s)] = 1;
  else if (scope === "p-browser")
    dirtyKeys["#p-browser" + qsa("#p-browser .tgl .switch").indexOf(s)] = 1;
  else if (scope === "p-hub") {
    var i = qsa("#p-hub .tgl .switch").indexOf(s);
    var map = ["hold_offline", "instant_auto_queue", "token_header_only", null,
               "reprint_watermark", "reprint_reason_required", "audit_enabled",
               "keep_files"];
    if (map[i]) dirtyKeys["hub_" + map[i]] = 1;
  } else if (scope === "p-settings") {
    var i2 = qsa("#p-settings .f-row .switch").indexOf(s);
    dirtyKeys[["autostart", "minimize", "lan", "hold"][i2] || "s" + i2] = 1;
  }
}
function bindSwitches(){
  document.addEventListener("click", function(ev){
    var s = ev.target.closest ? ev.target.closest(".switch") : null;
    if (!s) return;
    /* v3.3.2 SHARE SEND MODE (Connections LAN PC card) - saves itself
       the moment it is flipped, reads the PERSISTED pairing (never a
       transient JS flag), and reverting ON-without-peer is impossible
       server-side too (POST /config validates share_send).
       v3.3.3 POPUP FIX: the old client-side pre-check
       ("Connect the LAN PC first" toast when lanPeerState was not yet
       loaded) fired on a normal page load - lanPeerState stays null
       until the FIRST /peer/status answer, and that answer waits behind
       seven sequential poll calls (health, stats, queue, printers,
       jobs, audit, config - printers can take seconds on Windows WMI).
       So a user who flipped Share Send right after opening the console
       got the false popup EVEN THOUGH the pairing was saved and the
       server would have accepted the flip. The client no longer blocks:
       the POST goes out and the SERVER (the persisted truth) decides;
       on 400 the switch reverts and the server's real message shows. */
    if (s.id === "shareSendSw") {
      var want = !s.classList.contains("on");
      s.classList.toggle("on", want);
      _shareSendPending = true;
      api("/config", { method: "POST", body: { share_send: want } })
        .then(function(){
          if (lanPeerState) lanPeerState.share_send = want;
          toast(want ? "Share Send Mode ON \u2014 every print job now goes to the LAN PC"
                     : "Share Send Mode OFF \u2014 jobs print on the Self PC again",
                want ? "warn" : "ok");
          loadLanPeer();
        })
        .catch(function(e){ s.classList.toggle("on", !want);
          toast(e.message, "err"); })
        .then(function(){ _shareSendPending = false; });
      return;
    }
    /* v3.3.2 remote devices switch (Printers panel) */
    if (s.id === "showRemoteSw") {
      var wantR = !s.classList.contains("on");
      s.classList.toggle("on", wantR);
      api("/config", { method: "POST", body: { show_remote_printers: wantR } })
        .then(function(){
          cfgCache.show_remote_printers = wantR;
          if (wantR) { toast("Other PCs' devices shown below (LAN PC \u00b7 IPP badge)", "ok"); loadLanPeer(); }
          else { qsa("#p-printers .pcard[data-remote]").forEach(function(c){ c.remove(); });
                 toast("Remote devices hidden", "warn"); }
        })
        .catch(function(e){ s.classList.toggle("on", !wantR);
          toast(e.message, "err"); });
      return;
    }
    /* only switches inside toggle rows / form rows / the rule editor
       are controls - per-browser state table cells stay read-only */
    var zone = s.closest(".tgl, .f-row, #rulemodal");
    if (!zone) return;
    if (zone.id === "rulemodal") { s.classList.toggle("on"); return; }
    var panel = s.closest(".panel");
    var scope = panel ? panel.id : "";
    if (scope === "p-settings") {
      var rows = qsa("#p-settings .f-row .switch");
      var si = rows.indexOf(s);
      if (si === 0) {          /* v3.2.5 BUG FIX 6: Start with Windows
                                  ACTUALLY toggles now - POST /autostart
                                  writes/removes the Startup shortcut,
                                  the very same one the tray icon and
                                  Task Manager > Startup apps show */
        var want = !autoStartState;
        s.classList.toggle("on", want);
        api("/autostart", { method: "POST", body: { enabled: want } })
          .then(function(r2){
            autoStartState = !!(r2 && r2.enabled);
            s.classList.toggle("on", autoStartState);
            toast("Start with Windows " + (autoStartState
              ? "ON - the Startup shortcut is created (Task Manager > Startup apps shows it)"
              : "OFF - the Startup shortcut was removed"),
              autoStartState ? "ok" : "warn");
          })
          .catch(function(e){ s.classList.toggle("on", autoStartState);
            toast(e.message, "err"); });
        return;
      }
      if (si === 1) {          /* minimize-to-tray stays a desktop-app
                                  default - the hub window has no tray */
        toast("Minimize to tray is the desktop-app default", "warn");
        return;
      }
    }
    s.classList.toggle("on");
    if (scope === "p-dropzone") {          /* save immediately */
      var v = s.classList.contains("on");
      api("/config", { method: "POST", body: { drop_delete: v } })
        .then(function(){ toast((v ? "Delete" : "Move to done\\") +
          " after printing", v ? "warn" : "ok"); loadDropzone(); })
        .catch(function(e){ toast(e.message, "err"); });
      return;
    }
    swDirty(scope, s);
    swSave(scope);
  });
  /* history inputs dirty flags */
  var hq = document.querySelector("#p-history input.inp");
  if (hq) hq.addEventListener("input", function(){ renderJobs(lastJobs); });
  var hsel = document.querySelectorAll("#p-history select.inp");
  hsel.forEach(function(s2){ s2.addEventListener("change", function(){ renderJobs(lastJobs); }); });
  /* printers default select */
  var psel = document.querySelector("#p-printers select.inp");
  if (psel) psel.addEventListener("change", function(){
    var name = psel.value.replace(/^OS default \u2014 /, "");
    if (name && name !== "OS default") {
      api("/config", { method: "POST", body: { printer: name } })
        .then(function(){ toast(name + " is now the default printer", "ok"); poll(); })
        .catch(function(e){ toast(e.message, "err"); });
    }
  });
}

/* ---------- keyboard shortcuts (design) ---------- */
document.addEventListener("keydown", function(e){
  if (e.key === "Escape"){ closeMenus(); closeModal(); return; }
  if (e.ctrlKey && !e.shiftKey && !e.altKey){
    var map = { "1": "dashboard", "2": "queue", "3": "history", "4": "printers", "5": "lan",
                "6": "dropzone", "7": "connections", "8": "hub" };
    if (map[e.key]){ e.preventDefault(); showTab(map[e.key]); return; }
    if (e.key.toLowerCase() === "n"){ e.preventDefault(); showTab("dropzone"); return; }
    if (e.key.toLowerCase() === "t"){ e.preventDefault(); ACTIONS.testprint(); return; }
    if (e.key.toLowerCase() === "r"){ e.preventDefault(); ACTIONS.restart(); return; }
  }
  if (e.key === "F1"){ e.preventDefault(); showTab("about"); }
  if (e.key === "F5"){ e.preventDefault(); poll(); toast("Refreshed", "ok"); }
});
/* design F5 status-bar toggle replaced by refresh - keep a plain toggle too:
   Ctrl+F5 toggles the status bar */
document.addEventListener("keydown", function(e){
  if (e.ctrlKey && e.key === "F5"){ e.preventDefault();
    var sb = document.querySelector(".statusbar");
    sb.style.display = sb.style.display === "none" ? "flex" : "none"; }
});

/* ---------- window buttons (design) ---------- */
qsa(".winbtn").forEach(function(b){
  b.addEventListener("click", function(){
    if (b.classList.contains("close"))
      toast("Keep the hub running \u2014 close the tab anytime (the tray icon manages the hub)", "warn");
    else if (b.textContent.trim() === "\u2500")
      qsa(".toolbar,.addrbar,.sidebar").forEach(function(el){
        el.style.display = el.style.display === "none" ? "" : "none"; });
    else {
      var d = document.querySelector(".desktop");
      d.style.padding = d.style.padding ? "" : "0";
    }
  });
});

/* ---------- center view restrictions ---------- */
function applyCenterView(){
  if (!IS_CENTER) return;
  var banner = document.createElement("div");
  banner.id = "centerBanner";
  banner.style.cssText = "background:#fff7ed;border:1px solid #fdba74;color:#9a3412;" +
    "border-radius:10px;padding:10px 14px;font-size:12px;line-height:1.55;margin:12px 18px 0";
  banner.innerHTML = "<b>\u26A0 CENTER PC UI</b> \u2014 you are viewing the CENTER printing PC\u2019s hub \u201C" +
    esc(BOOT.host || "center PC") + "\u201D (" + esc(lanBase()) + "). This PC is connected as a child: " +
    "queue, history, rules and IPP print right here; the 14 system tools run on the center PC at its own screen.";
  var content = document.querySelector(".content");
  if (content) content.insertBefore(banner, content.firstChild);
  var tg = $("toolsGrid");
  if (tg) tg.innerHTML = '<div class="note amber" style="grid-column:1/-1">This is the <b>CENTER PC UI</b> ' +
    '\u2014 the 14 system tools run on the center PC itself (open <span class="mono">' +
    esc(lanBase()) + '/ui</span> there). Printing, queue, history, rules and IPP queues work right here.</div>';
}

/* ============================================================
   POLL + BOOT
   ============================================================ */
var VERSION_TXT = BOOT.version || "3.3.3";
async function poll(){
  try {
    var h = await api("/health");
    window._lastHealth = h;   /* v3.2.2: discovery / standard-port chips read this */
    var st = await api("/stats");
    var q = await api("/queue");
    var pr = await api("/printers");
    var jobs = (await api("/jobs?limit=120")).jobs || [];
    var audit = (await api("/audit?limit=60")).audit || auditRows;
    cfgCache = Object.assign(cfgCache, await api("/config"));
    auditRows = audit; pausedState = !!q.paused;
    if (!hubStartTime && h.uptime_s) hubStartTime = Date.now() - h.uptime_s * 1000;
    showOffline(false);
    VERSION_TXT = "v" + (h.version || BOOT.version || "?");
    /* v3.2.5 BUG FIX 6: the REAL Startup-folder state (the same source
       the tray icon reads). The old line read cfgCache.autostart - a
       config.json key the hub never wrote - so the switch showed OFF
       even when autostart was ON (tray said ON, UI said OFF). */
    autoStartState = !!h.autostart;
    renderFrame(h);
    renderStats(h, st, q, pr);
    renderLanRows();
    renderPrinters(pr.printers || []);
    renderJobs(jobs);
    renderRecent(jobs);
    renderAudit(audit);
    renderExt(audit);
    renderSettings(cfgCache);
    renderExtPrefs((cfgCache.ext_prefs || {}));
    /* v3.3.3 SHARE SEND MIRROR: the switch used to render OFF until the
       first /peer/status answer even when share_send was already ON in
       config.json (the boot window again) - flip-and-popup bait. The
       /config value arrives in the main poll body, mirror it here;
       loadLanPeer below re-mirrors it with the authoritative value. */
    var sssw = $("shareSendSw");
    if (sssw && !_shareSendPending) sssw.classList.toggle("on", !!cfgCache.share_send);
    /* v3.3.2 SHARE SEND MODE + remote devices: the LAN PC card and the
       "Show other PCs" switch read the persisted hub state every poll */
    loadLanPeer();
    /* v3.3.3: the peers table now refreshes on every poll too - it only
       rendered on page load before, so a peer that came online stayed
       OFFLINE in the table until a manual reload. /peers is cached
       15 s server-side, so this costs the hub nothing. */
    loadConnections();
    var srsw = $("showRemoteSw");
    if (srsw) srsw.classList.toggle("on", !!cfgCache.show_remote_printers);
    /* v3.2.3 SWITCH FIX part 2: the hub panel now refreshes from the
       live config on every poll - the inputs no longer keep the static
       demo values, and a switch save cannot write them into config.json */
    refreshHubPanel();
    loadDebugPanel();
    renderAbout(h);
  } catch (e) {
    if (e.message === "auth") return;
    showOffline(true);
  }
}
async function boot(){
  clearInterval(pollTimer);
  injectTools();
  bindButtons();
  bindSwitches();
  bindSelections();   /* v3.2.5: History/Queue checkbox selection engine */
  bindPrintDefaults();
  applyCenterView();
  try {
    await api("/health");
    showTokenCard(false);
    localStorage.setItem("advprintHubToken", TOKEN);
    pollTimer = setInterval(poll, 3000);
    await poll();
    loadDropzone(); loadConnections();
  } catch (e) {
    if (e.message === "auth") return;
    showOffline(true);
    pollTimer = setInterval(poll, 3000);
  }
}
boot();
</script>
</body>
</html>
"""






def console_page_bytes(view="self", req_host=None, req_port=0,
                       client_ip=None):
    """v3.2.1 THE ONE UI - the EMBEDDED rev-4 All-in-One console with the
    boot JSON injected. Every route that serves a page to a browser
    (/, /ui, /dashboard) answers with THIS one UI - no separate URLs and
    no external files any more.
    v3.2.9 BUG 3: the boot JSON carries the address THE OPENING DEVICE
    used (Host header) as self_host/self_port, the device's own IP and
    every interface IP of the hub (lan_ips) - the UI builds all printer
    and queue URLs per device instead of one global lan_ip().
    v3.3.0 BUG 2: lan_ips6 (the IPv6 addresses) join the boot JSON so
    the LAN panel lists BOTH stacks."""
    page = CONSOLE_HTML
    boot = {
        "view": "center" if view == "center" else "self",
        "host": (socket.gethostname() or "this PC"),
        "lan_ip": lan_ip(),
        "port": CFG["port"],
        "version": VERSION,
        # v3.2.9 BUG 3: per-device reachability
        "self_host": req_host or "",
        "self_port": int(req_port) if req_port else CFG["port"],
        "client_ip": client_ip or "",
        "lan_ips": list_lan_ips()[:8],
        # v3.3.0 BUG 2: IPv6 addresses for the LAN panel chips
        "lan_ips6": list_lan_ips6()[:6],
    }
    try:
        page = page.replace("__ADVPRINT_BOOT_JSON__",
                            json.dumps(boot).replace("</", "<\\/"))
    except Exception:
        pass
    return page.encode("utf-8")


def dashboard_html(query=""):
    """The built-in web dashboard (v2.0): success rate, queue size,
    printers, live queue, history, audit trail - one file, no assets."""
    q = ("?" + query) if query else ""
    tok = ""
    if "token=" in q:
        tok = q.split("token=", 1)[1].split("&", 1)[0]
    return (DASHBOARD_HTML
            .replace("@@VERSION@@", VERSION)
            .replace("@@BRANDING@@", BRANDING.replace(" - ", " &middot; "))
            .replace("@@Q@@", q)
            .replace("@@TOKEN@@", tok))

def docs_html():
    """v2.2: the full user guide, served by the hub itself at /docs so
    the documentation is ALWAYS inside the product (no website needed)."""
    return (DOCS_HTML
            .replace("@@VERSION@@", VERSION)
            .replace("@@PORT@@", str(CFG.get("port", 9235)))
            .replace("@@CFGPATH@@",
                     html.escape(config_path(), quote=True)))

# Docs live here so they can never be "missing" again - they ship in the
# hub file and are served at http://127.0.0.1:9235/docs?token=...
DOCS_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AdvPrint Pro @@VERSION@@ - User Guide</title>
<style>
 :root{--blue:#1d4ed8;--ink:#0f172a;--mut:#64748b;--ok:#16a34a;
       --bad:#dc2626;--line:#e2e8f0}
 *{box-sizing:border-box;margin:0;padding:0}
 body{font:14px/1.6 "Segoe UI",system-ui,sans-serif;color:var(--ink);
      background:#f5f8fc;padding-bottom:60px}
 header{background:linear-gradient(135deg,#1e3a8a,#1d4ed8);color:#fff;
        padding:22px 32px}
 header h1{font-size:20px}
 header p{font-size:12.5px;opacity:.9;margin-top:4px}
 main{max-width:960px;margin:0 auto;padding:18px 20px}
 nav.toc{background:#fff;border:1px solid var(--line);border-radius:12px;
         padding:14px 18px;margin-bottom:18px;font-size:13.5px}
 nav.toc a{color:var(--blue);text-decoration:none;margin-right:14px;
           white-space:nowrap;line-height:2}
 h2{font-size:17px;margin:26px 0 8px;color:#1e3a8a}
 h3{font-size:14px;margin:16px 0 6px}
 p{margin:7px 0}
 .box{background:#fff;border:1px solid var(--line);border-radius:12px;
      padding:16px 18px;margin:10px 0}
 .tip{background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af;
      border-radius:10px;padding:10px 13px;font-size:13px;margin:10px 0}
 .warn{background:#fef3c7;border:1px solid #fcd34d;color:#92400e;
       border-radius:10px;padding:10px 13px;font-size:13px;margin:10px 0}
 table{width:100%;border-collapse:collapse;font-size:13px;background:#fff;
       border:1px solid var(--line);border-radius:10px;overflow:hidden}
 th{background:#f1f5f9;text-align:left;padding:8px 10px;font-size:11.5px;
    text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
 td{padding:8px 10px;border-top:1px solid #f1f5f9;vertical-align:top}
 code,.mono{font:12.5px/1.6 Consolas,"Courier New",monospace;
            background:#f1f5f9;border:1px solid var(--line);
            border-radius:5px;padding:1px 6px;word-break:break-all}
 pre{background:#0f172a;color:#e2e8f0;border-radius:10px;padding:14px 16px;
     font:12.5px/1.65 Consolas,monospace;overflow-x:auto;margin:10px 0}
 pre b{color:#93c5fd;font-weight:600}
 ol,ul{padding-left:22px;margin:8px 0}
 li{margin:4px 0}
 .ok{color:var(--ok);font-weight:700}
 .no{color:var(--bad);font-weight:700}
 footer{color:var(--mut);font-size:12px;text-align:center;margin-top:30px}
</style></head><body>
<header>
 <h1>AdvPrint Pro @@VERSION@@ - User Guide</h1>
 <p>This page is served by YOUR hub - the documentation is inside the
    product. Open it any time: <code>http://127.0.0.1:@@PORT@@/docs?token=YOUR-TOKEN</code></p>
</header>
<main>
<nav class="toc">
 <a href="#where">Where is every feature</a>
 <a href="#options">All print options</a>
 <a href="#quality">Quality: presets + DPI</a>
 <a href="#lan">LAN sharing (print from other PCs)</a>
 <a href="#queue">Queue on/off + shift to another PC</a>
 <a href="#stuck">Nothing prints? (stuck jobs)</a>
 <a href="#debug">Debug mode (why is it not working?)</a>
 <a href="#laravel">Laravel / PHP auto print</a>
 <a href="#bangla">Bangla receipts</a>
 <a href="#files">Files &amp; endpoints</a>
 <a href="#devapi"><b>Developer API (v3.2.7)</b></a>
</nav>

<h2 id="where">1. Where is every feature (click map)</h2>
<div class="box">
 <ul>
  <li><b>Toolbar popup</b> - queue on/off (Pause), last jobs, token banner.
      <b>Queue mode OFF = instant print</b>: every job goes straight to the
      printer; if no printer is active the job is auto-queued (v2.3).
      <b>v2.7.0:</b> the popup also carries the two LAN switches -
      <b>Share Receive Mode</b> (this PC accepts jobs from other PCs =
      hub share_lan) and <b>Share Send Mode</b> (this browser may shift
      jobs to peer PCs; OFF locks every send-to-PC button here).</li>
  <li><b>Extension Options &rarr; Settings</b> - master switch, queue mode,
      <b>Debug mode</b> (v2.3 - collect errors so problems can be seen,
      not guessed),
      <b>Default print options</b> (copies, pages all/odd/even/custom,
      per-sheet n-up, <b>quality draft/normal/high AND DPI</b>, scale %,
      margins mm, duplex/two-sided, paper size, orientation) - these are
      sent with EVERY job from this browser. Connection (Hub URL + token)
      and auto-print routing rules are here too.</li>
  <li><b>Extension Options &rarr; LAN / PCs</b> - turn LAN sharing on/off,
      copy this hub's LAN URL, list peer PCs, <b>shift the whole queue or a
      single job to another PC</b>.</li>
  <li><b>Extension Options &rarr; Queue</b> - live queue, Pause/Resume,
      per-row Cancel + <b>Shift to PC</b>.</li>
  <li><b>Hub dashboard</b> (<code>/dashboard?token=...</code>) - printers,
      queue, <b>Job history manager (v2.7.0)</b>, audit, <b>LAN sharing
      card</b> (on/off + copy URL), pause, clear, shift-all to a peer PC,
      rotate token, <b>live debug &amp; test tool + SumatraPDF path</b>
      (proper panels inside the page since v2.7.0).</li>
  <li><b>Job history (v2.7.0)</b> - dashboard AND extension Options &rarr;
      History: <b>filter</b> by status (incl. one-click
      "not printed"), <b>search</b> by title / printer / #id, <b>tick</b>
      rows (check / uncheck all), <b>Reprint selected</b>,
      <b>Reprint all non-printed</b> and <b>Clear ALL history</b>
      (finished jobs only - waiting jobs are never touched).</li>
  <li><b>This page</b> - the built-in guide at <code>/docs?token=...</code>.</li>
 </ul>
</div>

<h2 id="options">2. All print options (POST /print)</h2>
<p>Every option works in the JSON API, in <code>window.advprint.print()</code>
   from any web page, and in the extension's <b>Default print options</b>.</p>
<table>
<tr><th style="width:14%">Parameter</th><th style="width:34%">Values</th>
    <th style="width:26%">Windows (SumatraPDF)</th><th>Linux (CUPS)</th></tr>
<tr><td><code>copies</code></td><td>1-50</td><td class="ok">yes</td><td class="ok">yes</td></tr>
<tr><td><code>pages</code></td><td>"1-3,5" &middot; "odd" &middot; "even"</td>
    <td class="ok">yes (incl. odd/even)</td><td class="ok">yes (page-set)</td></tr>
<tr><td><code>duplex</code></td><td>simplex &middot; duplex &middot; duplexlong &middot; duplexshort</td>
    <td class="ok">yes</td><td class="ok">yes</td></tr>
<tr><td><code>paper_size</code></td><td>A4 A5 A3 Letter Legal Tabloid...</td>
    <td class="ok">yes</td><td class="ok">yes (media)</td></tr>
<tr><td><code>per_sheet</code></td><td>1 2 4 6 9 16 (n-up)</td>
    <td class="no">no (driver)</td><td class="ok">yes (number-up)</td></tr>
<tr><td><code>quality</code></td><td>draft &middot; normal &middot; high &middot; <b>600 / "600dpi"</b></td>
    <td class="ok">accepted, driver decides</td><td class="ok">yes (print-quality / printer-resolution)</td></tr>
<tr><td><code>dpi</code></td><td>72-2400 number</td>
    <td class="ok">accepted, driver decides</td><td class="ok">yes</td></tr>
<tr><td><code>scale_pct</code></td><td>25-400</td><td class="ok">for rendered jobs</td><td class="ok">for rendered jobs</td></tr>
<tr><td><code>margin_mm</code></td><td>0-50</td><td class="ok">for rendered jobs</td><td class="ok">for rendered jobs</td></tr>
<tr><td><code>orientation</code></td><td>portrait &middot; landscape</td><td class="ok">yes</td><td class="ok">yes</td></tr>
<tr><td><code>tray</code></td><td>driver name</td><td class="no">no</td><td class="ok">yes (InputSlot)</td></tr>
<tr><td><code>priority</code></td><td>1 (urgent) - 9</td><td colspan="2" class="ok">queue ordering</td></tr>
<tr><td><code>queue</code></td><td>false = print immediately, skip FIFO</td><td colspan="2" class="ok">yes</td></tr>
<tr><td><code>profile</code></td><td>saved profile name</td><td colspan="2" class="ok">named defaults</td></tr>
<tr><td><code>run_at</code></td><td>ISO time or "+30s +5m +2h"</td><td colspan="2" class="ok">scheduled print</td></tr>
<tr><td><code>lang</code></td><td>escpos &middot; zpl (raw bytes)</td><td colspan="2" class="ok">receipt printers</td></tr>
<tr><td><code>watermark</code></td><td>true + watermark_text</td><td colspan="2" class="ok">reprint marking</td></tr>
</table>
<p>Ask any printer what IT supports:
   <code>GET /printers/PRINTER-NAME/capabilities?token=...</code> - returns
   pages/odd-even, copies range, duplex modes, per_sheet list, quality
   presets + DPI list, paper list (live from <code>lpoptions -l</code> on
   Linux).</p>

<h2 id="quality">3. Quality: draft/normal/high AND DPI - both work</h2>
<div class="box">
 <p><b>v2.2:</b> the <code>quality</code> parameter accepts BOTH spellings:</p>
 <pre>curl -X POST http://127.0.0.1:@@PORT@@/print \
  -H "X-AdvPrint-Token: YOUR-TOKEN" \
  -d '{"title":"lab report","pdfUrl":"https://x/r.pdf",
       <b>"quality":"draft"</b>}'          <i># preset -> CUPS print-quality=3</i>

curl -X POST http://127.0.0.1:@@PORT@@/print \
  -H "X-AdvPrint-Token: YOUR-TOKEN" \
  -d '{"title":"photo","pdfUrl":"https://x/p.pdf",
       <b>"quality":"600dpi"</b>}'        <i># DPI -> CUPS printer-resolution=600dpi</i>

<i>// or the dedicated dpi field:</i>
{"title":"invoice","text":"...","kind":"thermal",<b>"dpi":300</b>}</pre>
 <p>In the extension pick from the dropdown:
    <i>Printer default / Draft / Normal / High / 300 dpi / 600 dpi /
    1200 dpi</i> - or type any DPI. On Linux both are sent to CUPS exactly;
    on Windows the print driver keeps control (the choice is accepted,
    stored on the job and logged so you can see what was requested).</p>
</div>
<h2 id="lan">4. LAN sharing - print from OTHER PCs (restored)</h2>
<div class="box">
 <p>The hub by default listens only on this PC (127.0.0.1). Turn on
    <b>LAN sharing</b> and every PC/phone in your network can print
    through it:</p>
 <ol>
  <li><b>Turn it on</b> - pick ONE:<br>
      &bull; Extension Options &rarr; <b>LAN / PCs</b> tab &rarr; "Enable LAN sharing"<br>
      &bull; Hub dashboard &rarr; "LAN sharing &amp; other PCs" card &rarr; Enable<br>
      &bull; API: <code>POST /config</code> with <code>{"share_lan": true}</code></li>
  <li><b>v2.8.2: it applies INSTANTLY.</b> The hub keeps its loopback
      listener on <code>127.0.0.1:@@PORT@@</code> (local printing never
      stops) and starts a SECOND listener on this PC's LAN IP, e.g.
      <code>192.168.0.50:@@PORT@@</code> - no hub restart needed, and
      disabling the switch stops the LAN listener at once. If the
      router gives the PC a new IP (DHCP), the listener follows it
      automatically within seconds.</li>
  <li><b>Firewall (Windows)</b> - the dashboard shows the state and a
      one-click <b>Allow in firewall</b> button (also in the tray
      menu); it adds this rule after one UAC prompt:
      <pre>netsh advfirewall firewall add rule name="AdvPrint Pro" dir=in ^
  action=allow protocol=TCP localport=@@PORT@@</pre>
      The button lives at dashboard &rarr; LAN card &rarr;
      <i>Windows firewall</i> row. <b>Test LAN</b> (same row) checks
      the listener from the hub itself: if it passes but a DIFFERENT
      PC still cannot connect, it is the firewall.</li>
  <li><b>From another PC</b> - pick ONE:<br>
      &bull; Install the same extension there and set <b>Hub URL</b> to
      <code>http://192.168.0.50:@@PORT@@</code> + the same token<br>
      &bull; Or call the API from any program:
      <pre>curl -X POST http://192.168.0.50:@@PORT@@/print \
  -H "X-AdvPrint-Token: YOUR-TOKEN" \
  -d '{"title":"from pc2","pdfBase64":"JVBERi0...","copies":2}'</pre></li>
 </ol>
 <p class="warn"><b>Security:</b> remote IPs keep the 10-wrong-tokens &rarr;
    5-minute lockout. Only PCs with YOUR token can print. Turn sharing off
    the same way when you do not need it.</p>
 <h3 style="margin:16px 0 4px">QR code - phones print without any install
     (v2.8.1)</h3>
 <p>Dashboard &rarr; LAN card &rarr; <b>Send portal (phones)</b> row:
    <b>Copy send URL</b> copies
    <span class="mono">http://&lt;this-PC-ip&gt;:@@PORT@@/send?token=...</span>,
    and <b>QR code</b> shows the same URL as a QR generated inside the hub
    (no internet, no CDN). Any phone/tablet on the same Wi-Fi scans it,
    opens the Send portal, picks a PDF - it prints on this PC's default
    printer seconds later. API equivalent:
    <code>GET /qr?token=...&amp;kind=send|invite</code> returns the QR as
    SVG (<span class="mono">kind=send</span> = the phone upload URL,
    <span class="mono">kind=invite</span> = the PC invite link below).</p>
 <h3 style="margin:16px 0 4px">One-click invite - connect another PC in
     10 seconds (v2.8.1)</h3>
 <p>Dashboard &rarr; LAN card &rarr; <b>Connect another PC</b> row:
    <b>Copy invite link</b> copies
    <span class="mono">http://&lt;this-PC-ip&gt;:@@PORT@@/connect?t=&lt;token&gt;&amp;n=&lt;PC-name&gt;</span>.
    Open that link in a browser on the OTHER PC (chat, e-mail, QR - any
    way). It shows a confirmation page with an
    <b>Add &quot;PC-name&quot; as a LAN print peer</b> button; clicking it
    saves this hub into the other PC's <span class="mono">peer_hubs</span>
    automatically (its hub answers on
    <span class="mono">http://127.0.0.1:@@PORT@@/peer-connect</span>) and
    verifies it is online. No retyping the IP, no config.json editing.</p>
 <p class="warn"><b>Invite security:</b> the link carries this hub's token
    - treat it like a password (anyone with it can print here). The peer
    entry is only written after an explicit click, only from the target
    PC itself (loopback), only for private-LAN addresses, and only when
    the confirming page was served by exactly the hub being added
    (Origin check) - a random website cannot silently inject a peer.
    Peers appear in the LAN card and can be removed there or in
    config.json; every accept is audited
    (<span class="mono">peer.connected</span>).</p>
</div>

<h2 id="queue">5. Queue on/off + instant print + shift to another PC</h2>
<div class="box">
 <p><b>Queue on/off:</b> popup Pause button, Options &rarr; Queue &rarr;
    Pause/Resume, dashboard "Pause queue", or
    <code>POST /queue/pause</code> / <code>POST /queue/resume</code>.</p>
 <p><b>Instant (direct) print mode - v2.3:</b> Settings &rarr; <b>Queue mode
    OFF</b> (or <code>POST /print</code> with <code>"queue": false</code> /
    <code>"mode": "instant"</code>) hands every job straight to the printer
    the moment it arrives - nothing waits behind earlier jobs and Pause has
    no effect. <b>If no printer is active</b> (offline / paper-out / error)
    the job is <b>auto-queued</b> instead of failing: it waits in the queue
    (with the usual printer-status hold) and prints automatically when the
    printer is back. Turn the fallback off with
    <code>POST /config {"instant_auto_queue": false}</code>.</p>
 <p><b>Shift to another PC</b> (uses the LAN URL of that PC):</p>
 <ul>
  <li>Extension Options &rarr; Queue tab: each row has a <b>Shift to PC</b>
      selector; the LAN/PCs tab shifts <b>the whole waiting queue</b>.</li>
  <li>Dashboard: "LAN sharing &amp; other PCs" card has
      <b>Shift all waiting jobs</b> per peer.</li>
  <li>API: <pre>POST /queue/shift
{"target":"http://192.168.0.60:@@PORT@@",
 "target_token":"PEER-TOKEN",   <i>// optional if it is in peer_hubs</i>
 "scope":"all"}                  <i>// or "job" + "ids":[12,13]</i></pre>
      Jobs are re-uploaded to the target hub, marked <b>forwarded</b> here,
      and audited. Add fixed peers in config:
      <code>"peer_hubs": [{"url":"http://192.168.0.60:@@PORT@@",
      "token":"..."}]</code> in <span class="mono">@@CFGPATH@@</span>.</li>
 </ul>
</div>

<h2 id="stuck">5b. Jobs stay queued - nothing prints? (v2.2.1)</h2>
<div class="box">
 <p>The OK icon only means <b>the hub accepted the job</b>. If no paper
    comes out, the cause is now always visible - check in this order:</p>
 <ol>
  <li><b>Queue paused?</b> The popup shows <span class="st held">PAUSED</span>
      in red. Resume it (popup Pause button or dashboard
      "Resume queue").</li>
  <li><b>Printer-status hold?</b> Held jobs are
      <span class="st held">held</span> with the reason written below
      them (usually "Windows reports the printer offline"). Remedies:
      press <b>Print now</b> on the job (popup, Options &rarr; History,
      or the dashboard queue) - it bypasses pause and the hold - or
      switch OFF "Printer status hold" in the dashboard's LAN card, or
      fix the Windows printer tile (uncheck "Use Printer Offline").</li>
  <li><b>Backend error?</b> <span class="st failed">failed</span> jobs
      show the real error (SumatraPDF missing, CUPS lp missing, wrong
      printer name). The extension also raises a red <b>!</b> badge and
      a notification within a minute.</li>
  <li><b>Worker crashed?</b> Fixed in v2.2.1 - the queue worker is
      exception-proof and a watchdog respawns it (audit events
      <span class="mono">worker.error</span> /
      <span class="mono">worker.restarted</span>).</li>
 </ol>
 <p>API for one job: <code>GET /jobs/{id}</code> &middot; force it out:
    <code>POST /jobs/{id}/print-now</code>.</p>
</div>

<h2 id="debug">5c. Debug mode - WHEN / WHY / WHERE is the problem? (v2.3)</h2>
<div class="box">
 <p>Instead of guessing, switch Debug ON and let the system tell you:</p>
 <ol>
  <li><b>Turn Debug ON</b> - pick ONE:<br>
      &bull; Extension Options &rarr; Settings &rarr; <b>Debug mode</b><br>
      &bull; Hub dashboard &rarr; <b>Debug</b> card &rarr; Enable<br>
      &bull; API: <code>POST /config</code> with <code>{"debug": true}</code></li>
  <li><b>Reproduce the print once</b> (print any page / test page).</li>
  <li><b>Open the Debug tab</b> - Extension Options &rarr; <b>Debug</b>, or
      <code>http://127.0.0.1:@@PORT@@/debug?token=YOUR-TOKEN</code>. You get:
      <ul>
       <li><b>problems</b> - the hub's own verdict list (worker dead, queue
           paused, printer offline + held jobs, SumatraPDF/browser missing,
           failed jobs with their real error) each with a FIX;</li>
       <li><b>client_reports</b> - the errors the <b>browser extension (JS)</b>
           and the desktop tool hit: network failures, rejected tokens,
           parked jobs, print-call exceptions - with source, level, time
           and context;</li>
       <li><b>recent_jobs</b> - the last 15 jobs with status + error;</li>
       <li>worker/queue/printer state, and the <b>Copy report</b> button
           for a bug report you can paste anywhere.</li>
      </ul></li>
 </ol>
 <p class="tip">API: <code>GET /debug</code> (token like every GET) &middot;
    clients report errors with
    <code>POST /debug/report {"source":"extension","level":"error","message":"...","job_id":12}</code>.
    The hub keeps the last 100 reports (debug_reports.json). Debug OFF =
    no client collection, verbose <span class="mono">[DEBUG]</span> log
    lines off - normal quiet operation.</p>
</div>

<h2 id="laravel">6. Laravel / PHP - scheduled &amp; automatic printing</h2>
<div class="box">
 <p>Three proven patterns (full code in <b>docs/LARAVEL.md</b> in the
    package):</p>
 <h3>a) Print service + token header</h3>
 <pre>class AdvPrintService {
  public static function printPdf(string $url, array $opt = []): array {
    $res = Http::withHeaders(['X-AdvPrint-Token' =&gt; config('services.advprint.token')])
      -&gt;post(config('services.advprint.url', 'http://127.0.0.1:@@PORT@@').'/print',
        array_merge(['pdf_url' =&gt; $url, 'title' =&gt; 'laravel',
                     'copies' =&gt; 1, 'quality' =&gt; 'normal'], $opt));
    return $res-&gt;throw()-&gt;json();
  }
}</pre>
 <h3>b) Time-based automatic printing (schedule:run + cron every minute)</h3>
 <pre><i>// app/Console/Kernel.php</i>
protected function schedule(Schedule $schedule): void {
  $schedule-&gt;call(fn () =&gt; AdvPrintService::printDailyReports())
           -&gt;dailyAt('08:00');
  $schedule-&gt;call(fn () =&gt; AdvPrintService::printPendingInvoices())
           -&gt;everyFiveMinutes();
}
<i>// server crontab:  * * * * * php /var/www/artisan schedule:run</i></pre>
 <h3>c) Event-driven (a row created &rarr; print instantly)</h3>
 <pre><i>// in your controller / observer / job</i>
AdvPrintService::printPdf($report-&gt;pdf_url,
    ['title' =&gt; 'LAB-'.$report-&gt;id, 'printer' =&gt; 'LabPrinter',
     'pages' =&gt; '1-2', 'copies' =&gt; 2, 'quality' =&gt; 'high']);

<i>// or queued for reliability: PrintJob::dispatch($report);</i>
<i>// or webhook: POST /print from your own webhook receiver</i></pre>
 <p>Delayed printing without cron: send <code>"run_at": "+30m"</code> -
    the hub itself fires the job later (survives restarts, stored in the
    SQLite queue).</p>
</div>

<h2 id="bangla">7. Bangla (বাংলা) on thermal receipt printers</h2>
<div class="box">
 <p>ESC/POS code pages (cp437 etc.) contain <b>no Bangla glyphs</b> - a
    font table inside the printer cannot render them, on ANY vendor. So
    the hub does shaping + rendering itself:
    <code>thermal_text_engine = auto</code> (default) detects non-Latin
    text and renders the receipt with headless Chrome using
    <b>Nirmala UI / Noto Sans Bengali</b>, then prints it as a raster
    image - correct conjuncts, correct ligatures.</p>
 <ul>
  <li>Pure-Latin receipts keep the fast built-in font path.</li>
  <li>Install a Bangla font once: Windows ships Nirmala UI already; Linux:
      <code>sudo apt install fonts-noto-bengali</code>.</li>
  <li>Force either engine: <code>"thermal_text_engine": "text|browser"</code>
      in <span class="mono">@@CFGPATH@@</span>.</li>
  <li>Legacy printer firmware that maps a Bangla code page (rare) can set
      <code>"escpos_codepage"</code> and skip the browser path.</li>
 </ul>
</div>

<h2 id="files">8. Files &amp; quick endpoint map</h2>
<div class="box">
 <ul>
  <li>Config: <span class="mono">@@CFGPATH@@</span> - port, token,
      share_lan, printer, peer_hubs, profiles, escpos_codepage,
      thermal_text_engine...</li>
  <li>Logs: tray menu &rarr; Open log, or <code>/diagnostics?token=...</code>.</li>
  <li><code>/health</code> &middot; <code>/stats</code> &middot;
      <code>/printers</code> &middot; <code>/printers/{name}/capabilities</code>
      &middot; <code>/jobs</code> &middot; <code>/queue</code> &middot;
      <code>/audit</code> &middot; <code>/peers</code> &middot;
      <code>/config</code> &middot; <code>/docs</code> (this page) &middot;
      <b><code>/debug</code></b> (v2.3 - why is nothing printing) - all GET
      with <code>?token=</code> or the header.</li>
  <li>POST: <code>/print</code> &middot; <code>/queue/pause|resume|clear|shift</code>
      &middot; <code>/jobs/{id}/cancel|retry|reprint</code> &middot;
      <code>/token/rotate</code> &middot; <code>/config</code> &middot;
      <b><code>/debug/report</code></b> (v2.3 - client error reports) -
      header only.</li>
 </ul>
</div>

<h2 id="devapi">9. Developer API &mdash; <code>window.advprint</code> + <code>POST /print</code> (v3.2.7)</h2>
<div class="box">
 <p>Three ways to print, one pipeline. Everything lands in the same
    queue, History and audit &mdash; a job from JavaScript and a job from
    <code>curl</code> are identical afterwards.</p>
 <table>
 <tr><th style="width:26%">Channel</th><th>How</th><th style="width:22%">Needs extension?</th></tr>
 <tr><td><code>window.advprint</code></td>
     <td>injected into every http(s) page; every method returns a Promise
         with the hub JSON</td><td>yes</td></tr>
 <tr><td><code>POST /print</code></td>
     <td>plain HTTP + token &mdash; any language, any PC on the LAN</td>
     <td><b>no</b></td></tr>
 <tr><td><code>ipp://&lt;ip&gt;:9235/ipp/print</code> + RAW 9100</td>
     <td>the hub IS a printer (OS Add-printer, phones, label apps)</td>
     <td><b>no</b></td></tr>
 </table>
</div>

<h3>9a. <code>window.advprint</code> &mdash; every method</h3>
<div class="box">
<pre>await window.advprint.status();            // hub health  (GET /health)
await window.advprint.printers();          // [{name, is_default, status}]
await window.advprint.history(20);         // last jobs   (GET /jobs)
await window.advprint.printPage({title});  // print the current page
await window.advprint.printPdf(url, {title, printer}); // with login cookies
await window.advprint.printPdfLink(url, 'Title');      // + browser fallback
await window.advprint.print({
  title: 'Receipt 12', printer: '', copies: 1,
  priority: 1,                    // 1 = urgent first (9 = low, default 5)
  pages: '1-3,5',                 // range - 'odd' / 'even' too
  per_sheet: 2,                   // n-up (CUPS)
  quality: 'draft',               // draft|normal|high|'600'|'600dpi'
  dpi: 600,                       // explicit DPI 72-2400
  scale_pct: 150, margin_mm: 8,   // html/text renders
  duplex: 'duplex', paper_size: 'A4', orientation: 'landscape',
  tray: 'Tray2',                  // CUPS
  profile: 'Invoice',             // hub print profile
  destination: 'printer',         // or 'file' = archive as PDF
  queue: false,                   // false = INSTANT (own thread, parallel)
  run_at: '+5m',                  // ISO or +Ns/+Nm/+Nh/+Nd   (v3.2.7)
  dedupe: false,                  // allow identical repeats   (v3.2.7)
  watermark: true, watermark_text: 'COPY',
  reason: 'ward copy',            // recorded in the audit trail
  text: '|center|HELLO',          // payload: exactly ONE of -
  lang: 'escpos',                 //   text(+lang) | html | pageUrl
  html: '&lt;h1&gt;Invoice&lt;/h1&gt;',  //   | pdfBase64 | pdfUrl | rawBase64
  pdfBase64: 'JVBERi0...', pdfUrl: 'https://.../report.pdf'
});</pre>
 <p>Resolves with <code>{ok, job_id, kind, copies, queue_mode, instant,
    auto_queued, duplicate, priority, status, message}</code>; a failure
    resolves <code>{ok:false, error}</code> (only <code>printPdfLink</code>
    rejects, after opening its fallback tab). Full camelCase reference:
    <code>docs/DEVELOPER-API.md</code> in the install folder.</p>
</div>

<h3>9b. Direct HTTP from any language</h3>
<div class="box">
<pre>curl -X POST http://127.0.0.1:9235/print \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"pdf_base64":"JVBERi0...","title":"Invoice 42","printer":"HP LaserJet Pro","copies":2}'

# raw PDF body - no base64 (-33%), options on the query string
curl -X POST "http://127.0.0.1:9235/print?title=Lab%20report&amp;copies=1" \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/pdf" \
  --data-binary @report.pdf

# ZPL label straight to the Zebra (kind=raw = bytes are not PDF)
curl -X POST "http://127.0.0.1:9235/print?kind=raw&amp;lang=zpl&amp;printer=Zebra%20GK420t" \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/octet-stream" \
  --data-binary $'^XA^PW400^LL0160^FO30,30^A0N,36,30^FDHELLO^FS^XZ'</pre>
 <p>Payload sources (first match wins): raw body (%PDF or kind=raw) &middot;
    <code>raw_base64</code> &middot; <code>text</code>+<code>lang</code>
    &middot; <code>pdf_base64</code> &middot; <code>pdf_url</code> (25 MB,
    private-address guard) &middot; <code>image_base64</code> (JPEG) &middot;
    <code>html</code> &middot; <code>page_url</code> &middot; plain
    <code>text</code> (thermal/A4, Bangla via browser engine). Token via
    header <b>or</b> <code>?token=</code> <b>or</b> JSON
    <code>"token"</code>; multipart and the CSP form-payload fallback work
    too. From LAN PCs use <code>http://&lt;lan-ip&gt;:9235/print</code> &mdash;
    printing follows the Allowed-IPs list, the console UI stays
    local-only.</p>
</div>

<h3>9c. One PC, MANY printers &mdash; the real cases</h3>
<div class="box">
 <ul>
  <li><b>Targeting:</b> <code>printer:""</code> = hub destination &middot;
      exact name (typos self-heal) &middot; group name = first ready member
      &middot; <code>destination:"file"</code> = archive. One job = one
      printer: send one call per printer (the dedupe key includes the
      printer, so the same PDF to 3 printers is 3 jobs, never blocked).</li>
  <li><b>Parallel printing:</b> Queue Mode prints one-by-one (priority
      first). <code>"queue": false</code> prints <b>instantly in its own
      thread</b> &mdash; receipt on the thermal roll + invoice on the laser
      at the same moment:</li>
 </ul>
<pre>await Promise.all([
  window.advprint.print({title:'Order 12', printer:'XP-80C Thermal',
                         queue:false, text:'|center|#big MY SHOP\n...\n|cut|'}),
  window.advprint.print({title:'Invoice 12', printer:'HP LaserJet Pro',
                         queue:false, pdfBase64: b64})
]);</pre>
 <ul>
  <li><b>What serializes:</b> the FIFO worker (queue mode) &middot; headless
      renders max 2 at a time &middot; dedupe 5 min window. Instant jobs,
      raw jobs and LAN callers all run in parallel.</li>
  <li><b>Many PCs, one hub:</b> every PC POSTs to
      <code>http://&lt;lan-ip&gt;:9235/print</code> &mdash; each request gets
      its own thread and job id; a PDF from PC-A and a ZPL label from
      PC-B print side by side (raw jobs skip the offline probe).</li>
 </ul>
</div>

<h3>9d. Raw printing &mdash; ESC/POS receipts &amp; ZPL labels</h3>
<div class="box">
 <p><b>ESC/POS markers</b> (text + <code>lang:"escpos"</code>, the
    default): <code>#big </code> double size &middot;
    <code>|center|</code> / <code>|right|</code> &middot;
    <code>|cut|</code> &middot; <code>|drawer|</code> &middot;
    <code>|barcode:12345|</code> &middot; <code>|qr:text|</code>. The
    banner, feed and final cut are added automatically; Bangla/Unicode
    plain text renders through the browser engine.</p>
 <p><b>ZPL is verbatim:</b> <code>lang:"zpl"</code> encodes the text
    latin-1 and sends it untouched &mdash; YOU supply the full
    <code>^XA...^XZ</code>, the <code>^PW</code>/<code>^LL</code> label
    size and <code>^PQ</code> quantity (or send <code>copies</code>).
    Delivery: Windows winspool RAW &middot; Linux <code>lp -o raw</code>
    &middot; upstream IP printer &rarr; direct 9100/631 socket.</p>
</div>

<h3>9e. URL &amp; token map</h3>
<div class="box">
 <table>
 <tr><th>URL</th><th>Purpose</th><th>Token</th></tr>
 <tr><td><code>http://127.0.0.1:9235/print</code></td><td>print API (this PC)</td><td>required</td></tr>
 <tr><td><code>http://&lt;lan-ip&gt;:9235/print</code></td><td>print API from other PCs</td><td>required</td></tr>
 <tr><td><code>ipp://&lt;ip&gt;:9235/ipp/print</code></td><td>Add-printer URL (OS)</td><td>none</td></tr>
 <tr><td><code>.../ipp/print/&lt;slug&gt;</code></td><td>per-printer queue (<code>HP LaserJet Pro</code> &rarr; <code>hp-laserjet-pro</code>)</td><td>none</td></tr>
 <tr><td>TCP 9100</td><td>RAW JetDirect listener</td><td>none</td></tr>
 <tr><td><code>/send?token=</code></td><td>phone upload portal</td><td>token</td></tr>
 <tr><td><code>/jobs?limit=</code> &middot; <code>/jobs/{id}</code></td><td>watch jobs</td><td>token</td></tr>
 <tr><td><code>/ui</code></td><td>console &mdash; local-only PC (v3.2.6)</td><td>token</td></tr>
 </table>
 <p><code>ipp://</code> is for the OS Add-printer dialog;
    <code>http://</code> is for browsers/code (the QR encodes http://
    since v3.2.6). Every option is also accepted on the query string.</p>
</div>

<footer>AdvPrint Pro @@VERSION@@ &middot; by Bit Dream IT &middot; MIT license
 &middot; 100% local - no cloud, no tracking</footer>
</main>
</body></html>"""

DASHBOARD_AUTH_ERROR_TMPL = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AdvPrint Pro - dashboard needs the current token</title>
<style>
 body{font-family:"Segoe UI",system-ui,sans-serif;background:#f1f5f9;margin:0;
      display:flex;min-height:100vh;align-items:center;justify-content:center}
 .c{background:#fff;max-width:600px;width:92%;border-radius:12px;
    padding:26px 32px;box-shadow:0 4px 24px rgba(15,23,42,.08);
    border-top:4px solid #dc2626}
 h1{font-size:19px;margin:0 0 10px;color:#0f172a}
 p{color:#334155;line-height:1.55;margin:8px 0}
 ol{color:#334155;line-height:1.85;padding-left:22px;margin:10px 0}
 code{background:#f1f5f9;border:1px solid #e2e8f0;border-radius:4px;
      padding:1px 6px;font-size:12.5px;word-break:break-all}
 .m{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;
    border-radius:8px;padding:9px 12px;font-size:13px;word-break:break-word}
 .f{color:#64748b;font-size:12px;margin-top:14px;line-height:1.5}
</style></head><body><div class="c">
<h1>AdvPrint Pro - dashboard needs the current token</h1>
<div class="m">__MSG__</div>
<p>The token in this link is not the hub's current token. This often
happens when a bookmark still uses the old default token
<code>PrintHub-2024</code>, or the token was rotated recently.</p>
<div id="fixbox" style="display:none;margin:14px 0">
<button id="fixbtn" style="background:#16a34a;border-color:#16a34a;color:#fff;
  border:0;border-radius:9px;padding:12px 20px;font:700 15px
  'Segoe UI',system-ui;cursor:pointer">Fix it now - open the dashboard
  with the current token</button>
<button id="copybtn" style="margin-left:8px;border:1px solid #cbd5e1;
  background:#fff;border-radius:9px;padding:12px 16px;font:600 13px
  'Segoe UI',system-ui;cursor:pointer">Copy current token</button>
<div id="fixmsg" style="margin-top:8px;font-size:13px;color:#166534"></div>
</div>
<ol>
<li><b>Tray icon (easiest)</b> - right-click the AdvPrint Pro tray icon
and choose <i>Open dashboard</i>. It always opens with the right token.</li>
<li><b>Command line</b> - run <code>@@CLICMD@@</code> (full path -
works from any folder), then open
<code>/dashboard?token=THE-TOKEN</code>.</li>
<li><b>Config file</b> - the token is the <code>"token"</code> value in
<code>%USERPROFILE%\.advprint\config.json</code>
(Linux/Mac: <code>~/.advprint/config.json</code>).</li>
</ol>
<p class="f">Tip: after changing or rotating the token, also update it in
the extension (AdvPrint Pro Options - Hub token) and replace old dashboard
bookmarks. Since v2.0.1 a wrong token in one Chrome window can no longer
lock out the other windows - the hub never locks the loopback IP
127.0.0.1 by default.</p>
<script>
// One-click fix: this page itself is served by the hub, so asking the
// hub it came from for the current token works ONLY on the hub PC
// (loopback). The endpoint refuses remote IPs, so nothing leaks.
(function(){
 fetch(location.origin+"/token/current",{cache:"no-store"})
 .then(function(r){if(!r.ok)throw 0;return r.json();})
 .then(function(d){
   if(!d||!d.ok||!d.token)throw 0;
   document.getElementById("fixbox").style.display="block";
   document.getElementById("fixbtn").onclick=function(){
     location="/dashboard?token="+encodeURIComponent(d.token);};
   document.getElementById("copybtn").onclick=function(){
     (navigator.clipboard?navigator.clipboard.writeText(d.token):
      Promise.reject()).then(function(){
        document.getElementById("fixmsg").textContent=
          "Token copied - paste it into AdvPrint Pro Options > Hub token.";},
      function(){
        document.getElementById("fixmsg").textContent=
          "Token: "+d.token;});};
 })
 .catch(function(){/* remote PC: keep manual steps only */});
})();
</script>
</div></body></html>
"""


def dashboard_auth_error_html(message=""):
    """Friendly browser page when the dashboard token is wrong/missing."""
    msg = html.escape(str(message or "invalid or missing token"), quote=True)
    return (DASHBOARD_AUTH_ERROR_TMPL
            .replace("__MSG__", msg)
            .replace("@@CLICMD@@", html.escape(cli_cmd("token"), quote=True)))


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AdvPrint Pro Dashboard</title>
<style>
  :root{--blue:#1d4ed8;--ink:#0f172a;--mut:#64748b;--ok:#16a34a;
        --bad:#dc2626;--warn:#d97706;--bg:#f1f5f9;--card:#fff;}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:14px/1.5 "Segoe UI",system-ui,sans-serif;color:var(--ink);
       background:var(--bg);min-height:100vh}
  header{background:linear-gradient(135deg,#1e3a8a,#1d4ed8);color:#fff;
         padding:18px 24px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  header .logo{width:34px;height:34px;border-radius:8px;background:#fff;
         color:var(--blue);font-weight:800;display:flex;align-items:center;
         justify-content:center;font-size:19px}
  header h1{font-size:18px;flex:1}
  header small{display:block;font-size:11px;opacity:.85;font-weight:400}
  main{max-width:1100px;margin:0 auto;padding:18px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:12px;margin-bottom:16px}
  .card{background:var(--card);border:1px solid #e2e8f0;border-radius:12px;
        padding:14px 16px}
  .card b{font-size:24px;display:block}
  .card span{color:var(--mut);font-size:12px}
  .warn{background:#fef3c7;border:1px solid #fcd34d;color:#92400e;
        padding:10px 14px;border-radius:10px;margin-bottom:14px;font-size:13px}
  .warn button{float:right}
  h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;
     color:var(--mut);margin:18px 0 8px}
  /* v2.9.1 RESPONSIVE TABLES: panels no longer hide columns behind an
     inner horizontal scrollbar - cells wrap instead, so EVERY column,
     button and option is visible on load at any window width. */
  .panel{background:var(--card);border:1px solid #e2e8f0;border-radius:12px;
         padding:6px 12px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{color:var(--mut);text-align:left;font-weight:600;padding:7px 8px;
     border-bottom:1px solid #eef2f7}
  td{padding:7px 8px;border-bottom:1px solid #f4f7fb;white-space:normal;
     overflow-wrap:anywhere;word-break:break-word;vertical-align:top}
  .st{font-size:11px;font-weight:700;padding:2px 8px;border-radius:9px;
      white-space:nowrap;display:inline-block;overflow-wrap:normal;
      word-break:normal}
  .st.printed,.st.queued,.ready{background:#dcfce7;color:#166534}
  .st.printing,.st.forwarded{background:#dbeafe;color:#1e40af}
  .st.saved,.st.scheduled{background:#fef9c3;color:#854d0e}
  .st.held{background:#ffedd5;color:#9a3412}
  .st.dead,.st.failed,.st.canceled,.offline,.paper-out,.error{background:#fee2e2;color:#991b1b}
  .ready{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:9px}
  .offline,.paper-out,.error{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:9px}
  button{border:1px solid #dbe2ee;background:#fff;border-radius:7px;
         padding:5px 10px;font:600 12px "Segoe UI",system-ui;cursor:pointer;
         white-space:nowrap;overflow-wrap:normal;word-break:normal}
  button:hover{border-color:var(--blue);color:var(--blue)}
  button.primary{background:var(--blue);border-color:var(--blue);color:#fff}
  .bar{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}
  #msg{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);
       background:#0f172a;color:#fff;padding:9px 16px;border-radius:9px;
       font-size:13px;display:none;max-width:80vw;z-index:9}
  /* v2.7.0: inputs, checkboxes + history toolbar - the live test tool
     and the Job history manager now live INSIDE <main> (proper panel
     styling, no more broken full-width section below the page). */
  input[type=text],input[type=search],select{border:1px solid #dbe2ee;
       border-radius:7px;padding:5px 9px;font:600 12px "Segoe UI",system-ui;
       color:var(--ink);background:#fff;outline:none}
  input[type=text]:focus,input[type=search]:focus,select:focus{border-color:var(--blue)}
  input[type=checkbox]{width:15px;height:15px;accent-color:var(--blue);cursor:pointer}
  .hbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 8px}
  .hbar label{font-size:13px;color:#334155;display:flex;gap:6px;align-items:center}
  .hbar .cnt{font:700 12px "Segoe UI",system-ui;color:var(--blue);
       background:#dbeafe;border-radius:9px;padding:3px 10px}
  .ltbox{padding:12px 12px 14px}
  .ltbox p{font-size:13px;color:#334155;margin:2px 0 10px}
  #ltOut{margin:4px 0 2px;max-height:260px;overflow:auto;white-space:pre-wrap}
  .verbadge{font:700 11px "Segoe UI",system-ui;background:rgba(255,255,255,.14);
       border:1px solid rgba(255,255,255,.35);border-radius:9px;padding:3px 10px}
  .paging{display:flex;gap:8px;align-items:center;margin-top:8px;font-size:12px;color:var(--mut)}
  /* v2.9.1: form controls must never push their row into a scroll -
     they shrink/wrap instead, and the IP printer fields stack cleanly. */
  input[type=text],input[type=search],select{max-width:100%}
  .hbar label{max-width:100%}
  #destIpWrap{display:none;flex-wrap:wrap;gap:8px;align-items:center}
  @media (max-width:640px){
    main{padding:10px}
    header{padding:14px 12px}
    .cards{grid-template-columns:repeat(2,1fr)}
    table{font-size:12px}
    th,td{padding:6px 5px}
    button{padding:6px 9px}
  }
</style></head><body>
<header>
  <div class="logo"><svg viewBox="0 0 64 64" width="30" height="30" aria-label="AdvPrint Pro - A + printer logo"><defs><linearGradient id="lgA" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2563eb"/><stop offset="1" stop-color="#1e3a8a"/></linearGradient></defs><rect x="1" y="1" width="62" height="62" rx="14" fill="url(#lgA)"/><path d="M14 52 L32 12 L50 52" fill="none" stroke="#fff" stroke-width="8.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M22 39.5 H42" stroke="#fff" stroke-width="8.5" stroke-linecap="round"/><rect x="24.5" y="43.5" width="15" height="13" rx="2" fill="#fff"/><rect x="27.5" y="47" width="9" height="1.9" rx="0.9" fill="#1d4ed8"/><rect x="27.5" y="51" width="6.5" height="1.9" rx="0.9" fill="#1d4ed8"/></svg></div>
  <h1>AdvPrint Pro <small>@@BRANDING@@</small></h1>
  <span class="verbadge">v@@VERSION@@</span>
  <button class="primary" onclick="rotateToken()">Rotate token</button>
</header>
<main>
  <div class="warn" id="tokWarn" style="display:none">
    You are still using the DEFAULT token. Everyone who knows
    "PrintHub-2024" can print on this PC.
    <button onclick="rotateToken()">Rotate now</button>
  </div>
  <div class="bar">
    <button id="bPause" onclick="togglePause()">Pause queue</button>
    <button onclick="if(confirm('Cancel every waiting job?'))act('/queue/clear')">Clear queue</button>
    <a href="/docs@@Q@@"><button><b>Docs (user guide)</b></button></a>
    <a href="/export/history.csv@@Q@@"><button>History CSV</button></a>
    <a href="/audit.csv@@Q@@"><button>Audit CSV</button></a>
    <a href="/diagnostics@@Q@@"><button>Diagnostics JSON</button></a>
    <a href="/debug@@Q@@"><button><b>Debug</b></button></a>
    <a href="/send@@Q@@"><button title="v2.8: upload a PDF from any device on the LAN - no extension needed"><b>Send portal</b></button></a>
    <button onclick="restartHub()" title="v2.8: clean relaunch - the hub restarts itself and comes back in a few seconds">Restart hub</button>
    <button onclick="location='/health'">Health JSON</button>
  </div>
  <div class="cards">
    <div class="card"><b id="cRate">-</b><span>success rate (7 days)</span></div>
    <div class="card"><b id="cQueue">-</b><span>queue size</span></div>
    <div class="card"><b id="cToday">-</b><span>jobs today</span></div>
    <div class="card"><b id="cPrinters">-</b><span>printers ready</span></div>
    <div class="card"><b id="cVer">v@@VERSION@@</b><span>hub version</span></div>
  </div>
  <h2>LAN sharing &amp; other PCs <small style="text-transform:none;letter-spacing:0">&nbsp;- v2.2: share this printer over the network, shift jobs to another PC</small></h2>
  <div class="panel" id="lanCard"><table><tbody id="lanBody">
    <tr><td>Loading LAN status...</td></tr></tbody></table></div>
  <h2>DropZone - print WITHOUT the extension <small style="text-transform:none;letter-spacing:0">&nbsp;- v2.8: save a PDF into the folder, AdvPrint prints it (works from any Windows app, MS Word style)</small></h2>
  <div class="panel ltbox" id="dzCard">
    <div class="hbar">
      <b>DropZone: </b><span id="dzState" class="st queued">loading...</span>
      <span class="mono" id="dzDirShow" style="color:var(--mut)"></span>
      <span style="flex:1"></span>
      <button onclick="dzOpen()">Open folder</button>
      <button id="dzToggleBtn" onclick="dzToggle()">Disable</button>
    </div>
    <div class="hbar">
      <label style="flex:1;min-width:280px">Watched folder (empty = data folder + DropZone):
        <input type="text" id="dzDir" style="width:100%" placeholder="C:\Users\you\Desktop\DropZone"></label>
      <button onclick="dzSave()">Save</button>
      <label style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="dzDelete"> delete the PDF after printing (otherwise moved to done\)</label>
    </div>
    <p style="font-size:13px;color:#334155;margin:2px 0 0">Print from ANY app without the extension: <b>Print</b> &rarr; choose <b>Microsoft Print to PDF</b> &rarr; save the PDF into the DropZone folder. AdvPrint Pro prints it seconds later (the file moves to <span class="mono">done\</span>). Phones/tablets print through the <b>Send portal</b> button above (or <span class="mono">/send</span>) - also 100% local.</p>
  </div>
  <h2>Debug <small style="text-transform:none;letter-spacing:0">&nbsp;- v2.3: WHY is nothing printing? one card, one answer</small></h2>
  <div class="panel" id="dbgCard"><table><tbody id="dbgBody">
    <tr><td>Loading debug status...</td></tr></tbody></table></div>
  <h2>Live debug &amp; test tool <small style="text-transform:none;letter-spacing:0">&nbsp;- send a REAL print and watch every step live (v@@VERSION@@)</small></h2>
  <div class="panel ltbox" id="livetest">
    <p>Send a REAL test print and watch every step live until it hits the
       printer - or see exactly why it did not (offline, held, SumatraPDF...).</p>
    <div class="hbar">
      <label>Printer: <input type="text" id="ltPrinter" size="24" placeholder="(default printer)"></label>
      <button onclick="ltSend()">Send test print &amp; watch live</button>
      <button onclick="ltRelease()">Release ALL held jobs</button>
      <button class="primary" onclick="ltFull()">Full self-test (A-to-Z check)</button>
    </div>
    <pre id="ltOut">idle - click the button above</pre>
  </div>
  <h2>Hub settings <small style="text-transform:none;letter-spacing:0">&nbsp;- SumatraPDF.exe override (empty = auto-find on every print)</small></h2>
  <div class="panel ltbox">
    <div class="hbar">
      <label style="flex:1;min-width:280px">SumatraPDF.exe full path:
        <input type="text" id="ltSumatra" style="width:100%" placeholder="C:\Users\you\AppData\Local\SumatraPDF\SumatraPDF.exe"></label>
      <button onclick="ltSaveSumatra()">Save</button>
      <span id="ltCfgMsg" style="font-size:12px;color:var(--mut)"></span>
    </div>
  </div>
  <h2>Print destination <small style="text-transform:none;letter-spacing:0">&nbsp;- v2.9: ANY printer - OS default / selected / IP printer (network)</small></h2>
  <div class="panel ltbox">
    <div class="hbar">
      <label>Print to: <select id="destSel" onchange="destPick()"></select></label>
      <span id="destIpWrap">
        <label>IP: <input type="text" id="destIp" size="15" placeholder="e.g. 192.168.1.50"></label>
        <label>Port: <input type="text" id="destPort" size="5" placeholder="auto"></label>
        <select id="destProto">
          <option value="raw">RAW (JetDirect 9100)</option>
          <option value="ipp">IPP</option>
        </select>
      </span>
      <button class="primary" onclick="destSave()">Save destination</button>
      <button onclick="destTest()">Test</button>
      <span id="destMsg" style="font-size:12px;color:var(--mut)"></span>
    </div>
    <p style="font-size:13px;color:#334155;margin:2px 0 0">Where every job prints: the OS <b>default printer</b>, <b>any installed printer</b> (picked from the list), or an <b>IP printer</b> - a real network printer at IP:port (RAW&nbsp;9100 or IPP). PCs and phones that added <i>this</i> hub as their network printer print through exactly this destination, so one setting routes everything.</p>
  </div>
  <h2>Browser extension - silent install <small style="text-transform:none;letter-spacing:0">&nbsp;- v@@VERSION@@: Chrome/Edge/Brave install the extension BY POLICY - no chrome://extensions, no Load unpacked</small></h2>
  <div class="panel ltbox">
    <div class="hbar">
      <span class="mono">ID: <span id="extId">-</span></span>
      <span class="mono">CRX v<span id="extVer">-</span></span>
      <button class="primary" onclick="extPolicyInstall()">Silent-install into Chrome/Edge/Brave (this user)</button>
      <button onclick="extPolicyStatus()">Check policy</button>
      <button onclick="extPolicyRemove()">Remove policy</button>
      <button onclick="extCopyUrl()">Copy updates.xml URL</button>
      <span id="extMsg" style="font-size:12px;color:var(--mut)"></span>
    </div>
    <p style="font-size:13px;color:#334155;margin:2px 0 0">The hub serves the <b>signed extension package</b> at <span class="mono">/extension/updates.xml</span> + <span class="mono">/extension/AdvPrint-Pro.crx</span> (open endpoints - Chrome's updater sends no token). The Windows Setup already wrote the force-install policy for <b>all users</b> (HKLM); this button writes the same policy for <b>your user</b> (HKCU) - use it when Chrome was installed after Setup or the hub port changed. Chrome/Edge honor it <b>silently on domain-joined PCs</b> (schools, workplaces); on a normal home PC Chrome ignores non-store force-install - those users load the extension once via chrome://extensions &gt; Load unpacked (files sit in the install folder). Linux: the deb package writes /etc/*/policies/managed/advprint-pro.json. Every hub release ships a new .crx, so Chrome updates the extension automatically whenever this page shows a higher version.</p>
  </div>
  <h2>Printers</h2>
  <div class="panel" id="printers"><table><tbody>
    <tr><td>Loading printers...</td></tr></tbody></table></div>
  <h2>Queue (waiting + printing)</h2>
  <div class="panel"><table><thead><tr>
    <th>#</th><th>Title</th><th>Printer</th><th>Status</th><th></th>
  </tr></thead><tbody id="queue"><tr><td>-</td></tr></tbody></table></div>
  <h2>Job history <small style="text-transform:none;letter-spacing:0">&nbsp;- v2.7.0: filter, tick, REPRINT selected / non-printed, clear ALL</small></h2>
  <div class="panel" style="padding:10px 12px">
    <div class="hbar">
      <select id="hFilter" onchange="HIST.page=1;renderHistory()">
        <option value="">All statuses</option>
        <option value="printed">Printed</option>
        <option value="queued">Queued</option>
        <option value="printing">Printing</option>
        <option value="held">Held</option>
        <option value="scheduled">Scheduled</option>
        <option value="failed">Failed</option>
        <option value="dead">Dead</option>
        <option value="canceled">Canceled</option>
        <option value="saved">Saved (file)</option>
        <option value="forwarded">Forwarded</option>
        <option value="not_printed">Not printed (failed + dead + canceled)</option>
      </select>
      <input type="search" id="hSearch" size="24" placeholder="Search title / printer / #id..." oninput="HIST.page=1;renderHistory()">
      <select id="hLimit" onchange="loadHistory()">
        <option value="50">load last 50</option>
        <option value="100" selected>load last 100</option>
        <option value="300">load last 300</option>
        <option value="1000">load last 1000</option>
      </select>
      <span class="cnt" id="hSelCnt">0 selected</span>
      <span style="flex:1"></span>
      <button class="primary" onclick="reprintSelected()">Reprint selected</button>
      <button onclick="reprintNotPrinted()">Reprint non-printed</button>
      <button onclick="clearHistory()">Clear ALL history</button>
      <button onclick="loadHistory()">Refresh</button>
    </div>
    <table><thead><tr>
      <th style="width:26px;padding-right:0"><input type="checkbox" id="hAllTop" title="check / uncheck ALL rows on this page" onchange="toggleAllHistory(this.checked)"></th>
      <th>#</th><th>Time</th><th>Title</th><th>Printer</th><th>Status</th><th></th>
    </tr></thead><tbody id="jobs"><tr><td>-</td></tr></tbody></table>
    <div class="paging">
      <button id="hPrev" onclick="HIST.page--;renderHistory()">&larr; newer</button>
      <span id="hPage">-</span>
      <button id="hNext" onclick="HIST.page++;renderHistory()">older &rarr;</button>
    </div>
  </div>
  <h2>Audit trail (latest events)</h2>
  <div class="panel"><table><thead><tr>
    <th>Time</th><th>Event</th><th>Job</th><th>Site / IP</th><th>Printer</th><th>Reason / details</th>
  </tr></thead><tbody id="audit"><tr><td>-</td></tr></tbody></table></div>
</main>
<div id="msg"></div>
<script>
/* v2.7.0 NOTE: the "Live debug & test tool" + "Hub settings" panels now
   live INSIDE <main> (see above) - the old <section id="livetest"> after
   </main> broke the layout (full-width, unstyled, below the page). */
const Q = location.search || "";
const TOKEN = "@@TOKEN@@";
const H = {"X-AdvPrint-Token": new URLSearchParams(Q).get("token") || ""};
function msg(t){const m=document.getElementById("msg");m.textContent=t;
  m.style.display="block";setTimeout(()=>m.style.display="none",4000);}
/* v2.7.0 FIX: query strings used to be GLUED as
   "/jobs?limit=12" + "?token=..." -> "?limit=12?token=..." which the
   hub cannot parse - the dashboard's Recent jobs / Audit tables were
   ALWAYS empty on a real install (every dashboard link carries a
   token). withQ() joins the token with "&" when the path already has
   a "?", and jget() additionally sends the token header. */
function withQ(p){return Q?p+((p.indexOf("?")>=0)?"&":"?")+Q.slice(1):p;}
async function jget(p){const r=await fetch(withQ(p),{headers:H});
  return r.json();}
async function act(p,body){const r=await fetch(withQ(p),{method:"POST",
  headers:Object.assign({"Content-Type":"application/json"},H),
  body:JSON.stringify(body||{})});return r.json();}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));}
async function extInfo(){try{const d=await jget("/extension/info");
  document.getElementById("extId").textContent=d.extension_id||"-";
  document.getElementById("extVer").textContent=d.version||"-";
}catch(_){}}
async function extMsgSet(t){document.getElementById("extMsg").textContent=t;}
async function extPolicyInstall(){await extMsgSet("writing policy...");
  try{const d=await act("/extension/policy/install",{});
  await extMsgSet(d.ok?(d.message||"policy written - restart the browser once"):(d.note||d.error||"failed"));}
  catch(e){await extMsgSet("failed: "+e);}}
async function extPolicyStatus(){try{const d=await jget("/extension/policy/status");
  if(!d.platform||d.platform==="windows"){const parts=[];for(const[k,v]of Object.entries(d.browsers||{}))parts.push(k+": "+(v.present?("present ("+v.hive+" "+v.value+")"):"absent"));
  await extMsgSet(parts.join(" | ")||"no browser policy found");}else{await extMsgSet(d.note||"linux uses /etc/*/policies/managed/advprint-pro.json");}}
  catch(e){await extMsgSet("failed: "+e);}}
async function extPolicyRemove(){try{const d=await act("/extension/policy/remove",{});
  await extMsgSet(d.message||"done");}catch(e){await extMsgSet("failed: "+e);}}
async function extCopyUrl(){try{await navigator.clipboard.writeText(location.origin+"/extension/updates.xml");
  await extMsgSet("updates.xml URL copied");}catch(e){await extMsgSet("copy failed: "+e);}}
async function refresh(){
  try{
    const st=await jget("/stats");
    document.getElementById("cRate").textContent=
      st.success_rate==null?"-":st.success_rate+"%";
    document.getElementById("cQueue").textContent=st.queue_size;
    document.getElementById("cToday").textContent=st.jobs_today;
    const pr=st.printers_ready;
    document.getElementById("cPrinters").textContent=
      pr+"/"+Object.keys(st.printers||{}).length;
    document.getElementById("bPause").textContent=
      st.paused?"Resume queue":"Pause queue";
    if(st.default_token_warning)
      document.getElementById("tokWarn").style.display="block";
    let ph="";
    for(const[n,s]of Object.entries(st.printers||{}))
      ph+="<tr><td>"+esc(n)+"</td><td><span class='st "+esc(s)+"'>"+
          esc(s)+"</span></td></tr>";
    if(!ph)ph="<tr><td>No printers detected.</td></tr>";
    document.querySelector("#printers tbody").innerHTML=ph;
    const q=await jget("/queue");
    const jobs=await jget("/jobs?limit=12");
    let qh="";
    for(const j of (jobs.jobs||[]).filter(j=>
        ["queued","printing","held","scheduled"].includes(j.status))){
      qh+="<tr><td>"+j.id+"</td><td>"+esc(j.title)+"</td><td>"+
          esc(j.printer||"default")+"</td><td><span class='st "+esc(j.status)+
          "'>"+esc(j.status)+(j.held_reason?" - "+esc(j.held_reason):"")+
          "</span></td><td><button onclick=\"act('/jobs/"+j.id+
          "/cancel').then(()=>{refresh();loadHistory();})\">Cancel</button> "+
          (j.status!=="printing"?"<button onclick=\"act('/jobs/"+j.id+"/print-now').then(()=>{refresh();loadHistory();})\">Print now</button> "+
          "<button onclick=\"shiftJob("+j.id+")\">Shift</button>":"")+"</td></tr>";
    }
    document.getElementById("queue").innerHTML=
      qh||"<tr><td>Queue is empty.</td></tr>";
    /* v2.7.0: the old "Recent jobs" rendering moved out of refresh() -
       the Job history manager below owns the #jobs table now (it loads
       its own rows, keeps filter/checkboxes and pages 50 per view). */
    const a=await jget("/audit?limit=10");
    let ah="";
    for(const e of (a.entries||[])){
      ah+="<tr><td>"+esc((e.ts||"").replace("T"," "))+"</td><td>"+
          esc(e.event)+"</td><td>"+(e.job_id||"")+"</td><td>"+
          esc(e.site||e.ip||"")+"</td><td>"+esc(e.printer||"")+"</td><td>"+
          esc(e.reason||e.details||"")+"</td></tr>";
    }
    document.getElementById("audit").innerHTML=
      ah||"<tr><td>No audit events yet.</td></tr>";
  }catch(e){msg("hub offline? "+e.message);}
}
async function togglePause(){
  const st=await jget("/queue");
  await act("/queue/"+(st.paused?"resume":"pause"));
  refresh();
}
/* ---- v2.7.0: Job history - filter, search, tick, bulk reprint, clear ----
   Owns the #jobs table (the old "Recent jobs"). State:
   HIST.rows  = what the hub returned for the selected load-limit
   HIST.page  = page within the FILTERED rows (50 rows per page)
   SELECTED   = Set of ticked job ids - survives re-render/refresh */
const HIST={rows:[],page:1,per:50};
const SELECTED=new Set();
async function loadHistory(){
  try{
    const lim=(document.getElementById("hLimit")||{}).value||100;
    const f=(document.getElementById("hFilter")||{}).value||"";
    const st=(f&&f!=="not_printed")?("&status="+encodeURIComponent(f)):"";
    const d=await jget("/jobs?limit="+lim+st);
    HIST.rows=d.jobs||[];
    renderHistory();
  }catch(e){/* hub briefly offline - the next tick retries */}
}
function histFiltered(){
  const f=(document.getElementById("hFilter")||{}).value||"";
  const s=((document.getElementById("hSearch")||{}).value||"").trim().toLowerCase();
  let rows=HIST.rows;
  if(f==="not_printed")
    rows=rows.filter(j=>["failed","dead","canceled"].includes(j.status));
  if(s)
    rows=rows.filter(j=>(j.title||"").toLowerCase().includes(s)||
                        (j.printer||"").toLowerCase().includes(s)||
                        String(j.id)===s.replace("#",""));
  return rows;
}
function renderHistory(){
  const rows=histFiltered();
  const per=HIST.per, pages=Math.max(1,Math.ceil(rows.length/per));
  if(HIST.page>pages)HIST.page=pages;
  if(HIST.page<1)HIST.page=1;
  const start=(HIST.page-1)*per, pageRows=rows.slice(start,start+per);
  let h="";
  for(const j of pageRows){
    h+="<tr><td><input type='checkbox' "+(SELECTED.has(j.id)?"checked":"")+
       " title='tick to reprint' onchange='histCheck("+j.id+",this.checked)'></td>"+
       "<td>"+j.id+"</td><td>"+esc((j.created_at||"").replace("T"," "))+"</td>"+
       "<td>"+esc(j.title)+"</td><td>"+esc(j.printer||"default")+"</td>"+
       "<td><span class='st "+esc(j.status)+"'>"+esc(j.status)+
       (j.held_reason?" - "+esc(j.held_reason):"")+"</span></td><td>";
    if(["failed","dead","canceled"].includes(j.status))
      h+="<button onclick=\"const p=prompt('Retry on which printer? (empty = same)');"+
         "if(p!==null)act('/jobs/"+j.id+"/retry',{printer:p}).then(()=>{loadHistory();refresh();})\">Retry</button> ";
    else if(j.status!=="printing"&&j.status!=="forwarded")
      h+="<button onclick=\"const r=prompt('Reprint - reason?');"+
         "if(r!==null)act('/jobs/"+j.id+"/reprint',{reason:r}).then(()=>{loadHistory();refresh();})\">Reprint</button>";
    h+="</td></tr>";
  }
  const f=(document.getElementById("hFilter")||{}).value||"";
  const s=((document.getElementById("hSearch")||{}).value||"").trim();
  document.getElementById("jobs").innerHTML=h||
    "<tr><td colspan='7'>No jobs"+((f||s)?" match this filter.":" yet.")+"</td></tr>";
  document.getElementById("hSelCnt").textContent=SELECTED.size+" selected";
  document.getElementById("hPage").textContent=rows.length?
    ("showing "+(start+1)+"-"+Math.min(start+per,rows.length)+" of "+rows.length+" (page "+HIST.page+"/"+pages+")"):
    "0 jobs";
  const all=document.getElementById("hAllTop");
  const pageIds=pageRows.map(j=>j.id);
  const selPage=pageIds.filter(i=>SELECTED.has(i)).length;
  all.checked=pageIds.length>0&&selPage===pageIds.length;
  all.indeterminate=selPage>0&&selPage<pageIds.length;
}
function histCheck(id,on){on?SELECTED.add(id):SELECTED.delete(id);renderHistory();}
function toggleAllHistory(on){
  const rows=histFiltered().slice((HIST.page-1)*HIST.per,HIST.page*HIST.per);
  for(const j of rows)on?SELECTED.add(j.id):SELECTED.delete(j.id);
  renderHistory();
}
async function reprintSelected(){
  if(!SELECTED.size)return msg("Tick one or more jobs in the history first.");
  if(!confirm("Reprint "+SELECTED.size+" selected job(s)?"))return;
  const r=await act("/jobs/bulk-reprint",{ids:[...SELECTED]});
  if(r.ok)msg("Reprint queued: "+r.queued+" job(s)"+
              (r.skipped?(" - "+r.skipped+" skipped (original file gone)"):""));
  else msg(r.error||"bulk reprint failed");
  SELECTED.clear();loadHistory();refresh();
}
async function reprintNotPrinted(){
  if(!confirm("Reprint EVERY failed / dead / canceled job in the history (up to 500)?"))return;
  const r=await act("/jobs/bulk-reprint",{scope:"not_printed"});
  if(r.ok)msg("Reprint queued: "+r.queued+" job(s)"+
              (r.skipped?(" - "+r.skipped+" skipped (original file gone)"):""));
  else msg(r.error||"bulk reprint failed");
  SELECTED.clear();loadHistory();refresh();
}
async function clearHistory(){
  if(!confirm("Delete ALL finished jobs (printed / failed / dead / canceled / forwarded / saved) from the history?\n"+
              "Waiting jobs (queued / held) are NOT touched.\nThis cannot be undone - export the CSV first if unsure."))return;
  const r=await act("/history/clear",{});
  if(r.ok)msg(r.message||("History cleared - "+r.deleted+" job(s) removed"));
  else msg(r.error||"clear failed");
  SELECTED.clear();loadHistory();refresh();
}
/* ---- v2.2: LAN sharing card + queue shift ---- */
let PEERS=[],HEALTH=null;
async function loadLan(){
  try{
    const hl=await jget("/health");
    HEALTH=hl;
    const b=document.getElementById("lanBody");
    if(!b)return;
    const on=!!hl.share_lan;
    const active=!!hl.lan_active;
    HOLD_OFF=hl.hold_offline!==false;
    try{const qq=await jget("/queue");HELD_N=qq.held||0;}catch(_){HELD_N=0;}
    const url=hl.lan_url||("http://<this-PC-ip>:"+location.port);
    let rows="<tr><td><b>LAN sharing: </b>"+(on?"<span class='st queued'>ON</span>":"<span class='st held'>OFF</span>")+"</td>"+
      "<td class='mono'>"+esc(on?url:"127.0.0.1 (this PC only)")+"</td>"+
      "<td><button onclick='toggleLan("+(on?"false":"true")+")'>"+(on?"Disable":"Enable")+"</button> "+
      (on?"<button onclick='copyLan()'>Copy URL</button>":"")+"</td></tr>";
    if(on&&!active)
      rows+="<tr><td colspan='3'><b>The LAN listener is NOT running</b> (the setting is saved but the bind failed) - toggle LAN sharing off/on once, then check hub.log. Local printing on 127.0.0.1 is NOT affected.</td></tr>";
    if(on){
      /* v2.8.1: send-portal URL + QR (phones print without any install)
         and the one-click invite link for another PC. */
      const HOST=hl.hostname||"this PC";
      SEND_URL=url+"/send?token="+TOKEN;
      INVITE_URL=url+"/connect?t="+TOKEN+"&n="+encodeURIComponent(HOST);
      rows+="<tr><td><b>Send portal (phones): </b><span class='st queued'>QR ready</span></td>"+
        "<td class='mono' id='sendUrlCell'>"+esc(SEND_URL)+"</td>"+
        "<td><button onclick='copySend()'>Copy send URL</button> <button onclick='showQr(\"send\")'>QR code</button></td></tr>";
      rows+="<tr><td><b>Connect another PC: </b><span class='st queued'>1-click</span></td>"+
        "<td class='mono'>"+esc(INVITE_URL)+"</td>"+
        "<td><button onclick='copyInvite()'>Copy invite link</button> <button onclick='showQr(\"invite\")'>QR</button></td></tr>";
      /* v2.9.0: NETWORK PRINTER rows - add this PC like a physical IP
         printer from Windows ("add a printer") or phone print services. */
      IPP_URL=url+"/ipp/print";
      /* v2.9: IP PRINTER MODE - the one row that says it all: other
         devices add THIS PC as their network printer, this PC prints
         every job to the configured destination (default / selected /
         IP printer). */
      const ippMode=!!hl.ip_printer_mode;
      rows+="<tr><td><b>IP Printer mode: </b>"+(ippMode?"<span class='st queued'>ACTIVE</span>":"<span class='st held'>OFF</span>")+"</td>"+
        "<td class='mono'>every PC or phone adds this PC as their network printer &rarr; jobs print to "+esc(hl.dest_display||"(default printer)")+"</td>"+
        "<td>"+(ippMode?"":"<button onclick='ippModeOn()'>Turn on</button> ")+"<button onclick='showQr(\"ipp\")'>QR</button></td></tr>";
      if(hl.ipp_printer!==false){
        rows+="<tr><td><b>Network printer (IPP): </b><span class='st queued'>READY</span></td>"+
          "<td class='mono' id='ippUrlCell'>"+esc(IPP_URL)+"</td>"+
          "<td><button onclick='copyIpp()'>Copy printer URL</button> <button onclick='showQr(\"ipp\")'>QR</button></td></tr>";
      } else {
        rows+="<tr><td><b>Network printer (IPP): </b><span class='st held'>OFF</span></td>"+
          "<td class='mono'>set \"ipp_printer\": true in config.json to enable</td><td></td></tr>";
      }
      const rawPort=hl.raw_printer_port||0;
      if(rawPort>0){
        rows+="<tr><td><b>RAW printer port: </b>"+(hl.raw_active?"<span class='st queued'>LISTENING</span>":"<span class='st held'>starting...</span>")+"</td>"+
          "<td class='mono'>"+esc(hl.lan_ip||"this-PC-ip")+":"+rawPort+" (JetDirect)</td>"+
          "<td><button onclick='rawHow()'>How to add</button></td></tr>";
        rows+="<tr><td colspan='3'><small><b>Add this PC as a printer (like Windows adds a network device):</b> on the other PC - Settings &rarr; Printers &rarr; Add device &rarr; Add manually &rarr; <b>Add a printer using TCP/IP address</b> &rarr; IP <b>"+esc(hl.lan_ip||"this-PC-ip")+"</b>, port <b>"+rawPort+"</b>, device type <b>Generic Network Card</b> (RAW). Or add by URL: <b>"+esc(IPP_URL)+"</b> (Windows 10/11 installs it with the built-in IPP Class Driver). Phones: use the Send portal QR above, or a print service that accepts a manual IPP address.</small></td></tr>";
      }
      /* v2.8.2: firewall status + one-click allow + server-side LAN
         self-test - answers 'why can the other PC not connect?' */
      if(hl.os==="windows"){
        const fw=hl.firewall_ok;
        rows+="<tr><td><b>Windows firewall: </b>"+(fw===true?"<span class='st queued'>ALLOWED</span>":fw===false?"<span class='st held'>BLOCKED</span>":"<span class='st held'>unknown</span>")+"</td>"+
          "<td class='mono'>"+(fw===false?"other PCs cannot connect until TCP "+location.port+" is allowed":fw===true?"inbound TCP "+location.port+" allowed for LAN PCs":"click the button, then accept the Windows UAC prompt")+"</td>"+
          "<td>"+(fw===true?"":"<button onclick='fwAllow()'>Allow in firewall</button> ")+"<button onclick='lanSelftest()'>Test LAN</button></td></tr>";
      } else {
        rows+="<tr><td><b>LAN check: </b></td><td class='mono'>does the listener answer on this PC's LAN IP?</td><td><button onclick='lanSelftest()'>Test LAN</button></td></tr>";
      }
    }
    rows+="<tr><td><b>Printer status hold: </b>"+(HOLD_OFF?"<span class='st queued'>ON</span>":"<span class='st held'>OFF</span>")+"</td><td class='mono'>jobs wait while the printer reports offline</td><td><button onclick='toggleHold(+(!HOLD_OFF))'>"+(HOLD_OFF?"Disable":"Enable")+"</button></td></tr>";
    try{const pr=await jget("/peers");PEERS=(pr&&pr.peers)||pr||[];}catch(_){PEERS=[];}
    for(const p of (PEERS||[])){
      rows+="<tr><td><span class='st "+(p.alive?"queued":"offline")+"'>peer "+(p.alive?"online":"offline")+"</span> "+esc(p.url)+" <small>"+esc(p.version||"")+"</small></td>"+
        "<td></td><td><button onclick=\"shiftAll('"+esc(p.url)+"')\">Shift all waiting jobs</button></td></tr>";
    }
    if(!(PEERS||[]).length)
      rows+="<tr><td colspan='3'><small>Easiest: press <b>Copy invite link</b> above and open it on the other PC - it connects itself. Advanced: add fixed peer PCs (\"peer_hubs\") in config.json - see <a href='/docs@@Q@@'>Docs</a>.</small></td></tr>";
    rows+="<tr id='qrRow' style='display:none'><td colspan='3'></td></tr>";
    b.innerHTML=rows;
    renderQr();
  }catch(e){}
}
/* ---- v2.8.1: send-portal QR + one-click invite helpers ---- */
let SEND_URL="",INVITE_URL="",IPP_URL="",QR_OPEN=null;
function renderQr(){
  const tr=document.getElementById("qrRow"); if(!tr)return;
  if(!QR_OPEN){tr.style.display="none";return;}
  const kind=(QR_OPEN==="invite")?"invite":(QR_OPEN==="ipp")?"ipp":"send";
  const cap=(kind==="invite")
    ?"Scan on the OTHER PC (or send it the link below) - opening it offers a one-click \u201cAdd as LAN print peer\u201d button:"
    :(kind==="ipp")
    ?"Scan on the OTHER PC to add this PC as a NETWORK PRINTER (IPP): Windows 10/11 accepts this URL under 'Select a shared printer by name'. For phones, the Send portal QR is easier:"
    :"Scan with ANY phone on this Wi-Fi - it opens the Send portal: pick a PDF, it prints here. No app, no extension:";
  const u=(kind==="invite")?INVITE_URL:(kind==="ipp")?IPP_URL:SEND_URL;
  tr.style.display="";
  tr.innerHTML="<td colspan='3'><div style='display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap'>"+
    "<img src='"+withQ("/qr?kind="+kind)+"' alt='QR code' width='160' height='160' style='border:1px solid #e2e8f0;border-radius:8px;background:#fff'>"+
    "<div style='flex:1;min-width:220px'><b>"+cap+"</b>"+
    "<div class='mono' style='margin:6px 0;word-break:break-all'>"+esc(u)+"</div>"+
    "<button onclick='copyQr()'>Copy this URL</button> <button onclick='showQr(null)'>Close</button></div></div></td>";
}
function showQr(kind){ QR_OPEN=(kind&&QR_OPEN!==kind)?kind:null; renderQr(); }
function copySend(){
  if(SEND_URL&&navigator.clipboard)navigator.clipboard.writeText(SEND_URL)
    .then(()=>msg("Send URL copied - share it with phones on this Wi-Fi (or scan the QR)"));
}
function copyInvite(){
  if(INVITE_URL&&navigator.clipboard)navigator.clipboard.writeText(INVITE_URL)
    .then(()=>msg("Invite link copied - open it in a browser on the other PC and click Add as LAN print peer"));
}
function copyIpp(){
  if(IPP_URL&&navigator.clipboard)navigator.clipboard.writeText(IPP_URL)
    .then(()=>msg("Printer URL copied - on another PC: Add printer > 'Select a shared printer by name' > paste it"));
}
function rawHow(){
  const ip=(HEALTH&&HEALTH.lan_ip)||"this-PC-ip";
  const port=(HEALTH&&HEALTH.raw_printer_port)||9100;
  msg("On the other PC: Add printer > 'Add a printer using TCP/IP address' > IP "+ip+", port "+port+", device type 'Generic Network Card' - then pick the driver of your real printer. Windows renders the file there; this hub prints it here.");
}
function copyQr(){
  const u=(QR_OPEN==="invite")?INVITE_URL:(QR_OPEN==="ipp")?IPP_URL:SEND_URL;
  if(u&&navigator.clipboard)navigator.clipboard.writeText(u).then(()=>msg("URL copied"));
}
let HOLD_OFF=true,HELD_N=0;
async function toggleHold(on){
  const r=await act("/config",{hold_offline:on});
  if(r.ok)msg(on?"Printer status hold ON - jobs wait while the printer reports offline/out of paper.":"Printer status hold OFF - jobs are sent to the printer even when Windows reports it offline (fixes stuck-queued when the status is misreported).");
  else msg(r.error||"failed");
  setTimeout(loadLan,400);
}
async function toggleLan(on){
  /* v2.8.2: applies LIVE - the hub starts/stops the LAN listener inside
     this request. No restart, and 127.0.0.1 never stops answering. */
  msg(on?"Enabling LAN sharing - starting the LAN listener...":"Disabling LAN sharing - stopping the LAN listener...");
  const r=await act("/config",{share_lan:on});
  if(r.ok&&r.lan&&r.lan.rebound&&!r.lan.lan_error)
    msg(on?"LAN sharing ON - other PCs can connect RIGHT NOW (no restart needed). If one still cannot: click 'Test LAN', then 'Allow in firewall'."
          :"LAN sharing OFF - this PC only (127.0.0.1) again. Local printing never stopped.");
  else if(r.ok&&r.lan&&r.lan.lan_error)
    msg("LAN sharing saved, but the LAN listener could not start: "+r.lan.lan_error);
  else if(r.ok&&r.lan&&r.lan.note)
    msg(r.lan.note);
  else if(r.ok)
    msg("LAN sharing saved.");
  else msg(r.error||"failed");
  setTimeout(()=>{loadLan();loadDest();refresh();},400);
}
async function ippModeOn(){
  /* v2.9: ONE click - this PC BECOMES the network printer for every
     device on the LAN (IPP printer URL + RAW 9100 port) and prints
     every incoming job to the destination picked in "Print
     destination" (default / selected / IP printer). */
  msg("Turning on IP Printer mode...");
  const body={share_lan:true,ipp_printer:true};
  if(!(HEALTH&&HEALTH.raw_printer_port>0))body.raw_printer_port=9100;
  const r=await act("/config",body);
  if(r.ok)msg("IP Printer mode ON - on any PC or phone add THIS PC as a printer: "+IPP_URL+" (or the RAW port 9100). Every job prints to the destination set in 'Print destination'.");
  else msg(r.error||"failed");
  setTimeout(()=>{loadLan();loadDest();refresh();},400);
}
async function fwAllow(){
  /* v2.8.2: one-click Windows firewall fix (single UAC prompt). */
  msg("Adding the firewall rule - ACCEPT the Windows UAC prompt...");
  const r=await act("/firewall/allow",{});
  if(r.ok)msg("Firewall rule added - LAN PCs can now reach the hub. Try printing from the other PC.");
  else msg(r.error||"could not add the rule");
  setTimeout(loadLan,600);
}
async function lanSelftest(){
  /* v2.8.2: the hub connects to its own LAN URL - proves the listener
     is up. A DIFFERENT PC still failing after this = firewall. */
  msg("Testing the LAN listener from the hub itself...");
  try{
    const r=await jget("/lan/selftest");
    if(r.ok)msg("LAN listener OK - "+r.url+" answers. If a DIFFERENT PC still cannot connect, it is the firewall: click 'Allow in firewall'.");
    else msg("LAN test FAILED - "+r.url+" - "+(r.error||"?")+" "+(r.hint||""));
  }catch(e){msg("LAN test failed: "+e);}
}
function copyLan(){
  /* v2.8.1: anchor to the FIRST row - the new send/invite rows below
     also use .mono cells, so the old loose selector could grab one of
     those instead of the LAN sharing URL. */
  const u=document.querySelector("#lanBody tr:first-child .mono");
  if(u&&navigator.clipboard)navigator.clipboard.writeText(u.textContent).then(()=>msg("LAN URL copied: "+u.textContent));
}
async function shiftAll(url){
  if(!confirm("Shift ALL waiting jobs to "+url+"?"))return;
  const r=await act("/queue/shift",{scope:"all",target:url});
  if(r.ok)msg(r.message||("shifted "+r.shifted_count+" job(s)"));
  else msg(r.error||"shift failed");
  refresh();
}
async function shiftJob(id){
  const def=((PEERS||[]).filter(p=>p.alive).map(p=>p.url)[0])||"";
  const t=prompt("Shift job #"+id+" to which PC? (the OTHER AdvPrint's LAN URL, e.g. http://192.168.0.60:9235)",def);
  if(!t)return;
  const r=await act("/queue/shift",{scope:"job",ids:[id],target:t.trim()});
  if(r.ok)msg(r.message||"shifted");
  else msg(r.error||"shift failed");
  refresh();
}
/* ---- v2.3: Debug card - when / why / where is the problem ---- */
let DEBUG_ON=false;
async function loadDebug(){
  const el=document.getElementById("dbgBody");
  try{
    const d=await jget("/debug");
    DEBUG_ON=!!d.debug;
    const rows=[];
    rows.push("<tr><td><b>Debug mode: </b>"+(DEBUG_ON?"<span class='st printed'>ON</span>":"<span class='st held'>OFF</span>")+"</td>"+
      "<td class='mono'>verbose logs + collects browser (JS) error reports</td>"+
      "<td><button onclick='toggleDebug("+(!DEBUG_ON)+")'>"+(DEBUG_ON?"Disable":"Enable")+"</button></td></tr>");
    rows.push("<tr><td><b>Worker: </b>"+(d.worker_alive?"<span class='st printed'>running</span>":"<span class='st failed'>NOT RUNNING</span>")+"</td>"+
      "<td class='mono'>queue "+(d.paused?"<span class='st failed'>PAUSED</span>":"running")+" &middot; instant auto-queue "+(d.instant_auto_queue?"on":"off")+" &middot; held "+((d.queue||{}).held||0)+"</td>"+
      "<td><a href='/debug"+Q+"'><button>Open /debug</button></a></td></tr>");
    for(const p of (d.problems||[]).slice(0,4)){
      rows.push("<tr><td><span class='st "+(p.level==="error"?"failed":p.level==="warn"?"held":"queued")+"'>"+esc(p.level)+"</span> "+esc(p.check)+"</td>"+
        "<td>"+esc(p.message)+(p.fix?" <small>Fix: "+esc(p.fix)+"</small>":"")+"</td><td></td></tr>");
    }
    const crs=d.client_reports||[];
    const last=crs.length?crs[crs.length-1]:null;
    rows.push("<tr><td><b>Client error reports: </b>"+crs.length+"</td>"+
      "<td class='mono'>"+(last?esc((last.source||"?")+" / "+(last.level||"?")+": "+String(last.message||"").slice(0,90)):"none yet - also switch Debug ON in the extension (Options &gt; Settings)")+"</td>"+
      "<td><button onclick='copyDebug()'>Copy report</button></td></tr>");
    el.innerHTML=rows.join("");
  }catch(e){
    el.innerHTML="<tr><td>debug load failed: "+esc(e.message)+"</td></tr>";
  }
}
async function toggleDebug(on){
  const r=await act("/config",{debug:on});
  if(r.ok)msg("Debug mode "+(on?"ON - extension errors will be collected and shown in /debug":"OFF"));
  else msg(r.error||"failed to change debug mode");
  loadDebug();
}
function copyDebug(){
  jget("/debug").then(d=>navigator.clipboard.writeText(JSON.stringify(d,null,2)))
    .then(()=>msg("debug report copied to clipboard - attach it to your bug report"))
    .catch(()=>msg("copy failed - open /debug and copy manually"));
}
/* ---- v2.8: DropZone card - print without the extension ---- */
async function loadDz(){
  try{
    const d=await jget("/dropzone");
    const s=document.getElementById("dzState");
    if(!s)return;
    s.className="st "+(d.enabled?(d.waiting?"scheduled":"printed"):"held");
    s.textContent=d.enabled
      ?(d.waiting?(""+d.waiting+" PDF waiting")
                  :(""+d.done+" printed (done folder)"))
      :"OFF";
    document.getElementById("dzDirShow").textContent=d.dir||"";
    const di=document.getElementById("dzDir");
    if(di&&document.activeElement!==di)di.value=d.custom_dir||"";
    document.getElementById("dzDelete").checked=!!d.delete;
    document.getElementById("dzToggleBtn").textContent=d.enabled?"Disable":"Enable";
  }catch(e){}
}
async function dzToggle(){
  const d=await jget("/dropzone");
  const r=await act("/config",{drop_enabled:!d.enabled});
  if(r.ok)msg("DropZone "+(!d.enabled?"ON - PDFs saved into the folder print automatically":"OFF - the folder is not watched any more"));
  else msg(r.error||"failed");
  setTimeout(loadDz,400);
}
async function dzSave(){
  const dir=document.getElementById("dzDir").value.trim();
  const del=document.getElementById("dzDelete").checked;
  const r=await act("/config",{drop_dir:dir,drop_delete:del});
  if(r.ok)msg("DropZone saved - "+(dir?"watching "+dir:"using the default folder")+(del?", PDFs are deleted after printing":", printed PDFs move to done\\"));
  else msg(r.error||"failed");
  setTimeout(loadDz,400);
}
async function dzOpen(){
  const r=await act("/dropzone/open",{});
  if(r.ok)msg("DropZone folder opened: "+r.dir);
  else msg(r.error||"failed - open it manually on the hub PC");
}
/* ---- v2.8: Restart hub - clean self-relaunch with health polling ---- */
async function restartHub(){
  if(!confirm("Restart the AdvPrint Pro hub now?\n\nThe hub relaunches itself - queued jobs, settings and history are kept. The page reconnects automatically."))return;
  msg("Restarting the hub...");
  try{await act("/restart",{});}catch(_){}
  let tries=0;
  const t=setInterval(async()=>{
    tries++;
    try{
      const r=await fetch("/health",{cache:"no-store"});
      if(r.ok){clearInterval(t);msg("Hub is back (v"+(await r.json()).version+")");location.reload();return;}
    }catch(_){}
    if(tries>40){clearInterval(t);msg("The hub did not come back within 40 s - start it from the tray icon or AdvPrint Tool.");}
  },1000);
}
async function rotateToken(){
  if(!confirm("Generate a NEW token? The old one stops working immediately."))return;
  const r=await act("/token/rotate");
  if(r.ok){prompt("Your NEW token - copy it into the extension Options page:",r.token);}
  else msg(r.error||"failed");
}
refresh();loadHistory();loadLan();loadDest();loadDebug();loadDz();
setInterval(refresh,5000);setInterval(loadHistory,10000);extInfo();
setInterval(loadLan,15000);setInterval(loadDebug,15000);
async function ltSend(){
  const out=document.getElementById("ltOut");
  const pr=(document.getElementById("ltPrinter").value||"").trim();
  out.textContent="sending test print...";
  try{
    const r=await fetch(withQ("/testprint?kind=a4"+(pr?"&printer="+encodeURIComponent(pr):"")));
    const d=await r.json();
    if(!d.ok){out.textContent="test print failed: "+(d.error||("HTTP "+r.status));return;}
    const jid=d.job_id; let n=0;
    const timer=setInterval(async()=>{
      try{
        const s=await (await fetch("/jobs/"+jid+Q)).json();
        if(!s.job){return;}
        const j=s.job, st=j.status;
        out.textContent="job #"+jid+" ["+st+"] "
          +(j.held_reason?(" - "+j.held_reason+" "):"")
          +(j.error?(" - "+j.error+" "):"");
        if(st==="printed"){clearInterval(timer);
          out.textContent="VERDICT: job #"+jid+" REAL PRINTER HIT -> '"+j.printer+"'";}
        else if(st==="saved"){clearInterval(timer);
          out.textContent="VERDICT: job #"+jid+" SAVED to "+(j.file_path||"the save-as-PDF folder")+" (virtual printer, no paper needed)";}
        else if(st==="failed"||st==="canceled"||st==="dead"){clearInterval(timer);
          out.textContent="VERDICT: job #"+jid+" "+st.toUpperCase()+" - "+(j.error||"open /debug for details");}
        else if(++n>60){clearInterval(timer);
          out.textContent="job #"+jid+" still '"+st+"' after 60 s - open /debug";}
      }catch(e){clearInterval(timer);
        out.textContent="Hub went OFFLINE during the test (start AdvPrint"
          +" Pro again, then retry) - "+e;} },900);
  }catch(e){out.textContent="Hub is OFFLINE - start AdvPrint Pro first"
    +" (AdvPrint Tool > 1 Start, or the tray icon), then try again.";}
}
async function ltRelease(){
  const r=await act("/jobs/release_all",{});
  document.getElementById("ltOut").textContent="release_all -> "+JSON.stringify(r);}
/* v2.6: full A-to-Z self-test - runs the same checks as
 * "python advprint.py livetest" and renders PASS/FAIL lines. */
async function ltFull(){
  const out=document.getElementById("ltOut");
  out.textContent="running full self-test...";
  try{
    const r=await fetch("/livetest"+Q,{method:"POST",
      headers:Object.assign({"Content-Type":"application/json"},H),
      body:"{}"});
    const d=await r.json();
    if(!d.ok){out.textContent="self-test failed: "+(d.error||r.status);return;}
    const L=(d.steps||[]).map(s=>
      "["+(s.pass?"OK":"!!")+"] "+s.name+(s.info?"  - "+s.info:""));
    L.push("");L.push(d.all_ok?
      "ALL CHECKS PASSED - AdvPrint Pro is production-ready on this PC.":
      "FIX THE [!!] ITEMS ABOVE, then run the self-test again.");
    out.textContent=L.join("\n");
  }catch(e){out.textContent="Hub is OFFLINE - start AdvPrint Pro first"
    +" (AdvPrint Tool > 1 Start, or the tray icon), then run the"
    +" self-test again. ("+e.message+")";}
}
async function ltSaveSumatra(){
  const v=document.getElementById("ltSumatra").value.trim();
  const r=await act("/config",{sumatra_path:v});
  document.getElementById("ltCfgMsg").textContent=
    r.ok?("saved"+(r.changed&&r.changed.length?" ("+r.changed.join(", ")+")":"")):"failed";}
/* ---- v2.9: print destination - ANY printer (default / selected / IP) ---- */
let DEST={mode:"default",sel:"",display:"",ip:{host:"",port:0,proto:"raw"}};
async function loadDest(){
  try{
    const hl=await jget("/health");
    DEST.mode=hl.dest_mode||"default";
    DEST.sel=hl.selected_printer||"";
    DEST.display=hl.dest_display||"";
    DEST.ip=hl.ip_printer||{host:"",port:0,proto:"raw"};
    const sel=document.getElementById("destSel"); if(!sel)return;
    let opts="<option value='__default__'"+(DEST.mode==="default"?" selected":"")+">(OS default printer)</option>";
    try{
      const pr=await jget("/printers");
      ((pr&&pr.printers)||[]).forEach(p=>{
        const on=(DEST.mode==="selected"&&p.name===DEST.sel)?" selected":"";
        opts+="<option value='"+esc(p.name)+"'"+on+">"+esc(p.name)+(p.is_default?"  (default)":p.is_group?"  (group)":"")+"</option>";});
    }catch(_){}
    opts+="<option value='__ip__'"+(DEST.mode==="ip"?" selected":"")+">IP printer (network)...</option>";
    sel.innerHTML=opts;
    document.getElementById("destIp").value=DEST.ip.host||"";
    document.getElementById("destPort").value=DEST.ip.port||"";
    document.getElementById("destProto").value=DEST.ip.proto||"raw";
    destPick();
  }catch(_){}
}
function destPick(){
  const v=document.getElementById("destSel").value;
  /* v2.9.1: "flex" (was inline) - the wrap span is a flex row now, so the
     IP / Port / Proto fields wrap under each other instead of overflowing. */
  document.getElementById("destIpWrap").style.display=(v==="__ip__")?"flex":"none";
}
function destBody(){
  const v=document.getElementById("destSel").value;
  if(v==="__default__")return{dest_mode:"default"};
  if(v==="__ip__")return{dest_mode:"ip",
    ip_printer_host:document.getElementById("destIp").value.trim(),
    ip_printer_port:parseInt(document.getElementById("destPort").value,10)||0,
    ip_printer_proto:document.getElementById("destProto").value};
  return{dest_mode:"selected",printer:v};
}
async function destSave(){
  const m=document.getElementById("destMsg");
  const r=await act("/config",destBody());
  if(r.ok){await loadDest();m.textContent="saved - jobs now print to "+DEST.display;}
  else m.textContent=r.error||"save failed";
}
async function destTest(){
  const m=document.getElementById("destMsg");
  const v=document.getElementById("destSel").value;
  if(v!=="__ip__"){m.textContent="pick 'IP printer (network)...' in the list first, then Test";return;}
  m.textContent="testing...";
  const r=await act("/ip-printer/test",{
    host:document.getElementById("destIp").value.trim(),
    port:parseInt(document.getElementById("destPort").value,10)||0,
    proto:document.getElementById("destProto").value});
  m.textContent=r.ok?("IP printer answers - "+r.ms+" ms ("+r.target+")"):(r.error||"test failed");
}
</script></body></html>"""

# ------------------------------------------------------------
# Optional Windows service (services.msc -> "AdvPrint")
# ------------------------------------------------------------
# The DEFAULT auto-run is a normal Startup app (tray icon visible).
# Advanced users can additionally install the hub as a real Windows
# service - it then appears in services.msc and can be started/stopped
# like any service. Both at once is fine but pointless (port conflict:
# the second one to start exits gracefully).

_SVC_CACHE = {"t": 0.0, "v": None}

def service_state():
    """{'installed':bool,'running':bool,'state':str} for the optional
    Windows service (sc query, cached 10 s). Non-Windows -> None.
    Never raises - any problem degrades to state 'unknown'."""
    if not IS_WIN:
        return None
    now = time.time()
    if now - _SVC_CACHE["t"] < 10 and _SVC_CACHE["v"] is not None:
        return _SVC_CACHE["v"]
    state = {"installed": False, "running": False, "state": "not installed"}
    try:
        # v2.6.6: creationflags=HIDE was MISSING here - the windowless hub
        # (AdvPrintPro.exe) made Windows allocate a NEW console window for
        # sc.exe every ~10 s (service_state cache TTL), because the health
        # refresher thread pulls the service state through
        # build_health_snapshot() every 3 s. Users saw a black window /
        # screen "glitch" flashing periodically; it stopped only when the
        # tool or hub was closed. HIDE (CREATE_NO_WINDOW) ends the flash.
        r = subprocess.run(["sc", "query", SERVICE_NAME],
                           capture_output=True, text=True, timeout=6,
                           creationflags=HIDE)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 1060 or "STATE" not in out.upper():
            state["state"] = "not installed"
        else:
            state["installed"] = True
            for line in out.splitlines():
                if "STATE" in line:
                    s = line.split()[-1].strip().upper()
                    state["state"] = s.lower().replace("_", " ")
                    state["running"] = s == "RUNNING"
                    break
            else:
                state["state"] = "installed"
    except Exception:
        state = {"installed": False, "running": False, "state": "unknown"}
    _SVC_CACHE["t"] = now
    _SVC_CACHE["v"] = state
    return state


def _service_bat_path(action):
    """Locate (or generate) the elevated helper .bat for sc <action>.
    The installer ships service-install.bat / service-remove.bat next to
    the hub dir's parent (%LOCALAPPDATA%\\AdvPrintPro); if they are not
    there we generate an equivalent one in the data dir."""
    name = "service-install.bat" if action == "install" else "service-remove.bat"
    here = hub_dir()
    for cand in (os.path.join(os.path.dirname(here), name),
                 os.path.join(here, name)):
        if os.path.isfile(cand):
            return cand
    # generate (portable layout / manual installs)
    py_exe = os.path.join(os.path.dirname(sys.executable), "python.exe")
    if not os.path.isfile(py_exe):
        py_exe = sys.executable
    script = os.path.join(here, "service_main.py")
    lines = ["@echo off"]
    if action == "install":
        lines += [
            'sc create %s binPath= "\\"%s\\" \\"%s\\"" start= auto '
            'DisplayName= "%s"' % (SERVICE_NAME, py_exe, script,
                                   SERVICE_DISPLAYNAME),
            'sc description %s "AdvPrint Pro silent print bridge '
            '(Bit Dream IT) - manage in services.msc"' % SERVICE_NAME,
            'sc failure %s reset= 86400 actions= restart/5000/'
            'restart/5000/restart/60000' % SERVICE_NAME,
            "sc start %s" % SERVICE_NAME,
        ]
    else:
        lines += ["sc stop %s" % SERVICE_NAME,
                  "sc delete %s" % SERVICE_NAME]
    lines.append("exit /b 0")
    ensure_dirs()
    p = os.path.join(CFG["data_dir"], name)
    with open(p, "w", encoding="ascii", errors="replace", newline="\r\n") as f:
        f.write("\n".join(lines))
    return p


def cmd_service(action):
    """CLI: python advprint.py service-install | service-remove |
    service-status.  install/remove elevate via UAC and run sc.exe."""
    if not IS_WIN:
        print("Windows services are only available on Windows.")
        print("On Linux/macOS use the systemd user service (install-unix.sh / .deb).")
        return
    if action == "status":
        st = service_state()
        print("Windows service '%s': %s" % (SERVICE_NAME, st["state"]))
        if st["installed"]:
            print("Manage it in services.msc (name: %s), or:" % SERVICE_NAME)
            print("  stop : python advprint.py service-remove")
        else:
            print("Install it with:  python advprint.py service-install")
            print("(a UAC prompt will appear - admin approval needed once)")
        return
    bat = _service_bat_path(action)
    if not os.path.isfile(bat):
        print("Helper script missing: %s" % bat)
        return
    print("Requesting administrator approval (UAC prompt) ...")
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Start-Process -FilePath '%s' -Verb RunAs -Wait" % bat],
            timeout=240)
    except Exception as e:
        print("Elevation failed or was canceled: %s" % e)
        return
    time.sleep(1.5)
    _SVC_CACHE["t"] = 0.0
    st = service_state()
    if action == "install":
        if st["installed"]:
            print("Windows service '%s' is now: %s" % (SERVICE_NAME, st["state"]))
            print("Visible in services.msc as '%s'." % SERVICE_DISPLAYNAME)
        else:
            print("Service install did not complete - check the UAC prompt")
            print("and run 'python advprint.py service-status' to verify.")
    else:
        if not st["installed"]:
            print("Windows service '%s' removed." % SERVICE_NAME)
        else:
            print("Service still present (state: %s) - try again or use "
                  "services.msc to remove it." % st["state"])


# ------------------------------------------------------------
# GitHub update check
# ------------------------------------------------------------
def github_latest_version(timeout=8):
    """(version, url) of the newest GitHub release; raises on failure."""
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO,
        headers={"User-Agent": "AdvPrintPro/%s" % VERSION,
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    tag = str(data.get("tag_name") or "").lstrip("vV")
    return tag, (data.get("html_url") or GITHUB_RELEASES)


def cmd_update_check():
    """CLI: python advprint.py update-check"""
    print(BANNER)
    print("Installed version : AdvPrint Pro v%s" % VERSION)
    print("Checking GitHub .. %s" % GITHUB_RELEASES)
    try:
        latest, url = github_latest_version()
    except Exception as e:
        print("Could not reach GitHub (%s)." % e)
        print("Check manually: %s" % GITHUB_RELEASES)
        return 1
    def vnum(s):
        n = [int(x) for x in re.findall(r"\d+", s)[:3]]
        return n if len(n) == 3 else [0, 0, 0]
    if vnum(latest) > vnum(VERSION):
        print("")
        print("UPDATE AVAILABLE:  v%s   (you have v%s)" % (latest, VERSION))
        print("Download: %s" % url)
        try:
            if IS_WIN:
                os.startfile(url)          # opens the browser
            else:
                webbrowser.open(url)
        except Exception:
            pass
    else:
        print("You are up to date (latest release: v%s)." % latest)
    return 0


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------
BANNER = r"""
  ____  _             _      ____  __  __
 |  _ \| | __ _ _ __ | | ___|  _ \|  \/  | __ _ _ __   ___ ___
 | |_) | |/ _` | '_ \| |/ _ \ |_) | |\/| |/ _` | '_ \ / __/ _ \
 |  __/| | (_| | | | | |  __/  __/| |  | | (_| | | | | (_|  __/
 |_|   |_|\__,_|_| |_|_|\___|_|   |_|  |_|\__,_|_| |_|\___\___|
            v%s  by %s  -  open source (MIT)
  100%% local - no cloud, no tracking
""" % (VERSION, VENDOR)

def lan_ip():
    """Best-effort LAN address of this PC (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# v3.2.9 BUG 3: EVERY interface IP of the hub PC. The single lan_ip()
# UDP trick returns the address the default route uses - on a PC with
# a VPN / hotspot / virtual adapter that can be an address (e.g. a
# 10.x carrier range) the LAN PCs can NOT reach, while the real
# 192.168.x address never shows up anywhere. The LAN panel now lists
# every candidate so each PC can pick its own reachable ip:port.
_LAN_IPS_CACHE = {"t": 0.0, "ips": []}


def _ipv4_sort_key(ip):
    """Private-ranges first (192.168, 10, 172.16-31), then the rest;
    link-local (169.254.*) and loopback last - they never help."""
    o = ip.split(".")
    if len(o) != 4:
        return (9, ip)
    try:
        a, b = int(o[0]), int(o[1])
    except ValueError:
        return (9, ip)
    if a == 192 and b == 168:
        g = 0
    elif a == 10:
        g = 1
    elif a == 172 and 16 <= b <= 31:
        g = 2
    elif a == 169 and b == 254:
        g = 8
    elif a == 127:
        g = 9
    else:
        g = 5
    try:
        return (g, tuple(int(x) for x in o))
    except ValueError:
        return (g, ip)


def list_lan_ips(max_age=15.0):
    """All IPv4 addresses of this hub PC, best private-LAN candidate
    FIRST (v3.2.9 BUG 3). Cached a few seconds - DHCP changes picked
    up without hammering getaddrinfo on every poll."""
    now = time.time()
    if _LAN_IPS_CACHE["ips"] and now - _LAN_IPS_CACHE["t"] < max_age:
        return list(_LAN_IPS_CACHE["ips"])
    ips = set()
    lip = lan_ip()
    if lip and not lip.startswith("127."):
        ips.add(lip)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            a = str(info[4][0])
            if a and not a.startswith("127."):
                ips.add(a)
    except socket.gaierror:
        pass
    try:
        # enumerate through connected-UDP probes on common LAN ranges -
        # cheap and offline-safe: this does NOT send packets, it only
        # asks the kernel which SOURCE address a route would use.
        for probe in ("192.168.255.255", "10.255.255.255",
                      "172.31.255.255", "169.254.255.255"):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.settimeout(0.2)
                s.connect((probe, 9))
                a = s.getsockname()[0]
                if a and not a.startswith("127."):
                    ips.add(a)
            except OSError:
                pass
            finally:
                s.close()
    except Exception:
        pass
    ordered = sorted(ips, key=_ipv4_sort_key)[:12]
    if not ordered:
        ordered = [lip or "127.0.0.1"]
    _LAN_IPS_CACHE["t"] = now
    _LAN_IPS_CACHE["ips"] = ordered
    return list(ordered)


# v3.3.0 BUG 2: the IPv6 half of the address list. link-local fe80::
# needs a zone id and is useless in a printer URL; loopback ::1 is the
# PC itself - so only GLOBAL (2000::/3) and unique-local (fc00::/7)
# addresses are offered. Empty on IPv4-only PCs and that is fine.
_LAN_IPS6_CACHE = {"t": 0.0, "ips": []}


def list_lan_ips6(max_age=15.0):
    """Usable IPv6 addresses of this hub PC (global + unique-local,
    no ::1, no fe80 link-local). Cached a few seconds like
    list_lan_ips(). Returns [] when the PC has no usable IPv6."""
    now = time.time()
    if _LAN_IPS6_CACHE["ips"] and now - _LAN_IPS6_CACHE["t"] < max_age:
        return list(_LAN_IPS6_CACHE["ips"])
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET6):
            a = str(info[4][0]).split("%")[0].lower()
            if not a or a == "::1" or a.startswith("fe80:") or \
                    a.startswith("::ffff:"):
                continue
            if a not in ips:
                ips.append(a)
    except socket.gaierror:
        pass
    except OSError:
        pass
    _LAN_IPS6_CACHE["t"] = now
    _LAN_IPS6_CACHE["ips"] = ips[:12]
    return list(ips[:12])


# ------------------------------------------------------------
# v3.3.0 BUG 2: DUAL-STACK, EVERY-INTERFACE LISTENERS.
# The old LAN listeners (9235 LAN, 631 mirror, RAW 9100) each bound
# exactly ONE address - lan_ip(), the default-route IPv4 - so a hub PC
# with several adapters (Ethernet + Wi-Fi + VPN + virtual NICs) went
# DEAF on every other address, and no listener ever spoke IPv6 ("the
# other PC cannot connect", "row printer show only ipv6 why not also
# ipv4"). bind_listener_sockets() now binds:
#   IPv4: one listening socket per non-loopback interface IP - specific
#         binds never conflict with each other, nor with the 127.0.0.1
#         loopback hub on the same port.
#   IPv6: one [::] socket with IPV6_V6ONLY=1 - answers every IPv6
#         address of this PC (and future ones) without stealing IPv4
#         traffic from the v4 sockets.
# The ACL (allowed_ips) still gates every connection at the
# application layer, exactly as before - widening the bind does not
# widen who may DO anything.
# ------------------------------------------------------------
def _sock_label(sock):
    """Human label of a bound listening socket for logs + health."""
    try:
        host, port = sock.getsockname()[:2]
        if ":" in str(host):
            return "[%s]:%d" % (host, port)
        return "%s:%d" % (host, int(port))
    except Exception:
        return "?"


def _bind_signature():
    """The bind set the listeners SHOULD be on right now. The ensure()
    refreshers compare this against what is actually bound - DHCP, a
    Wi-Fi join or a VPN tunnel changing the interface set triggers a
    clean rebind (the old code rebinds only when lan_ip() moved, which
    misses new adapters entirely)."""
    ips = tuple(sorted(i for i in list_lan_ips()
                       if i and not i.startswith("127.")))
    try:
        v6 = bool(socket.has_dualstack_ipv6())
    except AttributeError:
        v6 = False
    return (ips, v6)


def bind_listener_sockets(port, label):
    """Bind BOTH stacks on EVERY interface for one port. Returns
    (sockets, errors); raises OSError only when NOT ONE socket could
    bind - a partial set (v4 only, or v6 only) is still a working
    listener."""
    socks, errs = [], []
    # ---- IPv6: one socket, every address, no v4 takeover ----
    try:
        dual = socket.has_dualstack_ipv6()
    except AttributeError:
        dual = False
    if dual:
        s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        try:
            s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            except OSError:
                pass
            s6.bind(("::", port))
            s6.listen(128)
            socks.append(s6)
        except OSError as e:
            try:
                s6.close()
            except OSError:
                pass
            errs.append("[::]:%d (%s)" % (port, e))
    # ---- IPv4: one socket per real interface IP ----
    for ip in list_lan_ips():
        if not ip or ip == "127.0.0.1":
            continue                  # the loopback hub owns exactly 127.0.0.1
        s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s4.bind((ip, port))
            s4.listen(128)
            socks.append(s4)
        except OSError as e:
            try:
                s4.close()
            except OSError:
                pass
            errs.append("%s:%d (%s)" % (ip, port, e))
    if not socks:
        raise OSError("%s listeners: no bindable address on port %d (%s)"
                      % (label, port, "; ".join(errs) or "none"))
    return socks, errs


def _httpd_on(sock, handler, server_cls):
    """server_cls instance on an ALREADY-BOUND listening socket (the
    dual-stack helper owns bind+listen, so the server skips its own
    bind - and HubServer's Windows-exclusive server_bind is never
    needed here)."""
    srv = server_cls(("127.0.0.1", 0), handler, bind_and_activate=False)
    try:
        srv.socket.close()
    except OSError:
        pass
    srv.socket = sock
    try:
        srv.server_address = sock.getsockname()
    except Exception:
        pass
    srv.server_activate()                   # listen(backlog) on our socket
    srv.daemon_threads = True
    return srv


def _sanitize_host_hdr(h):
    """v3.2.9 BUG 3: clean a Host header value for safe reuse in the
    URLs shown on pages. Returns (host, port-or-None) or ("", None) if
    the header is unusable - only [a-z0-9.-] hosts / [ipv6] / numeric
    ports survive, so no header text can leak into page markup."""
    h = str(h or "").strip().lower()
    if not h or len(h) > 253:
        return "", None
    host, port = h, None
    if h.startswith("["):                       # [ipv6]:port
        end = h.find("]")
        if end < 0:
            return "", None
        host = h[1:end]
        rest = h[end + 1:]
        if rest.startswith(":"):
            port = rest[1:]
    elif ":" in h:
        host, _, port = h.partition(":")
    if not re.fullmatch(r"[a-z0-9._\-:%]+", host or ""):
        return "", None
    host = host.rstrip(".")
    if port is not None and not port.isdigit():
        port = None
    return host, port


def lan_share_url(kind="send"):
    """v2.8.1: URL another device uses to reach this hub (see
    Handler._lan_share_url for the security rationale).
    v2.9.0: kind="ipp" -> the IPP printer URL for Windows "add a
    printer by URL" / phone print services (no token - IPP is its own
    protocol, like any physical network printer)."""
    ip = lan_ip() if CFG.get("share_lan") else "127.0.0.1"
    base = "http://%s:%d" % (ip, CFG["port"])
    if kind == "invite":
        return "%s/connect?t=%s&n=%s" % (
            base, quote(str(CFG["token"] or "")),
            quote(socket.gethostname()))
    if kind == "ipp":
        return "%s/ipp/print" % base
    return "%s/send?token=%s" % (base, quote(str(CFG["token"] or "")))


def _ipp_scheme_url(url):
    """v3.2.8 BUG FIX 1: convert ANY hub URL into the ipp:// printer URL
    WITHOUT ever doubling the scheme. v3.2.7 built the landing-page
    printer URL as 'ipp://' + lan_share_url('ipp') - but that value is an
    http:// URL, so opening http://<lan-ip>:9235/ipp/print in a browser
    showed ipp://http://<lan-ip>:9235/ipp/print (protocol TWICE) and
    Windows/macOS/CUPS refused the pasted address. Strip the web scheme
    FIRST, then prepend ipp:// so the page always shows the one clean
    form: ipp://<lan-ip>:9235/ipp/print. Accepts http://, https://, an
    already-ipp:// URL or a bare host:port/path."""
    u = str(url or "").strip()
    low = u.lower()
    for pfx in ("http://", "https://"):
        if low.startswith(pfx):
            u = u[len(pfx):]
            break
    if u.lower().startswith("ipp://"):
        return u
    return "ipp://" + u


def ipp_scheme_bare(url):
    """v3.2.8: the ipp:// printer URL WITHOUT the ipp:// prefix - for the
    landing-page template which writes the ipp:// itself inside <code>."""
    return _ipp_scheme_url(url)[len("ipp://"):]

# ------------------------------------------------------------
# v2.8.2 LIVE LAN REBIND - fixes "toggled LAN sharing ON but
# http://<lan-ip>:9235 does not answer". In 2.8.1 the flag was only
# SAVED and the hub had to be RESTARTED to rebind its single listener
# - easy to miss, so the LAN IP stayed dead. Now the loopback
# listener (127.0.0.1) ALWAYS stays up - the dashboard, the extension
# and this PC never lose the hub - and LAN sharing runs a SECOND
# listener bound to this machine's SPECIFIC LAN IP (e.g.
# 192.168.1.244:9235). A specific-IP bind coexists with the loopback
# bind on every OS, so toggling the switch simply starts/stops the
# second listener: instantly, zero downtime, and a failed LAN bind
# can never take local printing down.
# ------------------------------------------------------------
_LAN_HTTPDS = []                  # v3.3.0 BUG 2: one server per stack
_LAN_THREADS = []
_LAN_BINDS = []                   # labels of the sockets actually bound
_LAN_BIND_SIG = None              # interface set the binds were made on

def lan_listen_active():
    """True while the dedicated LAN listener is serving."""
    return bool(_LAN_HTTPDS)

def lan_listen_start():
    """Bind the LAN listener on EVERY interface, IPv4 AND IPv6
    (bind_listener_sockets). Returns an error string, or None on
    success. Never touches the loopback hub: if no bind succeeds,
    127.0.0.1 keeps answering.
    v3.3.0 BUG 2: the old single lan_ip() bind went deaf on every
    other adapter of the PC (VPN, second NIC, virtual switches) and
    never answered IPv6 at all - the "other PC cannot connect" and
    "listening shows only ipv6 / why not also ipv4" reports."""
    global _LAN_HTTPDS, _LAN_THREADS, _LAN_BINDS, _LAN_BIND_SIG, BOUND_LAN
    if _LAN_HTTPDS:
        return None
    if _env("HOST"):
        # Power user pinned the main bind with ADVPRINT_HOST (e.g.
        # 0.0.0.0): that listener already covers the LAN - do not open
        # a second one, trust the boot-time BOUND_LAN value.
        return None
    port = int(CFG.get("port", 9235))
    try:
        socks, errs = bind_listener_sockets(port, "LAN hub")
    except OSError as e:
        return ("no LAN address to bind (%s) - connect to the network"
                " and toggle LAN sharing again" % e)
    opened = []
    for s in socks:
        try:
            httpd = _httpd_on(s, Handler, HubServer)
        except Exception as e:
            try:
                s.close()
            except OSError:
                pass
            errs.append("%s: %s" % (_sock_label(s), e))
            continue
        opened.append(httpd)
    if not opened:
        for s in socks:
            try:
                s.close()
            except OSError:
                pass
        return ("cannot bind %s:%d (%s) - another program may own the"
                " port, or the network card just changed"
                % (lan_ip(), port, "; ".join(errs)))
    _LAN_HTTPDS = opened
    _LAN_BINDS = [_sock_label(s) for s in socks[:len(opened)]]
    for httpd in opened:
        t = threading.Thread(target=httpd.serve_forever,
                             kwargs={"poll_interval": 0.2},
                             name="advprint-lan", daemon=True)
        _LAN_THREADS.append(t)
        t.start()
    _LAN_BIND_SIG = _bind_signature()
    BOUND_LAN = True
    log("[LAN] listeners UP on %s - other PCs and phones can print now"
        " (IPv4 + IPv6; the loopback listener was never touched)%s"
        % (", ".join(_LAN_BINDS),
           " (failed: %s)" % "; ".join(errs) if errs else ""))
    try:
        build_health_snapshot()
    except Exception:
        pass
    return None

def lan_listen_stop():
    """Stop the dedicated LAN listeners (loopback hub keeps running)."""
    global _LAN_HTTPDS, _LAN_THREADS, _LAN_BINDS, _LAN_BIND_SIG, BOUND_LAN
    httpds = _LAN_HTTPDS
    if not httpds:
        return
    _LAN_HTTPDS = []
    _LAN_THREADS = []
    _LAN_BINDS = []
    _LAN_BIND_SIG = None
    if not _env("HOST"):
        BOUND_LAN = False
    def _closer():
        for httpd in httpds:
            try:
                httpd.shutdown()      # exits serve_forever (its own thread)
            except Exception:
                pass
            try:
                httpd.server_close()  # release the port
            except Exception:
                pass
        log("[LAN] listeners stopped - this PC only (127.0.0.1) again")
    threading.Thread(target=_closer, daemon=True,
                     name="advprint-lan-stop").start()
    try:
        build_health_snapshot()
    except Exception:
        pass

def lan_listen_ensure():
    """Health-refresher hook (runs every 3 s): follow config changes
    AND DHCP IP changes without any user action.
    v3.2.2: IPP PRINTER MODE owns the LAN listener too - when
    ipp_printer is on, phones/PCs must be able to REACH /ipp/print,
    so the LAN listener starts even when share_lan is off (turning
    'IP Printer mode' off + 'LAN sharing' off stops it again)."""
    if _env("HOST"):
        return
    want = bool(CFG.get("share_lan")) or ipp_printer_enabled()
    if want and not _LAN_HTTPDS:
        err = lan_listen_start()
        if err:
            log("[LAN] auto-start: %s" % err)
        elif not bool(CFG.get("share_lan")):
            log("[IPP] printer mode ON: LAN listener started so phones "
                "and PCs can reach /ipp/print (turn OFF 'IP Printer "
                "mode' to stop it)")
    elif want and _LAN_BIND_SIG is not None and \
            _LAN_BIND_SIG != _bind_signature():
        # v3.3.0 BUG 2: follow the INTERFACE SET, not just the default
        # route - a new Wi-Fi/VPN adapter is picked up automatically.
        log("[LAN] interface set changed %s -> %s - rebinding the LAN"
            " listeners" % (str(_LAN_BIND_SIG[0]), str(_bind_signature()[0])))
        lan_listen_stop()
        lan_listen_start()
    elif not want and _LAN_HTTPDS:
        lan_listen_stop()

# ------------------------------------------------------------
# v2.9.0 - NETWORK PRINTER MODE. The hub can now be added on OTHER
# devices like a real IP printer - the same way Windows "Add a
# printer" adds a network device by IP + port:
#
#   1. RAW JetDirect listener (default TCP 9100). On any Windows PC:
#      Add printer -> "The printer that I want isn't listed" ->
#      "Add a printer using TCP/IP address" -> this PC's IP, device
#      type Generic Network Card, port 9100 (RAW). Windows renders
#      ANY file (Word, Excel, photos, web pages) with the driver the
#      user picked and streams the print-ready bytes here; the hub
#      routes them to the real printer. Phones with ESC/POS/ZPL
#      printing apps can open a raw socket the same way.
#   2. IPP endpoint on the hub's own HTTP port: http://<ip>:9235/
#      ipp/print. Windows 10/11 "Select a shared printer by name"
#      and most phone print services accept this URL directly (the
#      Microsoft IPP Class Driver handles the rest). IPP rides the
#      SAME port as the dashboard, so no extra firewall rule is
#      needed for it.
#
# Payload routing (both paths share route_print_payload):
#   %PDF            -> normal PDF pipeline (SumatraPDF/Edge,
#                      keep_files, audit, History - a first-class job)
#   JPEG (FFD8FF)   -> wrapped into a single-page PDF (DCTDecode)
#   %!PS / PCL/ESC  -> winspool RAW passthrough to the target queue
#   ^XA (ZPL)       -> winspool RAW passthrough (label printers)
#   ESC @ (ESC/POS) -> thermal/raw route
# No authentication on these two printer endpoints BY DESIGN (a
# physical network printer has none either) - they ONLY accept print
# data, they are bounded by size limits, every job is audited with
# the source IP, and they listen only while LAN sharing is on (the
# RAW listener binds the LAN IP, never 0.0.0.0). Turn either off
# with config.json: "ipp_printer": false / "raw_printer_port": 0.
# ------------------------------------------------------------

_RAW_SOCKS = []                   # v3.3.0 BUG 2: one listener per stack
_RAW_THREADS = []
_RAW_BINDS = []                   # labels of the sockets actually bound
_RAW_BIND_SIG = None

IPP_VERSION_STR = "1.1"
IPP_MIME = "application/ipp"

# ------------------------------------------------------------
# v3.0.8 PROFESSIONAL IPP PRINTER - the v2.9 engine encoded several
# printer attributes with the WRONG wire tags and string values
# ("printer-state" as a charset-tagged ASCII "3", booleans inside an
# enum tag, integers inside a boolean tag, a range inside a boolean
# tag) and omitted the attributes every RFC 8011 printer MUST
# answer with (printer-uri-supported, uri-authentication-supported,
# operations-supported, document-format-default, charset-configured,
# printer-up-time...). Loose clients still printed, but the
# Microsoft IPP Class Driver that Windows 10/11 uses for
# "Add a printer -> IPP Device" runs a strict parser: the first
# mistyped attribute makes it answer "Windows couldn't connect to
# the printer". v3.0.8 rebuilds the whole wire layer with the exact
# RFC 8010 value tags (verified byte-for-byte against CUPS'
# cups/ipp.h) and answers every standard operation:
#
#   Get-Printer-Attributes (full RFC 8011 required set)
#   Print-Job / Print-URI / Validate-Job
#   Create-Job + Send-Document  (multi-document - how macOS CUPS,
#                                iOS PrintKit and Android Mopria
#                                actually submit jobs)
#   Get-Jobs / Get-Job-Attributes / Cancel-Job
#
# Wire reference (RFC 8010 §3.5.2, confirmed via cups/ipp.h):
#   0x21 integer   4-byte signed big-endian
#   0x22 boolean   1 byte 0x00/0x01
#   0x23 enum      4-byte signed big-endian
#   0x33 range     8 bytes (two signed ints)
#   0x31 dateTime  11-byte RFC 2579 DateAndTime
#   0x41 text      0x42 name   0x44 keyword   0x45 uri
#   0x47 charset   0x48 language   0x49 mimeMediaType
# ------------------------------------------------------------
IPP_TAG_OP = 0x01                  # delimiter: operation-attributes
IPP_TAG_JOB = 0x02                 # delimiter: job-attributes
IPP_TAG_END = 0x03                 # delimiter: end-of-attributes
IPP_TAG_PRINTER = 0x04             # delimiter: printer-attributes

V_INT = 0x21                       # SIGNED-INTEGER (4 bytes)
V_BOOL = 0x22                      # boolean (1 byte)
V_ENUM = 0x23                      # enumeration (4 bytes)
V_OCTETS = 0x30                    # octet-string
V_DATE = 0x31                      # dateTime (11 bytes)
V_RESOLUTION = 0x32                # resolution (9 bytes)
V_RANGE = 0x33                     # rangeOfInteger (8 bytes)
V_TEXT = 0x41                      # textWithoutLanguage
V_NAME = 0x42                      # nameWithoutLanguage
V_KEYWORD = 0x44                   # keyword
V_URI = 0x45                       # uri
V_CHARSET = 0x47                   # charset
V_LANG = 0x48                      # naturalLanguage
V_MIME = 0x49                      # mimeMediaType

# RFC 8011 operation-id values this printer implements
IPP_OP_PRINT_JOB = 0x0002
IPP_OP_PRINT_URI = 0x0003
IPP_OP_VALIDATE_JOB = 0x0004
IPP_OP_CREATE_JOB = 0x0005
IPP_OP_SEND_DOCUMENT = 0x0006
IPP_OP_CANCEL_JOB = 0x0008
IPP_OP_GET_JOB_ATTR = 0x0009
IPP_OP_GET_JOBS = 0x000A
IPP_OP_GET_PRINTER_ATTR = 0x000B
IPP_OPERATIONS_SUPPORTED = (
    IPP_OP_PRINT_JOB, IPP_OP_PRINT_URI, IPP_OP_VALIDATE_JOB,
    IPP_OP_CREATE_JOB, IPP_OP_SEND_DOCUMENT, IPP_OP_CANCEL_JOB,
    IPP_OP_GET_JOB_ATTR, IPP_OP_GET_JOBS, IPP_OP_GET_PRINTER_ATTR,
)

# RFC 8011 job-state enums
IPP_JOB_PENDING = 3
IPP_JOB_PROCESSING = 4
IPP_JOB_STOPPED = 5
IPP_JOB_CANCELED = 6
IPP_JOB_ABORTED = 7
IPP_JOB_COMPLETED = 8

IPP_STATUS_OK = 0x0000
IPP_STATUS_BAD_REQUEST = 0x0400
IPP_STATUS_NOT_FOUND = 0x0406
IPP_STATUS_NOT_POSSIBLE = 0x040A
IPP_STATUS_FORMAT_NOT_SUPPORTED = 0x040B
IPP_STATUS_OP_NOT_SUPPORTED = 0x040F
IPP_STATUS_INTERNAL_ERROR = 0x0500

# RFC 8011 status strings (kept for the log)
IPP_STATUS_NAMES = {
    0x0000: "successful-ok", 0x0400: "client-error-bad-request",
    0x0406: "client-error-not-found",
    0x040A: "client-error-not-possible",
    0x040B: "client-error-document-format-not-supported",
    0x040F: "client-error-operation-not-supported",
    0x0500: "server-error-internal-error",
}

# RFC 8011 document formats the virtual printer accepts. PDF first:
# Windows (MS IPP Class Driver), macOS CUPS, iOS PrintKit and the
# Android Default Print Service all send PDF as soon as it is
# advertised, which the hub prints natively. image/urf covers iOS
# AirPrint raster when a client chooses it (passed through raw, like
# a physical AirPrint printer would). PWG-raster is accepted even
# though not advertised (some Mopria builds send it regardless).
IPP_DOCUMENT_FORMATS = ("application/pdf", "image/urf", "image/jpeg",
                        "text/plain", "application/octet-stream")

IPP_MULTIDOC_BASE = 1000000        # Create-Job ids start here so they
                                   # can never collide with db job ids
IPP_MULTIDOC_TIMEOUT = 300         # seconds a session may stay open

_IPP_JOBS = {}                     # session id -> job dict (see below)
_IPP_JOB_SEQ = [IPP_MULTIDOC_BASE]
_IPP_JOBS_LOCK = threading.Lock()


def _ipp_attr(tag, name, value):
    """Encode one IPP attribute (value-tag, name, value). Binary tags
    (int/bool/enum/range/date) take pre-encoded bytes; string tags take
    str. Additional values repeat the SAME tag with an empty name."""
    nb = name.encode("utf-8") if isinstance(name, str) else name
    vb = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return (bytes([tag]) + len(nb).to_bytes(2, "big") + nb +
            len(vb).to_bytes(2, "big") + vb)


def _ipp_additional_attr(tag, value):
    """Additional-value entry: empty name (per RFC 8010 §3.1.4)."""
    return _ipp_attr(tag, "", value)


def _ipp_int(name, n):
    """integer attribute (4-byte signed big-endian)."""
    return _ipp_attr(V_INT, name,
                     int(n).to_bytes(4, "big", signed=True))


def _ipp_enum(name, n):
    """enum attribute (4-byte signed big-endian - NEVER the ASCII digit)."""
    return _ipp_attr(V_ENUM, name,
                     int(n).to_bytes(4, "big", signed=True))


def _ipp_bool(name, b):
    """boolean attribute (1 byte)."""
    return _ipp_attr(V_BOOL, name, b"\x01" if b else b"\x00")


def _ipp_range(name, lo, hi):
    """rangeOfInteger attribute (two 4-byte signed ints)."""
    return _ipp_attr(V_RANGE, name,
                     int(lo).to_bytes(4, "big", signed=True) +
                     int(hi).to_bytes(4, "big", signed=True))


def _ipp_date_bytes(ts=None):
    """11-byte RFC 2579 DateAndTime (year..deci-second, +/-hh:mm)."""
    import datetime as _dt
    now = _dt.datetime.now().astimezone()
    off = int((now.utcoffset() or _dt.timedelta(0)).total_seconds()) // 60
    sign = "+" if off >= 0 else "-"
    off = abs(off)
    out = bytearray()
    out += now.year.to_bytes(2, "big")
    out += bytes((now.month, now.day, now.hour, now.minute, now.second,
                  now.microsecond // 100000))
    out += sign.encode("ascii") + bytes((off // 60, off % 60))
    return bytes(out)


def _ipp_group(tag, attrs):
    return bytes([tag]) + b"".join(attrs)

def _ipp_parse(data):
    """Parse an IPP request far enough to route it. Returns
    (ver_tuple, operation_id, request_id, op_attrs, op_raw, doc).
    op_attrs maps operation-attribute name -> first value decoded as
    text (handy for job-name / user / uri). op_raw maps name ->
    (value_tag, raw_bytes) so binary operation attributes (job-id,
    last-document, my-jobs) can be read with their real types.
    Truncated attribute sections no longer raise mid-walk."""
    if len(data) < 8:
        raise ValueError("IPP request too short")
    ver = (data[0], data[1])
    op = int.from_bytes(data[2:4], "big")
    rid = int.from_bytes(data[4:8], "big")
    n = len(data)
    i = 8
    op_attrs = {}
    op_raw = {}
    doc = b""
    group = None
    while i < n:
        b = data[i]
        if b == 0x03:                       # end-of-attributes tag
            doc = data[i + 1:]
            break
        if b in (0x00, 0x01, 0x02, 0x04, 0x05):
            group = b                       # begOf attribute group
            i += 1
            continue
        # value-tag + name + value triple
        if i + 3 > n:
            break                           # truncated - stop cleanly
        value_tag = b
        nl = int.from_bytes(data[i + 1:i + 3], "big")
        i += 3
        name = data[i:i + nl]
        i += nl
        if i + 2 > n:
            break
        vl = int.from_bytes(data[i:i + 2], "big")
        i += 2
        value = data[i:i + vl]
        i += vl
        if group == 0x01 and nl and value_tag not in (0x34, 0x35, 0x36,
                                                      0x37, 0x4a):
            # operation attributes (skip collection scaffolding)
            key = name.decode("utf-8", "replace")
            if key not in op_attrs:
                op_attrs[key] = value.decode("utf-8", "replace")
            op_raw.setdefault(key, (value_tag, value))
    return ver, op, rid, op_attrs, op_raw, doc

def _ipp_header(ver, status, rid):
    if isinstance(ver, (tuple, list)):
        maj, mnr = int(ver[0]), int(ver[1])
    else:
        maj, mnr = 1, 1
    return (bytes([maj, mnr]) + int(status).to_bytes(2, "big") +
            int(rid).to_bytes(4, "big"))

def _ipp_response(ver, status, rid, groups):
    """RFC 8011 §4.1.1: the response version echoes the request
    version when we support it (Windows speaks 1.1, modern stacks
    speak 2.0); anything above 2.0 is answered as 2.0."""
    if isinstance(ver, (tuple, list)) and len(ver) == 2:
        maj, mnr = int(ver[0]), int(ver[1])
    else:
        maj, mnr = 1, 1
    if (maj, mnr) > (2, 0) or maj not in (1, 2):
        maj, mnr = 2, 0
    head = _ipp_header((maj, mnr), status, rid)
    opg = _ipp_group(IPP_TAG_OP, [
        _ipp_attr(V_CHARSET, "attributes-charset", "utf-8"),
        _ipp_attr(V_LANG, "attributes-natural-language", "en"),
    ])
    return head + opg + b"".join(groups) + b"\x03"

def _ipp_uri_base():
    """(lan_ip_or_loopback, port) the same way lan_share_url computes
    reachability for the IPP printer."""
    ip = lan_ip() if CFG.get("share_lan") else "127.0.0.1"
    return ip, int(CFG.get("port", 9235))

def _ipp_printer_uris():
    """printer-uri-supported: BOTH schemes, because Windows "Add a
    printer -> IPP Device" speaks http:// (the URI the user typed)
    while macOS/iOS/CUPS speak ipp://. Every client matches its own
    entry, so both work."""
    ip, port = _ipp_uri_base()
    return ["http://%s:%d/ipp/print" % (ip, port),
            "ipp://%s:%d/ipp/print" % (ip, port)]

def _ipp_queue_uris(queue_slug):
    """v3.2.9 BUG 1: printer-uri-supported entries for ONE per-printer
    queue ("hp-laser") - BOTH schemes, same reasoning as the generic
    pair above. Windows adds the queue with http://.../ipp/print/<slug>
    ("select a shared printer by name") while macOS/iOS/CUPS speak
    ipp://... - every client must find the URI IT asked for, otherwise
    the Add-Printer dialog refuses to connect.
    v3.3.0 BUG 3: the slug is percent-encoded (Unicode printer names
    produce valid URIs)."""
    ip, port = _ipp_uri_base()
    qs = quote(str(queue_slug or ""), safe="")
    return ["http://%s:%d/ipp/print/%s" % (ip, port, qs),
            "ipp://%s:%d/ipp/print/%s" % (ip, port, qs)]

def _ipp_printer_uuid(queue_slug=None):
    """Stable urn:uuid (derived from the hub token + hostname) - the
    same value every response, which iOS/Android use to remember the
    printer across reboots.
    v3.2.9 BUG 1: every PER-PRINTER queue gets its own stable uuid
    (token|hostname|slug) - clients remember each queue separately,
    and a re-added queue no longer hijacks the identity of the
    generic hub queue."""
    seed = (str(CFG.get("token", "")) + "|" + socket.gethostname()
            + ("|" + queue_slug if queue_slug else ""))
    h = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return "urn:uuid:%s-%s-%s-%s-%s" % (h[0:8], h[8:12], h[12:16],
                                        h[16:20], h[20:32])

def _ipp_scheme_swaps(uri):
    """v3.2.9 BUG 1: the http:// AND ipp:// forms of ANY printer URI -
    the requested URI is echoed in BOTH schemes so the client always
    finds the form it speaks (Windows http://, macOS/CUPS ipp://)."""
    u = str(uri or "").strip()
    low = u.lower()
    for pfx in ("ipp://", "https://", "http://"):
        if low.startswith(pfx):
            bare = u[len(pfx):]
            return ["http://" + bare, "ipp://" + bare]
    return []


def _ipp_printer_group(queue_slug=None, queue_name=None, extra_uris=None):
    """Printer-attributes group for Get-Printer-Attributes - the FULL
    RFC 8011 §4.2.5.2 required set with CORRECT value tags and value
    encodings, plus the job-template defaults the Microsoft IPP Class
    Driver and phone print services query for.
    v3.2.9 BUG 1: with a queue_slug the response ECHOES the per-printer
    queue first - printer-uri-supported lists http:// and ipp:// forms
    of .../ipp/print/<slug> BEFORE the generic ones, printer-name is the
    REAL printer name (not the hub hostname), printer-info/uuid/location
    describe the queue. This is what Windows "select a shared printer by
    name", macOS and CUPS validate - without the echo the Add-Printer
    dialog refused to connect on every LAN PC."""
    host = socket.gethostname()
    try:
        pending = int(db_count_pending())
    except Exception:
        pending = 0
    uris = _ipp_printer_uris()
    ip, port = _ipp_uri_base()
    if queue_slug:
        q_uris = _ipp_queue_uris(queue_slug)
        # the queue URIs go FIRST - the client must see the URI it used
        uris = q_uris + uris
        q_name = queue_name or queue_slug
    else:
        q_name = None
    # v3.2.9: the EXACT URI the client asked for is echoed too (both
    # schemes) when its path differs from the canonical slug - e.g. the
    # user typed HP-Laser-103 while the queue canonicalizes to
    # hp-laser-103, or the device reached the hub by another address.
    for ex in (extra_uris or []):
        if ex and ex not in uris:
            uris.insert(min(2, len(uris)), ex)
    # v3.3.2 BUG 1 (Windows add-printer root cause): uri-security-supported
    # is a REQUIRED RFC 8011 §4.2.5.2 printer description attribute and the
    # Microsoft IPP Class Driver validates the whole required set before it
    # lets Windows add the printer - with the attribute missing it answered
    # "Windows couldn't connect to the printer" on every LAN add attempt
    # even though every other attribute was correct (v3.0.8 set). Both
    # uri-* lists now carry EXACTLY ONE value per printer-uri-supported
    # entry (RFC: the 1setOf value counts must match 1:1; the old code
    # hardcoded two "none" values, which broke parity as soon as a client
    # URI was echoed into the list on a multi-adapter hub).
    # Wire order matters: an additional value (empty name) belongs to the
    # attribute right before it, so ALL auth values come first, then ALL
    # security values - never interleaved.
    n_uri = max(1, len(uris))
    attrs = [
        # -- printer description (RFC 8011 REQUIRED for every response)
        _ipp_attr(V_URI, "printer-uri-supported", uris[0]),
    ]
    for extra in uris[1:]:
        attrs.append(_ipp_additional_attr(V_URI, extra))
    attrs.append(_ipp_attr(V_KEYWORD,
                           "uri-authentication-supported", "none"))
    for _i in range(n_uri - 1):
        attrs.append(_ipp_additional_attr(V_KEYWORD, "none"))
    attrs.append(_ipp_attr(V_KEYWORD, "uri-security-supported", "none"))
    for _i in range(n_uri - 1):
        attrs.append(_ipp_additional_attr(V_KEYWORD, "none"))
    attrs += [
        _ipp_enum("printer-state",
                  IPP_JOB_PROCESSING if pending else IPP_JOB_PENDING),
        _ipp_attr(V_KEYWORD, "printer-state-reasons", "none"),
        _ipp_bool("printer-is-accepting-jobs", True),
        _ipp_int("queued-job-count", pending),
        _ipp_attr(V_KEYWORD, "ipp-versions-supported", "1.1"),
        _ipp_additional_attr(V_KEYWORD, "2.0"),
        # operations-supported: one enum per implemented operation
        _ipp_enum("operations-supported", IPP_OPERATIONS_SUPPORTED[0]),
    ]
    for opid in IPP_OPERATIONS_SUPPORTED[1:]:
        attrs.append(_ipp_additional_attr(
            V_ENUM, int(opid).to_bytes(4, "big", signed=True)))
    attrs += [
        _ipp_attr(V_MIME, "document-format-default", "application/pdf"),
        _ipp_attr(V_MIME, "document-format-supported",
                  IPP_DOCUMENT_FORMATS[0]),
    ]
    for fmt in IPP_DOCUMENT_FORMATS[1:]:
        attrs.append(_ipp_additional_attr(V_MIME, fmt))
    attrs += [
        _ipp_attr(V_KEYWORD, "pdl-override-supported", "attempted"),
        _ipp_int("printer-up-time", int(time.time() - START_TS)),
        _ipp_attr(V_DATE, "printer-current-time", _ipp_date_bytes()),
        _ipp_attr(V_CHARSET, "charset-configured", "utf-8"),
        _ipp_attr(V_LANG, "natural-language-configured", "en"),
        # v3.2.9 BUG 1: a per-printer queue is NAMED after the printer it
        # routes to, so the added printer shows the queue name on every
        # OS instead of the hub hostname (which the generic queue keeps).
        _ipp_attr(V_NAME, "printer-name",
                  q_name if q_name else host),
        _ipp_attr(V_NAME, "printer-info",
                  ("AdvPrint Pro queue %s on %s" % (q_name, host))
                  if q_name else ("AdvPrint Pro on %s" % host)),
        _ipp_attr(V_NAME, "printer-location", ip),
        _ipp_attr(V_URI, "printer-more-info",
                  ("http://%s:%d/ipp/print/%s" % (ip, port, queue_slug))
                  if queue_slug else ("http://%s:%d/" % (ip, port))),
        _ipp_attr(V_URI, "printer-uuid",
                  _ipp_printer_uuid(queue_slug)),
        _ipp_attr(V_TEXT, "printer-make-and-model",
                  "AdvPrint Pro %s Virtual Printer" % VERSION),
        # -- job template defaults / supported values
        _ipp_range("copies-supported", 1, 99),
        _ipp_int("copies-default", 1),
        _ipp_enum("finishings-supported", 3),        # 3 = none
        _ipp_enum("finishings-default", 3),
        _ipp_attr(V_KEYWORD, "sides-supported", "one-sided"),
        _ipp_attr(V_KEYWORD, "sides-default", "one-sided"),
        _ipp_attr(V_KEYWORD, "print-color-mode-supported", "color"),
        _ipp_additional_attr(V_KEYWORD, "monochrome"),
        _ipp_attr(V_KEYWORD, "print-color-mode-default", "color"),
        _ipp_attr(V_KEYWORD, "media-supported", "iso_a4_210x297mm"),
        _ipp_additional_attr(V_KEYWORD, "na_letter_8.5x11in"),
        _ipp_additional_attr(V_KEYWORD, "na_legal_8.5x14in"),
        _ipp_attr(V_KEYWORD, "media-default", "iso_a4_210x297mm"),
        _ipp_attr(V_KEYWORD, "compression-supported", "none"),
        _ipp_bool("multiple-document-jobs-supported", True),
        _ipp_int("multiple-operation-time-out", 60),
        _ipp_attr(V_KEYWORD, "which-jobs-supported", "not-completed"),
        _ipp_additional_attr(V_KEYWORD, "completed"),
        _ipp_attr(V_KEYWORD, "job-creation-attributes-supported",
                  "job-name"),
        _ipp_additional_attr(V_KEYWORD, "requesting-user-name"),
        _ipp_additional_attr(V_KEYWORD, "copies"),
        _ipp_additional_attr(V_KEYWORD, "media"),
        _ipp_additional_attr(V_KEYWORD, "print-color-mode"),
        _ipp_additional_attr(V_KEYWORD, "sides"),
    ]
    return _ipp_group(IPP_TAG_PRINTER, attrs)

def _ipp_job_group(job_id, state=IPP_JOB_PENDING, reasons=None,
                   name=None, user=None, created=None, size_kb=None,
                   queue_slug=None):
    """job-attributes group with correctly typed job-id (integer),
    job-state (enum) and job-state-reasons (keyword).
    v3.2.9 BUG 1: job-uri echoes the per-printer queue path so clients
    that remember the job see the SAME queue they printed to."""
    ip, port = _ipp_uri_base()
    jbase = ("ipp://%s:%d/ipp/print/%s" % (ip, port, queue_slug)
             if queue_slug else "ipp://%s:%d/ipp/print" % (ip, port))
    attrs = [
        _ipp_int("job-id", int(job_id)),
        _ipp_attr(V_URI, "job-uri",
                  "%s/job/%d" % (jbase, int(job_id))),
        _ipp_enum("job-state", state),
        _ipp_attr(V_KEYWORD, "job-state-reasons",
                  reasons or _ipp_job_state_reasons(state)),
    ]
    if name:
        attrs.append(_ipp_attr(V_NAME, "job-name", str(name)[:90]))
    if user:
        attrs.append(_ipp_attr(V_NAME, "job-originating-user-name",
                               str(user)[:60]))
    if created is not None:
        attrs.append(_ipp_int("time-at-creation", int(created)))
    if size_kb is not None:
        attrs.append(_ipp_int("job-k-octets", int(size_kb)))
    return _ipp_group(IPP_TAG_JOB, attrs)

def _ipp_job_state_reasons(state):
    return {IPP_JOB_PENDING: "none",
            IPP_JOB_PROCESSING: "job-printing",
            IPP_JOB_STOPPED: "processing-to-stop-point",
            IPP_JOB_CANCELED: "job-canceled-by-user",
            IPP_JOB_ABORTED: "job-aborted-by-system",
            IPP_JOB_COMPLETED: "job-completed-successfully",
            }.get(state, "none")

def _ipp_job_state_from_db(status):
    """db job status -> (IPP job-state enum, reasons keyword)."""
    return {"queued": (IPP_JOB_PENDING, "none"),
            "printing": (IPP_JOB_PROCESSING, "job-printing"),
            "printed": (IPP_JOB_COMPLETED, "job-completed-successfully"),
            "saved": (IPP_JOB_COMPLETED, "job-completed-successfully"),
            "failed": (IPP_JOB_ABORTED, "job-aborted-by-system"),
            "dead": (IPP_JOB_ABORTED, "job-aborted-by-system"),
            "canceled": (IPP_JOB_CANCELED, "job-canceled-by-user"),
            }.get(status, (IPP_JOB_PENDING, "none"))

def _ipp_row_koctets(row):
    """job-k-octets for a db job row (file size, best effort)."""
    try:
        return os.path.getsize(row.get("file_path") or "") // 1024
    except OSError:
        return 0

def _ipp_session_new(title, user, printer=""):
    """Create-Job: register an in-memory multi-document session with a
    guaranteed-unique id (1000000+ - never collides with db ids).
    Abandoned sessions are purged past multiple-operation-time-out.
    v3.0.9: printer carries the per-printer IPP queue target."""
    with _IPP_JOBS_LOCK:
        for k in [k for k, v in _IPP_JOBS.items()
                  if time.time() - v["created"] > IPP_MULTIDOC_TIMEOUT]:
            _IPP_JOBS.pop(k, None)
        _IPP_JOB_SEQ[0] += 1
        jid = _IPP_JOB_SEQ[0]
        _IPP_JOBS[jid] = {"title": title, "user": user, "chunks": [],
                          "bytes": 0, "done": False, "canceled": False,
                          "db_id": None, "created": time.time(),
                          "printer": printer or ""}
        return jid

def _ipp_session_doc_format(op_attrs, fallback="application/pdf"):
    """document-format operation attribute -> accepted or None."""
    fmt = (op_attrs.get("document-format") or fallback).strip().lower()
    if ";" in fmt:                       # strip ";parameter=value" suffix
        fmt = fmt.split(";", 1)[0].strip()
    if fmt in ("", "*"):
        fmt = fallback
    if fmt not in IPP_DOCUMENT_FORMATS and \
            fmt not in ("image/pwg-raster",):
        return None
    return fmt

def _ipp_op_int(op_raw, name, default=0):
    """Read a binary integer operation attribute (job-id...)."""
    entry = op_raw.get(name)
    if not entry:
        return default
    tag, val = entry
    if tag in (V_INT, V_ENUM) and len(val) == 4:
        return int.from_bytes(val, "big", signed=True)
    try:
        return int(val.decode("utf-8", "replace").strip() or default)
    except ValueError:
        return default

def _ipp_op_bool(op_raw, name, default=False):
    entry = op_raw.get(name)
    if not entry:
        return default
    tag, val = entry
    if tag == V_BOOL and val:
        return val[0] != 0
    s = val.decode("utf-8", "replace").strip().lower()
    return s in ("true", "t", "1", "yes")

def ipp_handle(data, ip, printer="", unknown_queue=""):
    """Top-level IPP request entry. Returns the IPP response bytes.
    Implements the RFC 8011 operations a desktop OS / phone print
    stack uses to add and drive a network printer:
      Print-Job, Print-URI, Validate-Job, Create-Job, Send-Document,
      Cancel-Job, Get-Job-Attributes, Get-Jobs, Get-Printer-Attributes.
    Every accepted document goes through the same pipeline as the
    Send portal; every request is audited with the source IP.
    v3.0.9: printer names a PER-PRINTER queue (/ipp/print/<printer>)
    - the document is routed to exactly that local printer instead of
    the hub's classic destination.
    v3.2.9 BUG 1: the queue context is echoed through every response
    (printer-uri-supported, printer-name/uuid, job-uri) and a queue
    name that arrives ONLY in the request's printer-uri op attribute
    (some clients put it there even on the generic HTTP path) is
    honoured too.
    v3.3.2 BUG 3: unknown_queue carries a per-printer slug that does
    NOT match any local printer. Get-Printer-Attributes still answers
    (printer-name = the requested slug, client URI echoed) so Windows
    "add printer" succeeds; documents fall back to the hub's default
    destination instead of dying on a JSON 404."""
    try:
        ver, op, rid, op_attrs, op_raw, doc = _ipp_parse(data)
    except Exception as e:
        log("[IPP] unparsable request from %s (%d bytes): %s"
            % (ip, len(data), e))
        return _ipp_response((1, 1), IPP_STATUS_BAD_REQUEST, 0, [])

    # v3.2.9 queue context: the HTTP route already resolved the queue
    # name into `printer`; some clients (Windows IPP class driver on a
    # manual add, Android print services) additionally carry the queue
    # URI in the printer-uri operation attribute even on the generic
    # path - resolve it so their jobs land on the RIGHT printer.
    q_slug = _ipp_queue_slug(printer) if printer else ""
    req_extra = []
    req_uri = (op_attrs.get("printer-uri") or "").strip()
    if not printer:
        if "/ipp/print/" in req_uri:
            try:
                tail = req_uri.split("/ipp/print/", 1)[1]
                tail = tail.split("/", 1)[0].split("?", 1)[0]
                resolved = _ipp_queue_match_cached(tail)
                if resolved:
                    printer = resolved
                    q_slug = _ipp_queue_slug(resolved)
                elif not unknown_queue:
                    # v3.3.2 BUG 3: the queue name rode ONLY in the
                    # printer-uri attribute (Windows manual add posts to
                    # the generic HTTP path) and it does not match any
                    # printer - treat it as the unknown queue so the add
                    # still validates with that name echoed.
                    unknown_queue = urllib.parse.unquote(tail)[:80]
            except Exception:
                pass
    if printer:
        # echo the EXACT URI the client used (both schemes) when it
        # differs from the canonical slug form
        for ex in _ipp_scheme_swaps(req_uri):
            if "/ipp/print/" in ex and ex not in req_extra:
                req_extra.append(ex)
    elif req_uri:
        # v3.2.9 BUG 3: even the GENERIC queue echoes the address the
        # client actually used - the canonical pair carries the hub's
        # own lan_ip, but a LAN PC that arrived via another address
        # (second NIC, hostname) must find ITS URI in the list too or
        # Windows refuses the generic queue with the same validation.
        for ex in _ipp_scheme_swaps(req_uri):
            if ex not in req_extra:
                req_extra.append(ex)

    if op == IPP_OP_GET_PRINTER_ATTR:                  # 0x000B
        # v3.2.9 BUG 1: ECHO the per-printer queue - printer-uri-supported
        # leads with the http:// + ipp:// forms of the queue URI the
        # client asked for, printer-name/uuid describe the queue. This is
        # the validation Windows/macOS/CUPS run during "add printer";
        # without the echo the named queue refused to connect from any
        # other PC while the generic /ipp/print kept working.
        # v3.3.2 BUG 3: an unknown slug still answers - printer-name is
        # the requested name and the client URI is echoed, so the ADD
        # succeeds (documents then print on the hub's destination).
        gpa_name = printer or (unknown_queue or "").strip()[:80]
        gpa_slug = q_slug or \
            (_ipp_queue_slug(unknown_queue) if unknown_queue else "")
        return _ipp_response(ver, IPP_STATUS_OK, rid,
                             [_ipp_printer_group(queue_slug=gpa_slug,
                                                 queue_name=gpa_name,
                                                 extra_uris=req_extra)])

    if op == IPP_OP_VALIDATE_JOB:                      # 0x0004
        # No job is created - successful-ok means "would accept".
        # v3.3.2 BUG 3: an unknown queue validates too (the add must not
        # die on a name Windows could not resolve yet).
        return _ipp_response(ver, IPP_STATUS_OK, rid, [])

    if op == IPP_OP_PRINT_JOB:                         # 0x0002
        if not doc:
            return _ipp_response(ver, IPP_STATUS_BAD_REQUEST, rid, [])
        fmt = _ipp_session_doc_format(op_attrs)
        if fmt is None:
            return _ipp_response(ver, IPP_STATUS_FORMAT_NOT_SUPPORTED,
                                 rid, [])
        title = (op_attrs.get("job-name") or
                 op_attrs.get("requesting-user-name") or "IPP job")
        user = op_attrs.get("requesting-user-name") or "ipp"
        if not printer and unknown_queue:
            log("[IPP] Print-Job on unknown queue %r from %s - printing "
                "on the hub default destination" % (unknown_queue[:60], ip))
        try:
            job_id, kind = route_print_payload(doc, str(title)[:90], ip,
                                               source="ipp", printer=printer)
        except ValueError as e:
            log("[IPP] rejected from %s: %s" % (ip, e))
            return _ipp_response(ver, IPP_STATUS_FORMAT_NOT_SUPPORTED,
                                 rid, [])
        except Exception as e:
            log("[IPP] print failed from %s: %s" % (ip, e))
            return _ipp_response(ver, IPP_STATUS_INTERNAL_ERROR, rid, [])
        log("[IPP] Print-Job from %s (%d KB, %s, %s) -> db job #%d"
            % (ip, len(doc) // 1024, fmt, kind, job_id))
        db_audit("print", job_id=job_id, ip=ip, site="lan",
                 printer=(printer or dest_display()),
                 details="IPP Print-Job %s (%d KB)" % (fmt,
                                                       len(doc) // 1024))
        return _ipp_response(ver, IPP_STATUS_OK, rid,
                             [_ipp_job_group(job_id, name=title,
                                             user=user,
                                             size_kb=len(doc) // 1024,
                                             queue_slug=q_slug)])

    if op == IPP_OP_PRINT_URI:                         # 0x0003
        url = (op_attrs.get("document-uri") or "").strip()
        if not url:
            return _ipp_response(ver, IPP_STATUS_BAD_REQUEST, rid, [])
        title = op_attrs.get("job-name") or "IPP URI job"
        user = op_attrs.get("requesting-user-name") or "ipp"
        try:
            pdf_url_guard(url)               # http/https only, LAN off
            data_bytes, _name = download_pdf(url)
        except Exception as e:
            log("[IPP] Print-URI rejected from %s (%s): %s" %
                (ip, url[:80], e))
            return _ipp_response(ver, IPP_STATUS_BAD_REQUEST, rid, [])
        try:
            job_id, kind = route_print_payload(data_bytes,
                                               str(title)[:90], ip,
                                               source="ipp", printer=printer)
        except ValueError as e:
            return _ipp_response(ver, IPP_STATUS_FORMAT_NOT_SUPPORTED,
                                 rid, [])
        except Exception as e:
            log("[IPP] Print-URI failed from %s: %s" % (ip, e))
            return _ipp_response(ver, IPP_STATUS_INTERNAL_ERROR, rid, [])
        log("[IPP] Print-URI from %s (%s) -> db job #%d" %
            (ip, url[:60], job_id))
        db_audit("print", job_id=job_id, ip=ip, site="lan",
                 printer=(printer or dest_display()),
                 details="IPP Print-URI (%s)" % url[:80])
        return _ipp_response(ver, IPP_STATUS_OK, rid,
                             [_ipp_job_group(job_id, name=title,
                                             user=user, queue_slug=q_slug)])

    if op == IPP_OP_CREATE_JOB:                        # 0x0005
        title = (op_attrs.get("job-name") or "IPP job")
        user = op_attrs.get("requesting-user-name") or "ipp"
        jid = _ipp_session_new(str(title)[:90], str(user)[:60],
                               printer=printer)
        log("[IPP] Create-Job from %s -> session #%d (%s)" %
            (ip, jid, title[:40]))
        return _ipp_response(ver, IPP_STATUS_OK, rid,
                             [_ipp_job_group(jid, name=title, user=user,
                                             queue_slug=q_slug)])

    if op == IPP_OP_SEND_DOCUMENT:                     # 0x0006
        jid = _ipp_op_int(op_raw, "job-id", 0)
        last = _ipp_op_bool(op_raw, "last-document", True)
        # v3.2.9 BUG 2: the session mutation runs under the lock -
        # several PCs (or one PC with parallel connections) feed
        # documents into sessions at the same moment and the unlocked
        # append/counter update could interleave.
        sess = None
        with _IPP_JOBS_LOCK:
            s0 = _IPP_JOBS.get(jid)
            if s0 is not None:
                if s0["canceled"]:
                    sess = s0
                else:
                    s0["chunks"].append(doc)
                    s0["bytes"] += len(doc)
                    sess = s0
        if not sess:
            return _ipp_response(ver, IPP_STATUS_NOT_FOUND, rid, [])
        if sess["canceled"]:
            return _ipp_response(ver, IPP_STATUS_NOT_POSSIBLE, rid, [])
        fmt = _ipp_session_doc_format(op_attrs)
        if fmt is None:
            return _ipp_response(ver, IPP_STATUS_FORMAT_NOT_SUPPORTED,
                                 rid, [])
        if not last:
            # more documents to come - acknowledge without printing
            return _ipp_response(ver, IPP_STATUS_OK, rid,
                                 [_ipp_job_group(jid, name=sess["title"],
                                                 user=sess["user"],
                                                 queue_slug=q_slug or
                                                 _ipp_queue_slug(
                                                     sess.get("printer", "")))])
        with _IPP_JOBS_LOCK:
            payload = b"".join(sess["chunks"])
        sess["done"] = True
        if not payload:
            _IPP_JOBS.pop(jid, None)
            return _ipp_response(ver, IPP_STATUS_BAD_REQUEST, rid, [])
        try:
            job_id, kind = route_print_payload(payload,
                                               sess["title"] or "IPP job",
                                               ip, source="ipp",
                                               printer=(printer or
                                                        sess.get("printer", "")))
        except ValueError as e:
            log("[IPP] rejected Send-Document from %s: %s" % (ip, e))
            return _ipp_response(ver, IPP_STATUS_FORMAT_NOT_SUPPORTED,
                                 rid, [])
        except Exception as e:
            log("[IPP] Send-Document failed from %s: %s" % (ip, e))
            return _ipp_response(ver, IPP_STATUS_INTERNAL_ERROR, rid, [])
        sess["db_id"] = job_id
        log("[IPP] Send-Document #%d from %s (%d KB, %s) -> db job #%d"
            % (jid, ip, len(payload) // 1024, kind, job_id))
        db_audit("print", job_id=job_id, ip=ip, site="lan",
                 printer=(printer or sess.get("printer", "") or dest_display()),
                 details="IPP Send-Document session #%d (%d KB)"
                         % (jid, len(payload) // 1024))
        return _ipp_response(ver, IPP_STATUS_OK, rid,
                             [_ipp_job_group(job_id, name=sess["title"],
                                             user=sess["user"],
                                             size_kb=len(payload) // 1024,
                                             queue_slug=q_slug or
                                             _ipp_queue_slug(
                                                 sess.get("printer", "")))])

    if op == IPP_OP_CANCEL_JOB:                        # 0x0008
        # RFC 8011 §4.3.4: job-id is REQUIRED for Cancel-Job
        if "job-id" not in op_raw:
            return _ipp_response(ver, IPP_STATUS_BAD_REQUEST, rid, [])
        jid = _ipp_op_int(op_raw, "job-id", 0)
        sess = None
        with _IPP_JOBS_LOCK:
            s0 = _IPP_JOBS.get(jid)
            if s0 is not None:
                s0["canceled"] = True
                s0["done"] = True
                sess = s0
        if sess is not None:
            log("[IPP] Cancel-Job: session #%d dropped" % jid)
            return _ipp_response(ver, IPP_STATUS_OK, rid,
                                 [_ipp_job_group(jid, IPP_JOB_CANCELED,
                                                 name=sess.get("title"),
                                                 queue_slug=_ipp_queue_slug(
                                                     sess.get("printer", "")))])
        job = db_get(jid) if jid else None
        if not job:
            return _ipp_response(ver, IPP_STATUS_NOT_FOUND, rid, [])
        if job["status"] in ("printed", "failed", "canceled", "saved",
                             "dead", "forwarded"):
            return _ipp_response(ver, IPP_STATUS_NOT_POSSIBLE, rid,
                                 [_ipp_job_group(jid, name=job["title"])])
        db_update(job["id"], status="canceled",
                  error="canceled via IPP", held_reason=None)
        cancel_current_print()
        db_audit("job.canceled", job_id=job["id"], ip=ip, site="lan",
                 printer=job.get("printer"),
                 details="canceled via IPP Cancel-Job")
        log("[IPP] Cancel-Job: db job #%d canceled" % jid)
        return _ipp_response(ver, IPP_STATUS_OK, rid,
                             [_ipp_job_group(jid, IPP_JOB_CANCELED,
                                             name=job["title"])])

    if op == IPP_OP_GET_JOB_ATTR:                      # 0x0009
        jid = _ipp_op_int(op_raw, "job-id", 0)
        # v3.2.9 BUG 2: snapshot the session fields under the lock so a
        # concurrent Send-Document cannot change counters mid-read.
        with _IPP_JOBS_LOCK:
            s0 = _IPP_JOBS.get(jid)
            sess = dict(s0) if s0 is not None else None
        if sess is not None:
            if sess["canceled"]:
                return _ipp_response(ver, IPP_STATUS_OK, rid,
                                     [_ipp_job_group(jid, IPP_JOB_CANCELED,
                                                     name=sess["title"],
                                                     user=sess["user"],
                                                     size_kb=sess["bytes"]
                                                     // 1024)])
            if sess["done"] and sess["db_id"]:
                row = db_get(sess["db_id"])
                if row:
                    st, rs = _ipp_job_state_from_db(row["status"])
                    return _ipp_response(ver, IPP_STATUS_OK, rid,
                                         [_ipp_job_group(
                                             jid, st, rs,
                                             name=sess["title"],
                                             user=sess["user"],
                                             size_kb=sess["bytes"]
                                             // 1024)])
            return _ipp_response(ver, IPP_STATUS_OK, rid,
                                 [_ipp_job_group(jid, name=sess["title"],
                                                 user=sess["user"],
                                                 created=sess["created"],
                                                 size_kb=sess["bytes"]
                                                 // 1024)])
        job = db_get(jid) if jid else None
        if not job:
            return _ipp_response(ver, IPP_STATUS_NOT_FOUND, rid, [])
        st, rs = _ipp_job_state_from_db(job["status"])
        return _ipp_response(ver, IPP_STATUS_OK, rid,
                             [_ipp_job_group(jid, st, rs,
                                             name=job["title"],
                                             size_kb=_ipp_row_koctets(job))])

    if op == IPP_OP_GET_JOBS:                          # 0x000A
        which = (op_attrs.get("which-jobs") or "not-completed").strip()
        my = _ipp_op_bool(op_raw, "my-jobs", False)
        user = (op_attrs.get("requesting-user-name") or "").strip()
        limit = 20
        groups = []
        with _IPP_JOBS_LOCK:
            sessions = sorted(_IPP_JOBS.items())
        for sid, s in sessions:
            if s["canceled"] or s["done"]:
                continue                # sessions appear only while open
            if my and user and s["user"] and s["user"] != user:
                continue
            groups.append(_ipp_job_group(sid, name=s["title"],
                                         user=s["user"],
                                         created=s["created"],
                                         size_kb=s["bytes"] // 1024))
        for row in db_list(limit=limit):
            completed = row["status"] in ("printed", "failed", "canceled",
                                          "saved", "dead", "forwarded")
            if which == "completed" and not completed:
                continue
            if which != "completed" and completed:
                continue
            if my and user:
                src = (row.get("source") or "").strip()
                if src and src != user:
                    continue
            st, rs = _ipp_job_state_from_db(row["status"])
            groups.append(_ipp_job_group(row["id"], st, rs,
                                         name=row["title"],
                                         size_kb=_ipp_row_koctets(row)))
        return _ipp_response(ver, IPP_STATUS_OK, rid, groups[:limit])

    # every other operation: not implemented
    log("[IPP] operation 0x%04X from %s not supported" % (op, ip))
    return _ipp_response(ver, IPP_STATUS_OP_NOT_SUPPORTED, rid, [])

def route_print_payload(data, title, ip, source="raw9100", printer=""):
    """Shared routing for IPP Print-Job and the RAW 9100 listener.
    Returns (job_id, kind). Raises ValueError for unsupported data.
    v3.0.9: printer="" keeps the classic destination (dest_mode /
    default printer); a per-printer IPP queue passes the REAL local
    printer name so the job prints on exactly that printer."""
    if not data:
        raise ValueError("empty print payload")
    if len(data) > MAX_PDF:
        raise ValueError("payload too large - the limit is %d MB"
                         % (MAX_PDF // (1024 * 1024)))
    _dest = printer or ""
    if data.startswith(b"%PDF"):
        job, dup = enqueue_print("a4", title[:90], data, printer=_dest,
                                 source=source, dedupe=False, origin_ip=ip)
        db_audit("print", job_id=job, ip=ip, site="lan",
                 printer=(_dest or dest_display()),
                 details="%s PDF payload (%d KB)%s"
                         % (source, len(data) // 1024,
                            " (duplicate held)" if dup else ""))
        return job, "pdf"
    if data[:3] == b"\xff\xd8\xff":
        try:
            pdf, _name = image_pdf_bytes(data, title=title)
        except Exception as e:
            raise ValueError("bad JPEG: %s" % e)
        job, dup = enqueue_print("a4", title[:90], pdf, printer=_dest,
                                 source=source, dedupe=False, origin_ip=ip)
        db_audit("print", job_id=job, ip=ip, site="lan",
                 printer=(_dest or dest_display()),
                 details="%s JPEG payload (%d KB)" % (source,
                                                      len(data) // 1024))
        return job, "jpeg"
    # everything below is printer-language passthrough (winspool RAW /
    # lp -o raw): PCL, PostScript, ZPL, ESC/POS...
    # v2.9.1 (audit M5 fix): the passthrough is now ENQUEUED like every
    # other payload instead of printing synchronously inside the socket
    # thread - it gets a history row, pause/cancel/reprint, and the
    # dest_mode routing (selected/default/IP printer). The old
    # synchronous print_raw() had no history row and audit job_id=0.
    try:
        job, _dup = enqueue_print("raw", title[:90], data, printer=_dest,
                                  source=source, dedupe=False, origin_ip=ip)
        db_audit("print", job_id=job, ip=ip, site="lan",
                 printer=(_dest or dest_display()),
                 details="%s raw passthrough %s (%d KB)"
                         % (source, _sniff_lang(data), len(data) // 1024))
        log("[RAW9100] %s payload from %s (%d KB) -> queued #%d -> %s"
            % (_sniff_lang(data), ip, len(data) // 1024, job,
               _dest or dest_display()))
    except Exception as e:
        db_audit("print.failed", ip=ip, site="lan",
                 details="%s raw passthrough failed: %s" % (source, e))
        raise ValueError("raw passthrough failed: %s" % e)
    return job, _sniff_lang(data)

def _sniff_lang(data):
    """Human name for a raw printer-language payload."""
    if data.startswith(b"%!PS"):
        return "postscript"
    if data.startswith(b"\x1b%-12345X") or data.startswith(b"\x1bE"):
        return "pcl"
    if data.startswith(b"^XA") or b"^XA" in data[:64]:
        return "zpl"
    if data.startswith(b"\x1b@"):
        return "escpos"
    return "raw"

# v2.9.1 (audit M5 fix): at most 8 concurrent RAW 9100 connections - the
# old accept loop spawned one unbounded daemon thread per connection, so
# a forklift of open sockets could exhaust memory/threads.
_RAW_SEM = threading.BoundedSemaphore(8)

def _raw_conn_handler(conn, addr):
    """One JetDirect connection: read until the client closes or an
    idle timeout hits, then route the payload. Releases the shared
    connection slot on exit."""
    ip = addr[0] if isinstance(addr, tuple) else "unknown"
    try:
        conn.settimeout(15)
        chunks = []
        total = 0
        # v2.9.1 (audit M5 fix): the old loop condition was
        # "while total <= MAX_PDF" and the cap-crossing chunk was STILL
        # appended - a 30 MB payload got truncated to 25 MB and the
        # TRUNCATED bytes were printed with no error. Now: stop reading
        # at the cap and REJECT the whole payload.
        while total < MAX_PDF:
            try:
                b = conn.recv(65536)
            except socket.timeout:
                break
            if not b:
                break
            chunks.append(b)
            total += len(b)
        if total > MAX_PDF:
            log("[RAW9100] %s payload too large (%d KB > %d KB cap) -"
                " rejected (send PDFs over HTTP /print or /send)"
                % (ip, total // 1024, MAX_PDF // 1024))
            return
        data = b"".join(chunks)
        if not data:
            return
        try:
            route_print_payload(data, "RAW print", ip, source="raw9100")
        except Exception as e:
            log("[RAW9100] rejected %s: %s" % (ip, e))
    finally:
        _RAW_SEM.release()             # v2.9.1 (M5): free the slot
        try:
            conn.close()
        except OSError:
            pass

def raw_listen_active():
    return bool(_RAW_SOCKS)

def raw_listen_start():
    """Bind the RAW JetDirect listener on EVERY interface, IPv4 AND
    IPv6 (bind_listener_sockets). Returns an error string or None.
    v3.3.0 BUG 2: the old single lan_ip() bind made the RAW printer
    port deaf on every other adapter and silent on IPv6 - now every
    interface IP of this PC accepts JetDirect jobs on both stacks,
    still gated by the same allowed_ips ACL per connection."""
    global _RAW_SOCKS, _RAW_THREADS, _RAW_BINDS, _RAW_BIND_SIG
    port = int(CFG.get("raw_printer_port") or 0)
    if port <= 0 or not CFG.get("share_lan"):
        return None
    if _RAW_SOCKS:
        return None
    try:
        socks, errs = bind_listener_sockets(port, "RAW 9100")
    except OSError as e:
        return "cannot bind RAW %s" % e
    _RAW_SOCKS = socks
    _RAW_BINDS = [_sock_label(s) for s in socks]

    def _accept_loop(srv):
        while _RAW_SOCKS and srv in _RAW_SOCKS:
            try:
                conn, addr = srv.accept()
            except OSError:
                break
            # v3.2.3 ALLOWED IPS - the RAW 9100 port honours the same
            # list: a blocked IP gets an instant close, no print channel
            peer = addr[0] if isinstance(addr, tuple) else "?"
            if "*" not in (CFG.get("allowed_ips") or ["*"]) and \
                    not ip_allowed_by_list(peer, CFG.get("allowed_ips")):
                log("[ACL] %s denied on the RAW 9100 port" % peer)
                try:
                    db_audit("acl.denied", ip=peer,
                             details="RAW 9100: IP not on allowed_ips list")
                except Exception:
                    pass
                try:
                    conn.close()
                except OSError:
                    pass
                continue
            # v2.9.1 (audit M5 fix): bounded concurrency - extra
            # connections are closed immediately with a log line
            if not _RAW_SEM.acquire(blocking=False):
                log("[RAW9100] %s dropped - too many concurrent RAW"
                    " connections (max 8)" % (addr[0] if isinstance(addr, tuple) else "?"))
                try:
                    conn.close()
                except OSError:
                    pass
                continue
            t = threading.Thread(target=_raw_conn_handler, args=(conn, addr),
                                 daemon=True, name="advprint-raw9100")
            t.start()
        try:
            srv.close()
        except OSError:
            pass

    for s in socks:
        t = threading.Thread(target=_accept_loop, args=(s,), daemon=True,
                             name="advprint-raw-accept")
        _RAW_THREADS.append(t)
        t.start()
    _RAW_BIND_SIG = _bind_signature()
    log("[RAW9100] JetDirect printer port UP on %s - other PCs can add"
        " this PC as a Standard TCP/IP port printer (IPv4 + IPv6)%s"
        % (", ".join(_RAW_BINDS),
           " (failed: %s)" % "; ".join(errs) if errs else ""))
    return None

def raw_listen_stop():
    global _RAW_SOCKS, _RAW_THREADS, _RAW_BINDS, _RAW_BIND_SIG
    socks = _RAW_SOCKS
    if not socks:
        return
    _RAW_SOCKS = []
    _RAW_THREADS = []
    _RAW_BINDS = []
    _RAW_BIND_SIG = None
    for srv in socks:
        try:
            srv.close()          # accept loops exit on the OSError
        except OSError:
            pass
    log("[RAW9100] printer port stopped")

def raw_listen_ensure():
    """Health-refresher hook (runs every 3 s): start/stop/rebind the
    RAW listeners following share_lan + raw_printer_port + the live
    interface set (v3.3.0 BUG 2: DHCP / Wi-Fi / VPN changes)."""
    want = bool(CFG.get("share_lan")) and \
        int(CFG.get("raw_printer_port") or 0) > 0
    if want and not _RAW_SOCKS:
        err = raw_listen_start()
        if err:
            log("[RAW9100] auto-start: %s" % err)
    elif not want and _RAW_SOCKS:
        raw_listen_stop()
    elif want and _RAW_BIND_SIG is not None and \
            _RAW_BIND_SIG != _bind_signature():
        raw_listen_stop()
        raw_listen_start()

def ipp_printer_enabled():
    return bool(CFG.get("ipp_printer", True))


def ipp_landing_html(req_host=None, req_port=None):
    """v3.2.2: the IPP how-to page served when a HUMAN opens the printer
    URL in a browser (GET /ipp/print). Shared by the main hub listener
    and the standard-port mirror - one source, both ports.
    v3.2.9 BUG 3: the primary URLs use the address THE OPENING DEVICE
    used (Host header) when it is a real LAN address, so every PC/phone
    sees its own reachable ip:port - never one stale global lan_ip().
    The page also states WHO may print (allowed_ips rules) so a denied
    or restricted device understands the hub's ACL at a glance."""
    host = socket.gethostname()
    # v3.2.9 BUG 3: per-device base address. Loopback-only Host headers
    # (the hub owner opening the page on the hub itself) fall back to
    # the hub's best LAN address so the owner still copies a shareable
    # URL; a LAN device keeps the exact address it reached the hub with.
    rip = (str(req_host or "").strip().lower() or None)
    if rip in ("localhost", "127.0.0.1", "::1") or \
            (rip or "").startswith("127."):
        rip = None
    ip = rip or (lan_ip() if CFG.get("share_lan") else "127.0.0.1")
    port = int(req_port) if req_port else int(CFG.get("port", 9235))
    # v3.2.8 BUG FIX 1: lan_share_url("ipp") returns the http:// URL -
    # v3.2.7 pushed it through .replace("ipp://", "") (a no-op) and wrote
    # the template's ipp:// in FRONT of it -> ipp://http://ip:port/...
    # (protocol twice). ipp_scheme_bare() strips the web scheme first, so
    # the page now shows the one clean printer URL: ipp://ip:9235/ipp/print
    ipp_url = ipp_scheme_bare("http://%s:%d/ipp/print" % (ip, port))
    http_url = "http://%s:%d/ipp/print" % (ip, port)
    std = int(CFG.get("ipp_standard_port") or 0)
    std_note = ""
    if std > 0 and _IPP631_STATE.get("up"):
        std_note = ("<li>Standard port also UP: <code>http://%s:%d/ipp/print"
                    "</code> - Android's manual add and most printer "
                    "dialogs default to port %d.</li>"
                    % (_html_escape(ip), std, std))
    # v3.2.9 BUG 2: say WHO may print (allowed_ips / * enforcement)
    rules = [str(r) for r in (CFG.get("allowed_ips") or ["*"])]
    if "*" in rules:
        acl_note = ("<b>Who may print:</b> every device on the LAN"
                    " (allowed_ips <code>*</code> - the factory"
                    " default). The hub owner can restrict this in"
                    " THE ONE UI &#8594; LAN Sharing &#8594; Allowed IPs.")
    else:
        shown = _html_escape(", ".join(rules[:6]))
        acl_note = ("<b>Who may print:</b> only devices on the hub's"
                    " Allowed-IPs list (<code>%s%s</code>) - this device"
                    " sees this page, so it is on the list. The hub PC"
                    " itself (127.0.0.1) is always allowed."
                    % (shown, " ..." if len(rules) > 6 else ""))
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport"
 content="width=device-width,initial-scale=1"><title>AdvPrint Pro - IPP printer</title>
<style>body{font:15px/1.55 "Segoe UI",system-ui,sans-serif;background:#f5f8fc;
 color:#0f172a;margin:0;padding:24px}.b{max-width:640px;margin:4vh auto;background:#fff;
 border:1px solid #e2e8f0;border-radius:14px;padding:22px}
 h1{font-size:19px;margin:0 0 6px}h2{font-size:15px;margin:18px 0 6px;color:#1d4ed8}
 code{background:#f1f5f9;border:1px solid #e2e8f0;border-radius:4px;padding:1px 6px;
 font-size:12.5px;word-break:break-all}li{margin:5px 0}
 .ok{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:10px 14px;
 margin:14px 0;font-size:13.5px}</style></head><body><div class="b">
 <h1>AdvPrint Pro - IPP network printer</h1>
 <p>This URL is the <b>IPP print endpoint of <span>%s</span></b>.
 Add it as a printer - do not open it in a browser:</p>
 <p style="font-size:16px"><code>ipp://%s</code></p>
 <p style="font-size:16px"><code>%s</code></p>
 <p style="font-size:12px;color:#475569">URLs above use the address
 <b>THIS device</b> reached the hub with - other PCs may prefer one of
 the hub's other addresses (see the hub console LAN panel).</p>
 <h2>Windows 10 / 11</h2>
 <ul><li>Settings &rarr; Bluetooth &amp; devices &rarr; Printers &amp;
 scanners &rarr; <b>Add device</b>. The printer appears by itself
 (AirPrint-style discovery) when LAN sharing is on - click it.</li>
 <li>Or: <b>Add manually</b> &rarr; &ldquo;Add a printer using an IP
 address or hostname&rdquo; &rarr; Device type <b>IPP Device</b> &rarr;
 paste <code>%s</code> &rarr; Next.</li></ul>
 <h2>macOS</h2>
 <ul><li>System Settings &rarr; Printers &amp; Scanners &rarr;
 <b>Add Printer</b> - it appears in the Bonjour list.</li>
 <li>Or: IP tab &rarr; Protocol <b>IPP</b> &rarr; Address
 <code>%s:%d</code> &rarr; Queue <code>ipp/print</code>.</li></ul>
 <h2>iPhone / iPad (AirPrint)</h2>
 <ul><li>Open anything printable &rarr; Share &rarr; Print &rarr;
 Select Printer - <b>AdvPrint Pro appears by itself</b> while this PC
 is on the same Wi-Fi.</li></ul>
 <h2>Android</h2>
 <ul><li>Print from any app &rarr; Default Print Service / Mopria -
 the printer is discovered automatically.</li>
 %s</ul>
 <div class="ok">%s<br><b>Prints go to THIS PC's printer</b> through the
 AdvPrint Pro hub - the PC must be on and the hub running (tray icon).
 The first job also shows in the hub history like every other print.
 100%% local - powered by AdvPrint Pro %s.</div>
 </div></body></html>""" % (
        _html_escape(host),
        _html_escape(ipp_url, quote=True),
        _html_escape(http_url, quote=True),
        _html_escape(http_url, quote=True),
        _html_escape(host),
        port,
        std_note,
        acl_note,
        VERSION)


# ------------------------------------------------------------
# v3.2.2 STANDARD-PORT IPP MIRROR - the SAME IPP printer endpoint
# ALSO answered on the standard printer port (631) on the LAN IP.
#
# Why: Android's Default Print Service / Mopria IGNORES custom ports
# when a printer is added manually (the user types just the IP) and
# tries http://<ip>:631/ipp/print. Plenty of printer dialogs and
# CUPS defaults assume 631 as well. The hub's own port (9235) stays
# the primary endpoint; this mirror exists so EVERY IPP pattern
# works: ipp://ip:9235/ipp/print, http://ip:9235/ipp/print AND
# http://ip:631/ipp/print.
#
# Scope is intentionally tiny - this listener serves ONLY the IPP
# print endpoint + its landing page; everything else is redirected
# to the hub's main port. Same rules as the main endpoint: no token
# (like a physical network printer), browser Origins refused, body
# size caps, every job audited. Windows needs no admin for ports
# < 1024; on macOS/Linux the bind may need root - a refused bind
# only disables the MIRROR, never the hub. Control: config.json
# "ipp_standard_port": 631 (default) | other port | 0 = off.
# ------------------------------------------------------------
_IPP631_HTTPDS = []               # v3.3.0 BUG 2: one server per stack
_IPP631_THREADS = []
_IPP631_BINDS = []                # labels of the sockets actually bound
_IPP631_BIND_SIG = None
_IPP631_STATE = {"up": False, "port": 0, "err": ""}


def _ipp631_server_on(sock):
    """_IPP631Server on an ALREADY-BOUND listening socket - the dual-stack
    helper owns bind+listen (v3.3.0 BUG 2), so the server skips its own
    socket creation entirely."""
    srv = _IPP631Server(("127.0.0.1", 0), IPP631Handler,
                        bind_and_activate=False)
    try:
        srv.socket.close()
    except OSError:
        pass
    srv.socket = sock
    try:
        srv.server_address = sock.getsockname()
    except Exception:
        pass
    srv.server_activate()
    srv.daemon_threads = True
    return srv


class _IPP631Server(ThreadingHTTPServer):
    # v3.2.9 BUG 2: accept backlog 128 (see HubServer) - several phones
    # + PCs may open print connections through the standard port at the
    # same moment; the default backlog of 5 refused the burst.
    request_queue_size = 128


class IPP631Handler(BaseHTTPRequestHandler):
    """Restricted HTTP handler for the standard-port IPP mirror."""

    protocol_version = "HTTP/1.1"
    # v3.2.9 BUG 2: same per-connection timeout as the main handler -
    # phones and PCs that vanish mid-conversation release their thread.
    timeout = 30

    def log_message(self, fmt, *args):     # silence stderr, use hub log
        pass

    def _client_ip(self):
        try:
            return self.client_address[0]
        except Exception:
            return "?"

    def _is_loopback(self):
        return self._client_ip() in (
            "127.0.0.1", "::1", "localhost",
            "::ffff:127.0.0.1", "::ffff:127.0.0.1%0")

    def _landing(self):
        try:
            # v3.2.9 BUG 3: the landing page mirrors the address the
            # phone/PC actually used to reach the mirror (Host header;
            # usually ip:631) - never one stale global hub IP.
            h, p = _sanitize_host_hdr(self.headers.get("Host"))
            page = ipp_landing_html(req_host=(h if h and not
                                              h.startswith("127.")
                                              and h != "localhost" else None),
                                    req_port=(int(p) if p and p.isdigit()
                                              else None)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _redirect(self, where):
        try:
            self.send_response(302)
            self.send_header("Location", where)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _ipp_reply(self, body):
        self.send_response(200)
        self.send_header("Content-Type", IPP_MIME)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        # v3.2.3 ALLOWED IPS - the 631 mirror honours the same list
        if not self._is_loopback() and "*" not in (
                CFG.get("allowed_ips") or ["*"]) and not ip_allowed_by_list(
                self._client_ip() or "", CFG.get("allowed_ips")):
            log("[ACL] %s denied on the 631 IPP mirror" % self._client_ip())
            return self._send_json(403, {
                "ok": False,
                "error": "access denied - this IP is not on the hub's"
                         " allowed_ips list"})
        u = urlparse(self.path)
        route = u.path.rstrip("/")
        if route in ("/ipp/print", "/ipp", "/ipp/") and \
                ipp_printer_enabled():
            return self._landing()
        if route.startswith("/ipp/print/"):
            return self._landing()
        # everything else belongs on the main hub port
        port = int(CFG.get("port", 9235))
        # v3.3.0 BUG 2: redirect to THIS socket's own address first (the
        # client reached the mirror on it, so it is reachable), else the
        # first bound listener, else the best LAN IP
        redir_host = ""
        try:
            h0 = _sanitize_host_hdr(self.headers.get("Host"))[0]
            if h0 and h0 not in ("localhost", "127.0.0.1", "::1") and \
                    not h0.startswith("127."):
                redir_host = h0
        except Exception:
            redir_host = ""
        if not redir_host and _IPP631_BINDS:
            redir_host = _IPP631_BINDS[0].rsplit(":", 1)[0].strip("[]")
        ip = redir_host or lan_ip() or "127.0.0.1"
        self._redirect("http://%s:%d%s" % (ip, port, self.path))

    def do_POST(self):
        # v3.2.3 ALLOWED IPS - same rule for print jobs on 631
        if not self._is_loopback() and "*" not in (
                CFG.get("allowed_ips") or ["*"]) and not ip_allowed_by_list(
                self._client_ip() or "", CFG.get("allowed_ips")):
            log("[ACL] %s denied POST on the 631 IPP mirror"
                % self._client_ip())
            try:
                db_audit("acl.denied", ip=self._client_ip(),
                         details="631 mirror: IP not on allowed_ips list")
            except Exception:
                pass
            return self._send_json(403, {
                "ok": False,
                "error": "access denied - this IP is not on the hub's"
                         " allowed_ips list"})
        u = urlparse(self.path)
        route = u.path.rstrip("/")
        ipp_q_printer = ""
        ipp_q_unknown = ""
        if route.startswith("/ipp/print/"):
            ipp_q_printer = _ipp_queue_match_cached(
                urllib.parse.unquote(route[len("/ipp/print/"):]))
            if not ipp_q_printer:
                # v3.3.2 BUG 3: unknown slug answered as the generic queue
                # (Windows add must not die on the standard port either)
                ipp_q_unknown = urllib.parse.unquote(
                    route[len("/ipp/print/"):])[:80]
                db_audit("ipp.queue.reject", ip=self._client_ip(),
                         site="lan", details="631 mirror: unknown "
                         "per-printer IPP queue %r (answered as generic)"
                         % route[:120])
            route = "/ipp/print"
        if route not in ("/ipp/print", "/ipp", "/ipp/") or \
                not ipp_printer_enabled():
            return self._send_json(404, {"ok": False,
                                         "error": "IPP printer is off"})
        # same anti-web guard as the main endpoint (audit H6)
        ipp_origin = (self.headers.get("Origin") or "").strip()
        if ipp_origin and ipp_origin.lower() != "null" \
                and not _extension_origin(ipp_origin):
            return self._send_json(403, {
                "ok": False,
                "error": "IPP is for native print clients"})
        try:
            data = read_raw_body(self)
        except ValueError as e:
            return self._send_json(400, {"ok": False,
                                         "error": "bad IPP request: %s" % e})
        if len(data) > MAX_PDF:
            return self._send_json(413, {"ok": False,
                                         "error": "IPP request too large"})
        resp = ipp_handle(data, self._client_ip(), printer=ipp_q_printer,
                          unknown_queue=ipp_q_unknown)
        self._ipp_reply(resp)

    def _send_json(self, code, obj):
        try:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def ipp631_listen_start():
    """Bind the standard-port IPP mirror on EVERY interface, IPv4 AND
    IPv6 (bind_listener_sockets). Returns an error string or None.
    v3.3.0 BUG 2: the old single lan_ip() bind answered on ONE address
    only - phones/PCs on the hub's other adapters (and anything on
    IPv6) found port 631 closed even though the hub was up."""
    global _IPP631_HTTPDS, _IPP631_THREADS, _IPP631_BINDS, _IPP631_BIND_SIG
    port = int(CFG.get("ipp_standard_port") or 0)
    if port <= 0 or not ipp_printer_enabled():
        return None
    if _IPP631_HTTPDS:
        return None
    try:
        socks, errs = bind_listener_sockets(port, "IPP mirror")
    except OSError as e:
        _IPP631_STATE.update({"up": False, "port": port,
                              "err": "port %d busy/refused (%s)" % (port, e)})
        return ("cannot bind IPP mirror (%s) - on macOS/Linux the "
                "standard port needs root; the hub's own port still "
                "works everywhere" % e)
    opened = []
    for s in socks:
        try:
            httpd = _ipp631_server_on(s)
        except Exception as e:
            try:
                s.close()
            except OSError:
                pass
            errs.append("%s: %s" % (_sock_label(s), e))
            continue
        opened.append(httpd)
    if not opened:
        for s in socks:
            try:
                s.close()
            except OSError:
                pass
        _IPP631_STATE.update({"up": False, "port": port,
                              "err": "; ".join(errs) or "bind failed"})
        return "cannot bind IPP mirror %d (%s)" % (port, "; ".join(errs))
    _IPP631_HTTPDS = opened
    _IPP631_BINDS = [_sock_label(s) for s in socks[:len(opened)]]
    for httpd in opened:
        t = threading.Thread(target=httpd.serve_forever,
                             kwargs={"poll_interval": 0.2},
                             name="advprint-ipp631", daemon=True)
        _IPP631_THREADS.append(t)
        t.start()
    _IPP631_BIND_SIG = _bind_signature()
    _IPP631_STATE.update({"up": True, "port": port, "err": ""})
    log("[IPP631] standard-port printer UP on %s /ipp/print - Android"
        " manual add and printer dialogs that assume port %d work now"
        " (IPv4 + IPv6)%s"
        % (", ".join(_IPP631_BINDS), port,
           " (failed: %s)" % "; ".join(errs) if errs else ""))
    return None


def ipp631_listen_stop():
    global _IPP631_HTTPDS, _IPP631_THREADS, _IPP631_BINDS, _IPP631_BIND_SIG
    httpds = _IPP631_HTTPDS
    if not httpds:
        return
    _IPP631_HTTPDS = []
    _IPP631_THREADS = []
    _IPP631_BINDS = []
    _IPP631_BIND_SIG = None
    _IPP631_STATE.update({"up": False, "port": 0, "err": ""})
    # synchronous close (the ensure() rebind path may follow instantly -
    # the new binds must not race the old sockets still being open)
    for httpd in httpds:
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
    log("[IPP631] standard-port printer stopped")


def ipp631_listen_ensure():
    """Health-refresher hook: start/stop/rebind the 631 mirror
    following ipp_printer + ipp_standard_port + the live interface set
    (v3.3.0 BUG 2: DHCP / Wi-Fi / VPN changes too)."""
    want_port = int(CFG.get("ipp_standard_port") or 0)
    want = want_port > 0 and ipp_printer_enabled()
    if want and not _IPP631_HTTPDS:
        err = ipp631_listen_start()
        if err:
            log("[IPP631] auto-start: %s" % err)
    elif not want and _IPP631_HTTPDS:
        ipp631_listen_stop()
    elif want and _IPP631_BIND_SIG is not None and \
            _IPP631_BIND_SIG != _bind_signature():
        ipp631_listen_stop()
        ipp631_listen_start()
    if want and _IPP631_STATE.get("up"):
        _IPP631_STATE["err"] = ""
    else:
        _IPP631_STATE.setdefault("up", False)


# ------------------------------------------------------------
# v3.0.8 AIRPRINT-GRADE DISCOVERY - mDNS / DNS-SD announcer.
# Manually typing http://192.168.1.x:9235/ipp/print works on
# Windows/macOS, but PHONES discover printers through mDNS
# (Bonjour). With this responder running, the hub shows up by
# itself in:
#   - Windows 10/11 "Settings -> Printers -> Add device"
#     (Windows browses _ipp._tcp since 1903)
#   - iOS AirPrint picker (needs the _universal subtype + URF TXT)
#   - Android Default/Mopria Print Service
#   - macOS "Add Printer" (Bonjour list)
# Pure stdlib (RFC 6762/6763 subset): one UDP multicast socket,
# queries answered + proactive announces, no third-party deps.
# Fail-safe by design: any error only disables DISCOVERY, never
# printing (the /ipp/print endpoint keeps working). Control:
# config.json "ipp_mdns": true|false. Announces ONLY while LAN
# sharing is on and bound to a real LAN IP - loopback is never
# advertised. Windows firewall needs inbound UDP 5353 (the Setup
# exe adds it; the dashboard firewall button covers TCP only).
# ------------------------------------------------------------
_MDNS_PORT = 5353
_MDNS_GROUP = "224.0.0.251"
_MDNS_TTL = 4500                    # advertised record TTL (75 min)
_MDNS_ANNOUNCE_EVERY = 1500         # proactive re-announce cadence (25 min)
_MDNS_QTYPE_A = 1
_MDNS_QTYPE_AAAA = 28               # v3.3.0 BUG 2: IPv6 answer record
_MDNS_QTYPE_PTR = 12
_MDNS_QTYPE_TXT = 16
_MDNS_QTYPE_SRV = 33
_MDNS_QTYPE_ANY = 255

_mdns_state = {"sock": None, "thread": None, "ip": None,
               "last_announce": 0.0, "announced": False, "err_logged": False}


def _mdns_instance_name():
    """Service instance shown in printer pickers."""
    host = (socket.gethostname() or "").strip() or "This PC"
    return ("AdvPrint Pro @ %s" % host).replace(".", "-")


def _mdns_host_target():
    h = re.sub(r"[^A-Za-z0-9-]", "-",
               (socket.gethostname() or "").strip() or "advprint")
    return (h or "advprint").strip("-").lower() + ".local"


def _mdns_encode_name(name):
    """DNS wire name ("Instance._ipp._tcp.local" -> labels)."""
    out = bytearray()
    for label in name.rstrip(".").split("."):
        if not label:
            continue
        lb = label.encode("utf-8")[:63]
        out += bytes([len(lb)]) + lb
    out += b"\x00"
    return bytes(out)


def _mdns_txt_records(rp="ipp/print", ty="AdvPrint Pro",
                      note="AdvPrint Pro print hub"):
    """AirPrint TXT for one service. v3.0.9: rp/ty/note are per-service
    so every per-printer queue advertises its own ipp/print/<printer>."""
    kv = [("txtvers", "1"), ("qtotal", "1"), ("rp", rp),
          ("pdl", "application/pdf,image/urf,image/jpeg"),
          ("ty", ty), ("product", "(AdvPrint Pro)"),
          ("Note", note),
          ("usb_MFG", "Bit Dream IT"),
          ("usb_MDL", "AdvPrint Pro Hub"),
          ("UUID", _ipp_printer_uuid().replace("urn:uuid:", "")),
          ("URF", "V1.4"), ("Color", "T"), ("Duplex", "F"),
          ("Scan", "F"), ("Sort", "F")]
    out = b""
    for k, v in kv:
        item = ("%s=%s" % (k, v)).encode("utf-8")[:255]
        out += bytes([len(item)]) + item
    return out


def _mdns_services():
    """v3.0.9: every advertised service as (instance, rp, ty, note).
    Service 0 = the classic central queue (ipp/print). Then ONE service
    per LOCAL printer with rp=ipp/print/<slug>, capped at 24 printers so
    the UDP announce packet stays far below the 9000 byte mDNS cap
    (v3.3.0 BUG 3: was 12 - larger labs/shops have more printers, and
    EVERY printer that exists must be separately discoverable)."""
    out = [(_mdns_instance_name(), "ipp/print", "AdvPrint Pro",
            "AdvPrint Pro print hub")]
    try:
        for n in list_printers_cached(max_age=30.0)[:24]:
            if not n:
                continue
            out.append(("%s @ %s" % (n, _mdns_host_target().split(".")[0]),
                        "ipp/print/%s" % _ipp_queue_slug(n),
                        n[:60],
                        "AdvPrint Pro - %s" % n[:60]))
    except Exception:
        pass
    return out


def _mdns_rr(name, rtype, ttl, rdata, flush=False):
    """One resource record: NAME TYPE CLASS TTL RDLENGTH RDATA.
    cache-flush bit set for unique records (SRV/TXT/A)."""
    cls = 0x8001 if flush else 0x0001
    return (_mdns_encode_name(name) + rtype.to_bytes(2, "big") +
            cls.to_bytes(2, "big") + int(ttl).to_bytes(4, "big") +
            len(rdata).to_bytes(2, "big") + rdata)


def _mdns_rrset(ip, ttl=_MDNS_TTL, ip6=None):
    """All records that describe this hub as an IPP printer.
    v3.0.9: announces the central queue PLUS one service per local
    printer (per-printer ipp:// queues) - phones and PCs see every
    printer of the center PC by itself. One shared A record.
    v3.3.0 BUG 2: one shared AAAA record too, so IPv6-capable clients
    (modern phones, IPv6-only LANs) can reach the hub over IPv6."""
    target = _mdns_host_target()
    port = int(CFG.get("port", 9235))
    srv = ((0).to_bytes(2, "big") + (0).to_bytes(2, "big") +
           port.to_bytes(2, "big") + _mdns_encode_name(target))
    records = []
    for inst, rp, ty, note in _mdns_services():
        fq = inst + "._ipp._tcp.local"
        records.append(
            _mdns_rr("_ipp._tcp.local", _MDNS_QTYPE_PTR, ttl,
                     _mdns_encode_name(fq)))
        records.append(
            _mdns_rr("_universal._sub._ipp._tcp.local", _MDNS_QTYPE_PTR,
                     ttl, _mdns_encode_name(fq)))
        records.append(_mdns_rr(fq, _MDNS_QTYPE_SRV, ttl, srv, flush=True))
        records.append(_mdns_rr(fq, _MDNS_QTYPE_TXT, ttl,
                                _mdns_txt_records(rp=rp, ty=ty, note=note),
                                flush=True))
    records.append(_mdns_rr(target, _MDNS_QTYPE_A, ttl,
                            socket.inet_aton(ip), flush=True))
    if ip6:
        try:
            records.append(_mdns_rr(target, _MDNS_QTYPE_AAAA, ttl,
                                    socket.inet_pton(socket.AF_INET6, ip6),
                                    flush=True))
        except (OSError, socket.error):
            pass                    # AAAA is best-effort, never fatal
    return records


def _mdns_packet(answers, questions=b"", qdcount=0):
    """Build an mDNS response: ID + QR=1/AA=1 flags + counts, optional
    echoed questions. RFC 1035 §4.1.1 header layout."""
    header = ((0).to_bytes(2, "big") +                  # transaction id
              (0x8400).to_bytes(2, "big") +             # QR + AA
              qdcount.to_bytes(2, "big") +              # QDCOUNT
              len(answers).to_bytes(2, "big") +         # ANCOUNT
              (0).to_bytes(2, "big") +                  # NSCOUNT
              (0).to_bytes(2, "big"))                   # ARCOUNT
    return header + questions + b"".join(answers)


def _mdns_parse_questions(pkt):
    """Extract (qname_str, qtype, class, raw_bytes) per question."""
    out = []
    if len(pkt) < 12:
        return out
    qd = int.from_bytes(pkt[4:6], "big")
    i = 12
    for _ in range(min(qd, 8)):        # sane cap - we only match our own
        labels = []
        start = i
        try:
            while True:
                if i >= len(pkt):
                    return out
                ln = pkt[i]
                i += 1
                if ln == 0:
                    break
                if ln & 0xC0:          # compression pointer - unsupported
                    return out
                labels.append(pkt[i:i + ln].decode("utf-8", "replace"))
                i += ln
            qtype = int.from_bytes(pkt[i:i + 2], "big")
            qclass = int.from_bytes(pkt[i + 2:i + 4], "big")
            i += 4
        except (IndexError, ValueError):
            return out
        out.append((".".join(labels).lower(), qtype, qclass,
                    pkt[start:i]))
    return out


def _mdns_announce(ip, ttl=_MDNS_TTL, ip6=None):
    """Unsolicited multicast announce (RFC 6762 §8.3). v3.3.0 BUG 2:
    carries the AAAA record when the hub has a usable IPv6."""
    sock = _mdns_state["sock"]
    if sock is None:
        return
    try:
        pkt = _mdns_packet(_mdns_rrset(ip, ttl, ip6=ip6))
        sock.sendto(pkt, (_MDNS_GROUP, _MDNS_PORT))
        _mdns_state["last_announce"] = time.time()
        _mdns_state["announced"] = ttl > 0
    except OSError as e:
        if not _mdns_state["err_logged"]:
            log("[MDNS] announce failed: %s" % e)
            _mdns_state["err_logged"] = True


def _ipp_mdns_loop():
    """Responder thread: opens the socket while discovery is wanted,
    answers queries, re-announces periodically, says goodbye (TTL 0)
    when LAN sharing turns off. Any error silently downgrades to
    "no discovery" - printing itself never depends on this."""
    while True:
        try:
            want = (ipp_printer_enabled() and
                    bool(CFG.get("ipp_mdns", True)))
                    # v3.2.2: decoupled from share_lan - IPP printer mode
                    # owns discovery (lan_listen_ensure now starts the
                    # LAN listener for ipp_printer too, so advertising
                    # without a listener can no longer happen)
            ip = lan_ip() if want else None
            if ip in ("127.0.0.1", "::1", ""):
                want, ip = False, None
            # v3.3.0 BUG 2: one usable IPv6 for the AAAA record
            ip6 = (list_lan_ips6() or [None])[0] if want else None
            sock = _mdns_state["sock"]
            if want and sock is None:
                _mdns_state["announced"] = False
                _mdns_state["last_announce"] = 0.0
                try:
                    _mdns_state["sock"] = _mdns_socket_open()
                    _mdns_state["err_logged"] = False
                    log("[MDNS] AirPrint discovery UP on %s (%s) - the"
                        " hub now shows up in phone/PC printer lists"
                        % (ip, _mdns_instance_name()))
                except OSError as e:
                    if not _mdns_state["err_logged"]:
                        log("[MDNS] cannot join multicast group (%s) -"
                            " phones will need the manual IPP URL" % e)
                        _mdns_state["err_logged"] = True
                    _mdns_state["sock"] = None
            elif not want and sock is not None:
                _mdns_announce(ip or "0.0.0.0", ttl=0, ip6=ip6)   # goodbye
                try:
                    sock.close()
                except OSError:
                    pass
                _mdns_state["sock"] = None
                _mdns_state["announced"] = False
                log("[MDNS] discovery stopped")
            sock = _mdns_state["sock"]
            if sock is not None:
                if ip and (_mdns_state["ip"] != ip or
                           _mdns_state.get("ip6") != ip6):
                    _mdns_announce(ip, ttl=0, ip6=ip6)   # IP changed
                    _mdns_state["announced"] = False
                _mdns_state["ip"] = ip
                _mdns_state["ip6"] = ip6
                if ip and (not _mdns_state["announced"] or
                           time.time() - _mdns_state["last_announce"]
                           >= _MDNS_ANNOUNCE_EVERY):
                    _mdns_announce(ip, ip6=ip6)
                sock.settimeout(2.0)
                try:
                    pkt, addr = sock.recvfrom(9000)
                    _mdns_answer_query(pkt, addr, ip, ip6=ip6)
                except socket.timeout:
                    pass
                except OSError:
                    pass
        except Exception:
            pass                    # discovery must never break the hub
        time.sleep(3.0)


def ipp_mdns_ensure():
    """Health-refresher hook: start the responder thread once; the
    thread itself tracks share_lan / ipp_printer / ipp_mdns live."""
    if _mdns_state["thread"] and _mdns_state["thread"].is_alive():
        return
    t = threading.Thread(target=_ipp_mdns_loop, daemon=True,
                         name="advprint-mdns")
    _mdns_state["thread"] = t
    t.start()


def _mdns_socket_open():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    mreq = socket.inet_aton(_MDNS_GROUP) + socket.inet_aton("0.0.0.0")
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    try:
        s.bind(("", _MDNS_PORT))
    except OSError:
        s.close()
        raise
    return s


def _mdns_answer_query(pkt, addr, ip, ip6=None):
    """Answer a query with the records that match its questions.
    v3.0.9: knows every per-printer service instance, so a client
    asking for ONE printer's SRV/TXT gets exactly that queue's
    rp=ipp/print/<printer> answer. v3.3.0 BUG 2: AAAA answers too."""
    sock = _mdns_state["sock"]
    if sock is None or not ip:
        return
    qs = _mdns_parse_questions(pkt)
    if not qs:
        return
    target = _mdns_host_target()
    port = int(CFG.get("port", 9235))
    services = {
        "_ipp._tcp.local": True,
        "_universal._sub._ipp._tcp.local": True,
    }
    # instance name -> (rp, ty, note) for per-instance SRV/TXT answers
    instances = {}
    for inst, rp, ty, note in _mdns_services():
        instances[inst.lower() + "._ipp._tcp.local"] = (rp, ty, note)
    answers = []
    echoed = b""
    qdcount = 0
    full_set_sent = False
    for name, qtype, qclass, raw in qs:
        matched = False
        for svc, want in services.items():
            if name == svc or name.endswith("." + svc):
                matched = want
                break
        if not matched and name not in instances and name != target:
            continue
        qdcount += 1
        echoed += raw
        if qtype in (_MDNS_QTYPE_PTR, _MDNS_QTYPE_ANY):
            answers += [r for r in _mdns_rrset(ip, ip6=ip6) if r]
            full_set_sent = True
            break               # PTR/ANY -> full record set (all queues)
        if qtype == _MDNS_QTYPE_SRV:
            srv = ((0).to_bytes(2, "big") + (0).to_bytes(2, "big") +
                   port.to_bytes(2, "big") + _mdns_encode_name(target))
            answers.append(_mdns_rr(name, _MDNS_QTYPE_SRV, _MDNS_TTL,
                                    srv, flush=True))
        elif qtype == _MDNS_QTYPE_TXT:
            rp, ty, note = instances.get(name, ("ipp/print",
                                                "AdvPrint Pro",
                                                "AdvPrint Pro print hub"))
            answers.append(_mdns_rr(name, _MDNS_QTYPE_TXT, _MDNS_TTL,
                                    _mdns_txt_records(rp=rp, ty=ty,
                                                      note=note),
                                    flush=True))
        elif qtype == _MDNS_QTYPE_A and name == target:
            answers.append(_mdns_rr(target, _MDNS_QTYPE_A, _MDNS_TTL,
                                    socket.inet_aton(ip), flush=True))
        elif qtype == _MDNS_QTYPE_AAAA and name == target and ip6:
            try:
                answers.append(_mdns_rr(target, _MDNS_QTYPE_AAAA,
                                        _MDNS_TTL,
                                        socket.inet_pton(socket.AF_INET6,
                                                         ip6),
                                        flush=True))
            except (OSError, socket.error):
                pass
    if not answers:
        return
    reply = _mdns_packet(answers, questions=echoed, qdcount=qdcount)
    try:
        # legacy unicast clients (source port != 5353) get a unicast
        # reply; mDNS-capable clients get multicast (RFC 6762 §18)
        if addr[1] != _MDNS_PORT:
            sock.sendto(reply, addr)
        else:
            sock.sendto(reply, (_MDNS_GROUP, _MDNS_PORT))
    except OSError:
        pass


# ------------------------------------------------------------
# v2.8.2 WINDOWS FIREWALL - the OTHER classic reason "the other PC
# cannot connect even with the listener up": Windows Defender drops
# inbound TCP 9235 silently. The installer adds the rule, but a port
# change or a cleanup tool can remove it. Detect the rule (cheap,
# cached 30 s) and allow adding it back with ONE click from the
# dashboard / tray (a single UAC prompt, standard netsh rule).
# ------------------------------------------------------------
_FW_CACHE = {"t": 0.0, "ok": None}

def firewall_rule_ok():
    """True/False = inbound rule present/absent (Windows); None =
    non-Windows or the netsh query failed. Cached for 30 s."""
    if not IS_WIN:
        return None
    now = time.time()
    if now - _FW_CACHE["t"] < 30:
        return _FW_CACHE["ok"]
    ok = None
    try:
        p = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             "name=" + FIREWALL_RULE_NAME],
            capture_output=True, timeout=8, creationflags=HIDE)
        ok = (p.returncode == 0)
    except Exception:
        ok = None
    _FW_CACHE["t"] = now
    _FW_CACHE["ok"] = ok
    return ok

def firewall_allow():
    """Add the inbound allow rules via ONE UAC prompt: the hub HTTP
    port (dashboard / extension / Send portal / IPP printer) and the
    RAW JetDirect port (Standard TCP/IP port printers). Returns
    (ok, error_string). Safe to call from any thread."""
    if not IS_WIN:
        return True, None                      # nothing to do off Windows
    port = int(CFG.get("port", 9235))
    raw = int(CFG.get("raw_printer_port") or 0)
    adds = ["advfirewall firewall add rule name=\"%s\" dir=in action=allow "
            "protocol=TCP localport=%d" % (FIREWALL_RULE_NAME, port)]
    if raw > 0:
        adds.append("advfirewall firewall add rule name=\"%s RAW %d\" "
                    "dir=in action=allow protocol=TCP localport=%d"
                    % (FIREWALL_RULE_NAME, raw, raw))
    ps = ("Start-Process netsh -Verb RunAs -Wait -ArgumentList '%s'"
          % "; ".join(adds))
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", ps],
            capture_output=True, timeout=120, creationflags=HIDE)
    except Exception as e:
        return False, "firewall command failed: %s" % e
    _FW_CACHE["t"] = 0.0
    if firewall_rule_ok():
        ports = str(port) if raw <= 0 else "%d + RAW %d" % (port, raw)
        db_audit("firewall.allowed", actor="ui",
                 details="inbound TCP %s allowed (rule '%s')"
                         % (ports, FIREWALL_RULE_NAME))
        log("[FIREWALL] inbound TCP %s allowed - LAN PCs and phones can "
            "reach the hub (rule '%s')" % (ports, FIREWALL_RULE_NAME))
        return True, None
    return False, ("the rule is still missing - the Windows UAC prompt "
                   "was probably canceled. Start the hub once as admin, "
                   "or add the rule manually with netsh.")

# ------------------------------------------------------------
# v2.8 - DROP ZONE: print from ANY PC/app without the extension.
# Watch a folder; every PDF that lands in it is printed and moved
# into done/. This is the "MS Word print share" feature: in Word /
# Excel / any Windows app choose the printer "Microsoft Print to
# PDF", save into the DropZone - the page comes out of the real
# printer seconds later. No extension, no driver, no cloud.
# ------------------------------------------------------------
_DROP_SEEN = {}                    # path -> size seen on the previous poll
DROP_POLL_SECONDS = 2.5

def drop_dir():
    """Active DropZone folder (config drop_dir or <data>/DropZone)."""
    d = (CFG.get("drop_dir") or "").strip()
    if not d:
        d = os.path.join(CFG["data_dir"], "DropZone")
    return d

def drop_stats():
    """Cheap status for GET /dropzone + the dashboard card."""
    d = drop_dir()
    out = {"ok": True, "enabled": bool(CFG.get("drop_enabled")),
           "dir": d, "waiting": 0, "done": 0}
    try:
        out["waiting"] = len([n for n in os.listdir(d)
                              if n.lower().endswith(".pdf")])
    except OSError:
        pass
    try:
        out["done"] = len([n for n in os.listdir(os.path.join(d, "done"))
                           if n.lower().endswith(".pdf")])
    except OSError:
        pass
    return out

def _drop_move(path, sub):
    """Move a picked-up PDF into DropZone/<sub> (done)."""
    if CFG.get("drop_delete"):
        try:
            os.unlink(path)
        except OSError:
            pass
        return
    dst_dir = os.path.join(drop_dir(), sub)
    try:
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, os.path.basename(path))
        try:
            os.replace(path, dst)
        except OSError:
            root, ext = os.path.splitext(os.path.basename(path))
            dst = os.path.join(dst_dir, "%s-%d%s" % (root, os.getpid(), ext))
            os.replace(path, dst)
    except OSError as e:
        log("[DROP] cannot move %s into %s/ (%s)"
            % (os.path.basename(path), sub, e))

def _drop_process(path):
    """Enqueue one PDF found in the DropZone, then move it away."""
    name = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        log("[DROP] cannot read %s (%s)" % (name, e))
        return
    if not data.startswith(b"%PDF"):
        log("[DROP] %s is not a PDF - only PDF files are printed; "
            "moved to done/ untouched" % name)
        _drop_move(path, "done")
        return
    try:
        job, dup = enqueue_print("a4", "DropZone: " + name[:-4], data,
                                 source="dropzone", dedupe=False,
                                 origin_ip="dropzone")
    except Exception as e:
        log("[DROP] enqueue failed for %s: %s" % (name, e))
        return
    _drop_move(path, "done")
    log("[DROP] '%s' picked up -> job #%d%s"
        % (name, job, " (already printed before)" if dup else ""))

def _drop_scan():
    """One poll over the DropZone. A file is only taken when it is a
    stable, complete PDF (size seen twice + %PDF magic)."""
    d = drop_dir()
    try:
        entries = [n for n in os.listdir(d)
                   if n.lower().endswith(".pdf")]
    except OSError:
        return
    for name in entries:
        p = os.path.join(d, name)
        try:
            if not os.path.isfile(p):
                continue
            sz = os.path.getsize(p)
        except OSError:
            continue
        if sz <= 0:
            continue
        if _DROP_SEEN.get(p) != sz:
            _DROP_SEEN[p] = sz      # wait one more poll - writer may be done
            continue
        if sz < 200:
            continue
        try:
            with open(p, "rb") as f:
                head = f.read(5)
        except OSError:
            continue
        if head != b"%PDF-":
            continue
        _drop_process(p)
        _DROP_SEEN.pop(p, None)

def drop_watcher():
    """Background loop - prints every PDF that lands in the DropZone.
    v2.8.1: the loop ALWAYS runs and re-reads the config every poll, so
    the DropZone can be switched on/off live from the dashboard without
    restarting the hub."""
    logged = False
    while True:
        try:
            if CFG.get("drop_enabled"):
                d = drop_dir()
                try:
                    os.makedirs(os.path.join(d, "done"), exist_ok=True)
                except OSError as e:
                    log("[DROP] cannot create the DropZone %s (%s)"
                        % (d, e))
                if not logged:
                    log("[DROP] DropZone active: %s" % d)
                    log("[DROP] print from ANY app: Print -> 'Microsoft "
                        "Print to PDF' -> save into this folder - it "
                        "prints automatically")
                    logged = True
                _drop_scan()
            else:
                _DROP_SEEN.clear()
                logged = False
        except Exception as e:
            log("[DROP] scan error: %s" % e)
        time.sleep(DROP_POLL_SECONDS)

def start_drop_watcher():
    threading.Thread(target=drop_watcher, daemon=True,
                     name="advprint-dropzone").start()

# ------------------------------------------------------------
# v2.8.1 - QR CODE ENCODER (pure stdlib, no third-party deps).
# Byte-mode QR, ECC level M, versions 1-40, auto mask selection.
# Ported from the MIT-licensed "QR Code generator" reference design
# (Project Nayuki) and verified BIT-EXACT against an independent
# implementation for every mask 0-7 and every version the hub can
# emit (the hub only ever encodes its own small send/invite URLs).
# Rendered as inline SVG so any phone camera can scan it off the
# dashboard - no internet, no CDN, no tracking.
# ------------------------------------------------------------
_QR_ECC_CW_PER_BLOCK = (
    (7, 10, 15, 20, 26, 18, 20, 24, 30, 18,
     20, 24, 26, 30, 22, 24, 28, 30, 28, 28,
     28, 28, 30, 30, 26, 28, 30, 30, 30, 30,
     30, 30, 30, 30, 30, 30, 30, 30, 30, 30),   # L
    (10, 16, 26, 18, 24, 16, 18, 22, 22, 26,
     30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
     26, 28, 28, 28, 28, 28, 28, 28, 28, 28,
     28, 28, 28, 28, 28, 28, 28, 28, 28, 28),   # M
    (13, 22, 18, 26, 18, 24, 18, 22, 20, 24,
     28, 26, 24, 20, 30, 24, 28, 28, 26, 30,
     28, 30, 30, 30, 30, 28, 30, 30, 30, 30,
     30, 30, 30, 30, 30, 30, 30, 30, 30, 30),   # Q
    (17, 28, 22, 16, 22, 28, 26, 26, 24, 28,
     24, 28, 22, 24, 24, 30, 28, 28, 26, 28,
     30, 24, 30, 30, 30, 30, 30, 30, 30, 30,
     30, 30, 30, 30, 30, 30, 30, 30, 30, 30),   # H
)
_QR_NUM_ECC_BLOCKS = (
    (1, 1, 1, 1, 1, 2, 2, 2, 2, 4,
     4, 4, 4, 4, 6, 6, 6, 6, 7, 8,
     8, 9, 9, 10, 12, 12, 12, 13, 14, 15,
     16, 17, 18, 19, 19, 20, 21, 22, 24, 25),   # L
    (1, 1, 1, 2, 2, 4, 4, 4, 5, 5,
     5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
     17, 17, 18, 20, 21, 23, 25, 26, 28, 29,
     31, 33, 35, 37, 38, 40, 43, 45, 47, 49),   # M
    (1, 1, 2, 2, 4, 4, 6, 6, 8, 8,
     8, 10, 12, 16, 12, 17, 16, 18, 21, 20,
     23, 23, 25, 27, 29, 34, 34, 35, 38, 40,
     43, 45, 48, 51, 53, 56, 59, 62, 65, 68),   # Q
    (1, 1, 2, 4, 4, 4, 5, 6, 8, 8,
     11, 11, 16, 16, 18, 16, 19, 21, 25, 25,
     25, 34, 30, 32, 35, 37, 40, 42, 45, 48,
     51, 54, 57, 60, 63, 66, 70, 74, 77, 81),   # H
)
_QR_ECL_FORMAT_BITS = (1, 0, 3, 2)          # L, M, Q, H
_QR_ECL_M = 1                               # the hub always uses level M


def _qr_raw_modules(ver):
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        num_align = ver // 7 + 2
        result -= (25 * num_align - 10) * num_align - 55
        if ver >= 7:
            result -= 36
    return result


def _qr_data_cw(ver, ecl):
    return (_qr_raw_modules(ver) // 8
            - _QR_ECC_CW_PER_BLOCK[ecl][ver - 1]
            * _QR_NUM_ECC_BLOCKS[ecl][ver - 1])


def _qr_align_pos(ver):
    if ver == 1:
        return []
    num_align = ver // 7 + 2
    step = 26 if ver == 32 else \
        (ver * 4 + num_align * 2 + 1) // (num_align * 2 - 2) * 2
    result = [6]
    pos = ver * 4 + 10
    for _ in range(num_align - 1):
        result.append(pos)
        pos -= step
    return sorted(set(result))


def _qr_gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _qr_gf_pow(base, e):
    r = 1
    for _ in range(e):
        r = _qr_gf_mul(r, base)
    return r


def _qr_rs_divisor(degree):
    """g(x) = prod (x - alpha^i), highest-first, monic."""
    result = [1]
    for i in range(degree):
        a = _qr_gf_pow(0x02, i)
        new = [0] * (len(result) + 1)
        for j, c in enumerate(result):
            new[j] ^= c
            new[j + 1] ^= _qr_gf_mul(c, a)
        result = new
    return result


def _qr_rs_remainder(data, divisor):
    result = [0] * (len(divisor) - 1)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i in range(len(divisor) - 1):
            result[i] ^= _qr_gf_mul(divisor[i + 1], factor)
    return result


def _qr_codewords(data, ecl, max_ver=40):
    for ver in range(1, max_ver + 1):
        cap = _qr_data_cw(ver, ecl)
        cc_bits = 8 if ver < 10 else 16
        if 4 + cc_bits + 8 * len(data) > cap * 8:
            continue
        bits = [0, 1, 0, 0]                       # byte mode 0b0100
        for i in range(cc_bits - 1, -1, -1):
            bits.append((len(data) >> i) & 1)
        for byte in data:
            for i in range(7, -1, -1):
                bits.append((byte >> i) & 1)
        bits += [0] * min(4, cap * 8 - len(bits))   # terminator
        bits += [0] * (-len(bits) % 8)              # byte align
        pad = (0xEC, 0x11)
        i = 0
        while len(bits) < cap * 8:
            bits += [(pad[i % 2] >> j) & 1 for j in range(7, -1, -1)]
            i += 1
        cw = []
        for k in range(0, cap * 8, 8):
            v = 0
            for bit in bits[k:k + 8]:
                v = (v << 1) | bit
            cw.append(v)
        return ver, cw
    raise ValueError("data too long for a QR code (max version 40)")


def _qr_interleave(ver, ecl, datacw):
    blocks = _QR_NUM_ECC_BLOCKS[ecl][ver - 1]
    ecc_len = _QR_ECC_CW_PER_BLOCK[ecl][ver - 1]
    short = len(datacw) // blocks
    num_short = blocks - len(datacw) % blocks
    divisor = _qr_rs_divisor(ecc_len)
    dat_blocks, ecc_blocks = [], []
    idx = 0
    for b in range(blocks):
        d = short + (1 if b >= num_short else 0)
        blk = datacw[idx:idx + d]
        idx += d
        dat_blocks.append(blk)
        ecc_blocks.append(_qr_rs_remainder(blk, divisor))
    out = []
    for i in range(short):
        for blk in dat_blocks:
            out.append(blk[i])
    for b in range(num_short, blocks):
        out.append(dat_blocks[b][short])
    for i in range(ecc_len):
        for blk in ecc_blocks:
            out.append(blk[i])
    return out


def _qr_mask_bit(mask, x, y):
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (x // 3 + y // 2) % 2 == 0
    if mask == 5:
        return (x * y) % 2 + (x * y) % 3 == 0
    if mask == 6:
        return ((x * y) % 2 + (x * y) % 3) % 2 == 0
    return ((x + y) % 2 + (x * y) % 3) % 2 == 0


def _qr_fmt_bits(ecl, mask):
    data = _QR_ECL_FORMAT_BITS[ecl] << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    bits = (data << 10 | rem) ^ 0x5412
    return [(bits >> i) & 1 for i in range(15)]     # LSB-first


def _qr_ver_bits(ver):
    rem = ver
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    bits = ver << 12 | rem
    return [(bits >> i) & 1 for i in range(18)]     # LSB-first


class _QrGrid:
    def __init__(self, ver):
        self.ver = ver
        self.size = ver * 4 + 17
        self.mods = [[False] * self.size for _ in range(self.size)]
        self.func = [[False] * self.size for _ in range(self.size)]

    def set(self, x, y, dark):
        self.mods[y][x] = dark
        self.func[y][x] = True


def _qr_draw_patterns(g):
    size = g.size
    for i in range(size):
        g.set(6, i, i % 2 == 0)
        g.set(i, 6, i % 2 == 0)

    def finder(cx, cy):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    dist = max(abs(dx), abs(dy))
                    g.set(x, y, dist != 2 and dist != 4)
    finder(3, 3)
    finder(size - 4, 3)
    finder(3, size - 4)
    apos = _qr_align_pos(g.ver)
    n = len(apos)
    for i in range(n):
        for j in range(n):
            if ((i == 0 and j == 0) or (i == 0 and j == n - 1)
                    or (i == n - 1 and j == 0)):
                continue                     # the three finder corners
            cy, cx = apos[i], apos[j]
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    g.set(cx + dx, cy + dy,
                          max(abs(dx), abs(dy)) != 1)
    g.set(8, size - 8, True)                 # dark module


def _qr_draw_format(g, ecl, mask):
    size = g.size
    bits = _qr_fmt_bits(ecl, mask)
    for i in range(6):
        g.set(8, i, bits[i])
    g.set(8, 7, bits[6])
    g.set(8, 8, bits[7])
    g.set(7, 8, bits[8])
    for i in range(9, 15):
        g.set(14 - i, 8, bits[i])
    for i in range(8):
        g.set(size - 1 - i, 8, bits[i])
    for i in range(8, 15):
        g.set(8, size - 15 + i, bits[i])
    g.set(8, size - 8, True)


def _qr_draw_version(g):
    if g.ver < 7:
        return
    size = g.size
    bits = _qr_ver_bits(g.ver)
    for i in range(18):
        a, b = i // 3, i % 3
        g.set(b + size - 11, a, bits[i])
        g.set(a, b + size - 11, bits[i])


def _qr_place_data(g, codewords, mask):
    size = g.size
    i = 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5                        # skip the timing column
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = (size - 1 - vert) if upward else vert
                if not g.func[y][x] and i < len(codewords) * 8:
                    bit = (codewords[i >> 3] >> (7 - (i & 7))) & 1
                    g.mods[y][x] = bool(bit) ^ _qr_mask_bit(mask, x, y)
                    i += 1
        right -= 2


def _qr_penalty(g):
    size = g.size
    res = 0
    for row in g.mods:                       # rule 1 - rows
        run = 1
        for x in range(1, size):
            if row[x] == row[x - 1]:
                run += 1
                if run == 6:
                    res += 3
                elif run > 6:
                    res += 1
            else:
                run = 1
    for x in range(size):                    # rule 1 - columns
        run = 1
        for y in range(1, size):
            if g.mods[y][x] == g.mods[y - 1][x]:
                run += 1
                if run == 6:
                    res += 3
                elif run > 6:
                    res += 1
            else:
                run = 1
    for y in range(size - 1):                # rule 2 - 2x2 blocks
        row, nxt = g.mods[y], g.mods[y + 1]
        for x in range(size - 1):
            if row[x] == row[x + 1] == nxt[x] == nxt[x + 1]:
                res += 3
    res_holder = [res]                       # rule 3 - finder-like patterns
    pat1 = (True, False, True, True, True, False, True,
            False, False, False, False)
    pat2 = tuple(not b for b in pat1)

    def scan(get, n):
        for i in range(n - 10):
            for pat in (pat1, pat2):
                if all(get(i + j) == pat[j] for j in range(11)):
                    res_holder[0] += 40
    for y in range(size):
        scan(lambda i, y=y: g.mods[y][i], size)
    for x in range(size):
        scan(lambda i, x=x: g.mods[i][x], size)
    res = res_holder[0]
    dark = sum(r.count(True) for r in g.mods)   # rule 4 - balance
    total = size * size
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    return res + k * 10


def qr_matrix(data, ecl=_QR_ECL_M):
    """bytes -> module matrix (list of bool rows), auto mask."""
    ver, datacw = _qr_codewords(bytes(data), ecl)
    allcw = _qr_interleave(ver, ecl, datacw)
    base = _QrGrid(ver)
    _qr_draw_patterns(base)
    best, best_pen = None, None
    for m in range(8):
        g2 = _QrGrid(ver)
        g2.mods = [row[:] for row in base.mods]
        g2.func = base.func
        _qr_draw_format(g2, ecl, m)
        _qr_draw_version(g2)
        _qr_place_data(g2, allcw, m)
        pen = _qr_penalty(g2)
        if best_pen is None or pen < best_pen:
            best, best_pen = g2, pen
    return best.mods


def qr_svg(data, dark="#0f172a", light="#ffffff", border=4, px=6):
    """bytes -> standalone SVG string (phone-scannable, prints crisply)."""
    m = qr_matrix(data)
    n = len(m) + 2 * border
    w = n * px
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" shape-rendering='
             '"crispEdges" viewBox="0 0 %d %d" width="%d" height="%d">'
             % (w, w, w, w),
             '<rect width="%d" height="%d" fill="%s"/>' % (w, w, light)]
    path = []
    for y, row in enumerate(m):
        for x, on in enumerate(row):
            if on:
                path.append("M%d %dh%dv%dh-%dz"
                            % ((x + border) * px, (y + border) * px,
                               px, px, px))
    parts.append('<path d="%s" fill="%s"/>' % ("".join(path), dark))
    parts.append('</svg>')
    return "".join(parts)


# ------------------------------------------------------------
# v2.8 - SEND PORTAL (/send): a tiny upload page served by the hub,
# so ANY device on the LAN (phone, tablet, a PC without the
# extension) can print a PDF through this PC's printers.
# Token required - same as every other endpoint.
# ------------------------------------------------------------
def send_portal_html(token):
    q = "?token=" + quote(token or "")
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AdvPrint Pro - Send a PDF to print</title><style>
 body{font:15px/1.55 "Segoe UI",system-ui,sans-serif;background:#f5f8fc;
      color:#0f172a;margin:0;padding:24px}
 .box{max-width:520px;margin:4vh auto;background:#fff;border:1px solid #e2e8f0;
      border-radius:14px;padding:22px;box-shadow:0 8px 30px #0f172a14}
 h1{font-size:19px;margin:0 0 4px} p{color:#475569;margin:6px 0 14px}
 input[type=file]{width:100%;border:1px dashed #94a3b8;border-radius:10px;
      padding:14px;background:#f8fafc}
 button{width:100%;margin-top:14px;border:none;border-radius:10px;
      background:#1d4ed8;color:#fff;font:700 15px "Segoe UI",system-ui;
      padding:12px;cursor:pointer}
 button:disabled{background:#94a3b8}
 #out{margin-top:12px;font-size:14px;display:none;border-radius:9px;
      padding:10px 12px}
 #out.ok{display:block;background:#dcfce7;color:#166534}
 #out.bad{display:block;background:#fee2e2;color:#991b1b}
 .brand{font-size:11px;color:#94a3b8;text-align:center;margin-top:14px}
</style></head><body><div class="box">
 <h1>Send a PDF to print</h1>
 <p>This uploads the file to the AdvPrint Pro hub on this network and
    prints it immediately on the default printer. 100% local.</p>
 <input type="file" id="f" accept="application/pdf,.pdf">
 <button id="go" onclick="up()">Print it</button>
 <div id="out"></div>
 <div class="brand">AdvPrint Pro v@@VERSION@@ - by Bit Dream IT -
   100% local - no cloud, no tracking</div>
</div>
<script>
const TOK = new URLSearchParams(location.search).get("token") || "";
async function up(){
  const fi = document.getElementById("f");
  const out = document.getElementById("out");
  const b = document.getElementById("go");
  out.className = ""; out.style.display = "none";
  if (!fi.files.length) { out.textContent = "Choose a PDF first.";
    out.className = "bad"; return; }
  const file = fi.files[0];
  if (!/\\.pdf$/i.test(file.name)) { out.textContent =
    "Only PDF files can be printed here."; out.className = "bad"; return; }
  b.disabled = true; b.textContent = "Uploading...";
  try {
    const fd = new FormData();
    fd.append("file", file, file.name);
    /* v2.9.0: token ALSO as a form field - survives QR apps and phone
       browsers that mangle the query string. The query token above
       stays as the primary transport. */
    if (TOK) fd.append("token", TOK);
    const r = await fetch("/send@@Q@@", { method: "POST", body: fd });
    const d = await r.json();
    if (d.ok) { out.textContent = "Sent! Printing as job #" + d.job_id +
      " - watch the printer."; out.className = "ok"; }
    else { out.textContent = "Failed: " + (d.error || ("HTTP " + r.status));
      out.className = "bad"; }
  } catch (e) { out.textContent = "Upload failed: " + e;
    out.className = "bad"; }
  b.disabled = false; b.textContent = "Print it";
}
</script></body></html>""".replace("@@VERSION@@", VERSION).replace("@@Q@@", q)

# ------------------------------------------------------------
# v2.8.1 - ONE-CLICK LAN INVITE. The hub PC shows a "Copy invite
# link" button on the dashboard LAN card; the link looks like
#   http://192.168.1.100:9235/connect?t=<hub-token>&n=<hostname>
# When the OTHER PC's user opens that link in a browser, this hub
# serves a small confirmation page. Its form POSTs to the OTHER
# PC's OWN hub at http://127.0.0.1:9235/peer-connect, which saves
# this PC into that config's peer_hubs - no retyping IPs, no
# config.json editing.
#
# SECURITY MODEL of POST /peer-connect (it must work WITHOUT the
# peer's own token, because the inviting hub cannot know it):
#   1. loopback only - the request must come from the peer PC itself;
#   2. CSRF guard - if the request carries a browser Origin header,
#      its scheme+host+port MUST equal the peer URL being added
#      (the confirmation page is served by exactly that hub). A
#      random website cannot forge this Origin, so drive-by CSRF
#      cannot inject a peer;
#   3. the peer URL must be a private-LAN http(s) address
#      (localhost / 10.x / 172.16-31.x / 192.168.x / 169.254.x);
#   4. nothing happens on GET - the user must click the button on
#      the confirmation page (form POST with confirm=1);
#   5. every accept is audited (event "peer.connected") and visible
#      in the dashboard LAN card where it can be removed again.
# ------------------------------------------------------------
def esc_html(s):
    return html.escape(str(s == None and "" or s), quote=True)  # noqa: E711


DEFAULT_PEER_PORT = 9235   # the peer PC's own hub port (default install)


def connect_page_html(token, name, req_host="", req_port=None,
                      visitor_is_hub=False):
    """v2.8.1 ONE-CLICK LAN INVITE page.
    v3.3.0 BUG 1: the hub URL shown on the page (and saved into the
    visiting PC's peer_hubs) is built from the address the VISITOR
    actually used - the request's Host header - never from the serving
    hub's own lan_ip() guess, which could be an adapter the visitor
    cannot reach or simply the wrong identity when two labs share one
    token. A visitor who opened the invite ON the hub PC itself gets
    connect_self_html() instead of a form that would add the hub to
    itself; the page also probes the VISITING PC's own hub (127.0.0.1)
    so "click Connect" can never die with a raw browser error when the
    other PC has no hub running yet."""
    host = socket.gethostname()
    who = str(name or host)[:60]
    rh = str(req_host or "").strip().lower()
    if rh in ("localhost", "::1") or rh.startswith("127."):
        rh = ""
    peer_host = rh or (lan_ip() if CFG.get("share_lan") else "127.0.0.1")
    peer_port = int(req_port) if req_port else int(CFG.get("port", 9235))
    peer_url = "http://%s:%d" % (peer_host, peer_port)
    if visitor_is_hub:
        return connect_self_html(peer_url, who, token)
    # v3.3.0 BUG 2: offer EVERY address of this hub (IPv4 + IPv6) so the
    # visitor can swap the ip:port if the one they typed is not the best
    # route to this PC on their segment.
    alt4 = []
    try:
        alt4 = [i for i in list_lan_ips() if i and not i.startswith("127.")]
    except Exception:
        alt4 = []
    alt6 = []
    try:
        alt6 = list_lan_ips6()
    except Exception:
        alt6 = []
    alt_rows = ""
    for a in alt4:
        alt_rows += ("<div class='alt'><span class='mono'>http://%s:%d"
                     "</span><button class='btn gray' data-alt=\"http://%s:%d\">"
                     "use this</button></div>"
                     % (esc_html(a), peer_port, esc_html(a), peer_port))
    for a in alt6:
        alt_rows += ("<div class='alt'><span class='mono'>http://[%s]:%d"
                     "</span><button class='btn gray' data-alt=\"http://[%s]:%d\">"
                     "use this</button></div>"
                     % (esc_html(a), peer_port, esc_html(a), peer_port))
    if alt_rows:
        alt_rows = ("<details><summary>Other addresses of this hub"
                    " (pick one YOUR PC reaches)</summary>" + alt_rows +
                    "</details>")
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AdvPrint Pro - connect to this printer hub</title><style>
 body{font:15px/1.55 "Segoe UI",system-ui,sans-serif;background:#f5f8fc;
      color:#0f172a;margin:0;padding:24px}
 .box{max-width:560px;margin:6vh auto;background:#fff;border:1px solid #e2e8f0;
      border-radius:14px;padding:24px;box-shadow:0 8px 30px #0f172a14}
 h1{font-size:19px;margin:0 0 6px} p{color:#475569;margin:8px 0}
 .kv{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
     padding:10px 14px;margin:10px 0;font-size:14px}
 .mono{font-family:Consolas,monospace;font-size:13px;word-break:break-all}
 button{border:none;border-radius:10px;background:#1d4ed8;color:#fff;
        font:700 15px "Segoe UI",system-ui;padding:12px 18px;cursor:pointer}
 button.gray{background:#64748b}
 details{margin-top:14px} summary{cursor:pointer;color:#1d4ed8}
 pre{background:#0f172a;color:#e2e8f0;border-radius:8px;padding:10px;
     font-size:12px;overflow-x:auto}
 .brand{font-size:11px;color:#94a3b8;text-align:center;margin-top:14px}
 .warn{background:#fef9c3;border:1px solid #fde047;color:#854d0e;
       border-radius:10px;padding:10px 14px;font-size:14px}
 #localHubState{border-radius:10px;padding:10px 14px;font-size:13.5px;
       margin:10px 0;background:#f8fafc;border:1px solid #e2e8f0}
 #localHubState.ok{background:#ecfdf5;border-color:#a7f3d0;color:#065f46}
 #localHubState.warn{background:#fef9c3;border-color:#fde047;color:#854d0e}
 .alt{display:flex;gap:8px;align-items:center;margin:6px 0}
 .alt .mono{flex:1}
 .alt button{padding:6px 10px;font-size:12px}
</style></head><body><div class="box">
 <h1>Connect to &#8220;@@WHO@@&#8221;'s printer hub?</h1>
 <p>The PC that showed you this link shares its printers over the
    local network with <b>AdvPrint Pro</b>. Clicking the button below
    adds it to YOUR PC's printer-hub list (peer_hubs) - afterwards you
    can send print jobs to its printers from your own dashboard.</p>
 <div class="kv">Peer PC: <b>@@WHO@@</b><br>
  Hub URL: <span class="mono" id="peerUrl">@@URL@@</span></div>
 <div id="localHubState">Checking your PC's own AdvPrint hub
   (127.0.0.1:@@DPORT@@) ...</div>
 <form method="post" id="peerForm"
       action="http://127.0.0.1:@@DPORT@@/peer-connect">
  <input type="hidden" name="url" id="fUrl" value="@@URL@@">
  <input type="hidden" name="token" value="@@TOK@@">
  <input type="hidden" name="name" value="@@WHO@@">
  <input type="hidden" name="confirm" value="1">
  <button type="submit" id="peerBtn">Add &#8220;@@WHO@@&#8221; as a LAN print peer</button>
 </form>
 <p class="warn">Nothing is sent to the internet - this only writes the
    peer entry into your local AdvPrint Pro config. You can remove it
    any time from your dashboard's LAN card (or config.json).</p>
 @@ALTS@@
 <details><summary>Manual alternative (if your hub runs on another port)</summary>
  <p>Paste this into <span class="mono">peer_hubs</span> in your
     <span class="mono">config.json</span> and restart the hub:</p>
  <pre>[{"url": "@@URL@@",
 "token": "@@TOK@@",
 "name": "@@WHO@"}]</pre>
 </details>
 <div class="brand">AdvPrint Pro v@@VERSION@@ - by Bit Dream IT -
   100% local - no cloud, no tracking</div>
</div>
<script>
(function(){
  var DPORT = @@DPORT@@;
  var st = document.getElementById("localHubState");
  var form = document.getElementById("peerForm");
  var btn = document.getElementById("peerBtn");
  var fUrl = document.getElementById("fUrl");
  var up = null;
  function set(t, cls){ st.textContent = t;
    st.className = cls ? cls : ""; }
  /* v3.3.0 BUG 1: probe the VISITING PC's own hub first - the old page
     just POSTed into the void and the browser answered with a raw
     "127.0.0.1 refused to connect" error page. */
  fetch("http://127.0.0.1:" + DPORT + "/health", { mode: "cors" })
    .then(function(r){ return r.ok ? r.json() : null; })
    .then(function(j){
      if (j && j.ok) {
        up = true;
        set("Your PC's hub is running (AdvPrint Pro v" + (j.version || "?") +
            ") - the button below connects THIS PC to it.", "ok");
      } else { probeFail(); }
    })
    .catch(function(){ probeFail(); });
  function probeFail(){
    up = false;
    set("No AdvPrint hub answered on THIS PC (127.0.0.1:" + DPORT + ")." +
        " Install / start AdvPrint Pro here first, then click the" +
        " button - or add the peer manually (config.json, see below).",
        "warn");
  }
  /* "use this" chips: swap the peer URL the form will save */
  var altBtns = document.querySelectorAll("button[data-alt]");
  for (var i = 0; i < altBtns.length; i++) {
    altBtns[i].addEventListener("click", function(ev){
      ev.preventDefault();
      fUrl.value = this.getAttribute("data-alt");
      document.getElementById("peerUrl").textContent = fUrl.value;
      set("Peer URL set to " + fUrl.value +
          " - click the connect button to save it.", "");
    });
  }
  form.addEventListener("submit", function(ev){
    if (up === true) return;            /* hub up: normal form POST */
    ev.preventDefault();
    set("Connecting ...", "");
    btn.disabled = true;
    var fd = new URLSearchParams();
    fd.append("url", fUrl.value);
    fd.append("token", "@@TOK@@");
    fd.append("name", "@@WHO@@");
    fd.append("confirm", "1");
    /* last-chance live POST: the GET probe can be blocked by the
       browser's private-network rules even when the hub IS up. */
    fetch("http://127.0.0.1:" + DPORT + "/peer-connect",
          { method: "POST", mode: "cors", body: fd })
      .then(function(r){ return r.text().then(function(t){
        return { ok: r.ok, text: t }; }); })
      .then(function(res){
        if (res.ok && res.text) {
          document.open(); document.write(res.text); document.close();
          return;
        }
        fail(); })
      .catch(function(){ fail(); });
    function fail(){
      btn.disabled = false;
      set("Could not reach YOUR PC's hub on 127.0.0.1:" + DPORT +
          " - nothing was saved. Install / start AdvPrint Pro on this" +
          " PC, then open this invite again (or use the config.json" +
          " snippet below).", "warn");
    }
  });
})();
</script></body></html>""" \
        .replace("@@WHO@@", esc_html(who)) \
        .replace("@@URL@@", esc_html(peer_url)) \
        .replace("@@TOK@@", quote(token or "")) \
        .replace("@@DPORT@@", str(DEFAULT_PEER_PORT)) \
        .replace("@@ALTS@@", alt_rows) \
        .replace("@@VERSION@@", VERSION)


def connect_self_html(peer_url, who, token=""):
    """v3.3.0 BUG 1: what a visitor sees when the invite link is opened
    ON the hub PC itself (loopback). The old page happily offered the
    "Add ... as a LAN print peer" button - clicking it wrote the hub
    into its OWN peer_hubs (the 'it redirect own pc' bug report). This
    page explains the one correct move instead: carry the link to the
    OTHER PC."""
    invite = peer_url + "/connect?t=" + quote(token or "") + \
        "&n=" + quote(socket.gethostname() or "")
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AdvPrint Pro - this invite is for the OTHER PC</title><style>
 body{font:15px/1.55 "Segoe UI",system-ui,sans-serif;background:#f5f8fc;
      color:#0f172a;margin:0;padding:24px}
 .box{max-width:560px;margin:6vh auto;background:#fff;border:1px solid #e2e8f0;
      border-radius:14px;padding:24px;box-shadow:0 8px 30px #0f172a14}
 h1{font-size:19px;margin:0 0 6px} p{color:#475569;margin:8px 0}
 .kv{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
     padding:10px 14px;margin:10px 0;font-size:14px}
 .mono{font-family:Consolas,monospace;font-size:13px;word-break:break-all}
 ol{color:#475569;line-height:1.7} code{background:#f1f5f9;border:1px solid
     #e2e8f0;border-radius:4px;padding:1px 6px;font-size:12.5px}
 button{border:none;border-radius:10px;background:#1d4ed8;color:#fff;
        font:700 15px "Segoe UI",system-ui;padding:12px 18px;cursor:pointer}
 .brand{font-size:11px;color:#94a3b8;text-align:center;margin-top:14px}
 .ok{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;
     padding:10px 14px;font-size:13.5px;color:#065f46}
</style></head><body><div class="box">
 <h1>You opened this invite ON the hub PC &#8220;@@WHO@@&#8221;</h1>
 <p>This link is meant for a <b>DIFFERENT PC</b>: opening it there and
    clicking its button adds <b>this hub</b> to that PC's peer list.
    Opening it here would connect this PC to itself - so nothing was
    done.</p>
 <div class="kv">This hub: <span class="mono">@@URL@@</span></div>
 <ol><li>Copy the invite link below.</li>
     <li>Open it in any browser on the <b>other PC</b> (the one that
         should print THROUGH this hub).</li>
     <li>Click &#8220;Add ... as a LAN print peer&#8221; on THAT PC -
         it configures itself.</li></ol>
 <div class="kv"><span class="mono" id="inv">@@INVITE@@</span><br>
  <button id="cp">Copy invite link</button></div>
 <p class="ok">Tip: the same link is always on this PC's console -
    LAN Sharing &gt; Connect another PC &gt; <b>Copy invite link</b>
    (and a QR code next to it for phones).</p>
 <div class="brand">AdvPrint Pro v@@VERSION@@ - by Bit Dream IT -
   100% local - no cloud, no tracking</div>
</div>
<script>
(function(){
  var b = document.getElementById("cp");
  b.addEventListener("click", function(){
    var t = document.getElementById("inv").textContent;
    function fb(){ var ta = document.createElement("textarea");
      ta.value = t; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch (e) {}
      document.body.removeChild(ta); b.textContent = "Copied"; }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).then(function(){
        b.textContent = "Copied"; }, fb);
    } else { fb(); }
  });
})();
</script></body></html>""" \
        .replace("@@WHO@@", esc_html(who)) \
        .replace("@@URL@@", esc_html(peer_url)) \
        .replace("@@INVITE@@", esc_html(invite)) \
        .replace("@@VERSION@@", VERSION)


def connect_error_html(message):
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AdvPrint Pro - invite link</title><style>
 body{font:15px/1.55 "Segoe UI",system-ui,sans-serif;background:#f5f8fc;
      color:#0f172a;margin:0;padding:24px}
 .box{max-width:560px;margin:8vh auto;background:#fff;border:1px solid #e2e8f0;
      border-radius:14px;padding:24px;box-shadow:0 8px 30px #0f172a14}
 h1{font-size:19px;color:#b91c1c;margin:0 0 6px} p{color:#475569;margin:8px 0}
 .brand{font-size:11px;color:#94a3b8;text-align:center;margin-top:14px}
</style></head><body><div class="box">
 <h1>This invite link is not valid</h1>
 <p>@@MSG@@</p>
 <p>Ask the other PC for a FRESH invite: on its AdvPrint Pro dashboard,
    LAN card &rarr; <b>Copy invite link</b> (the token changes when the
    hub token is rotated).</p>
 <div class="brand">AdvPrint Pro v@@VERSION@@ - by Bit Dream IT -
   100% local - no cloud, no tracking</div>
</div></body></html>""".replace("@@MSG@@", esc_html(message)) \
                        .replace("@@VERSION@@", VERSION)


def peer_connect_result_html(ok, title, lines, show_dashboard=True):
    rows = "".join("<p>%s</p>" % esc_html(l) for l in lines)
    btn = ("<a href=\"/dashboard\"><button>Open my dashboard</button></a>"
           if show_dashboard else "")
    return ("""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AdvPrint Pro - peer connect</title><style>
 body{font:15px/1.55 "Segoe UI",system-ui,sans-serif;background:#f5f8fc;
      color:#0f172a;margin:0;padding:24px}
 .box{max-width:560px;margin:8vh auto;background:#fff;border:1px solid #e2e8f0;
      border-radius:14px;padding:24px;box-shadow:0 8px 30px #0f172a14}
 h1{font-size:19px;margin:0 0 6px;color:@@COLOR@@}
 p{color:#475569;margin:8px 0}
 .brand{font-size:11px;color:#94a3b8;text-align:center;margin-top:14px}
 a{text-decoration:none}
 button{border:none;border-radius:10px;background:#1d4ed8;color:#fff;
        font:700 15px "Segoe UI",system-ui;padding:12px 18px;cursor:pointer;
        display:inline-block}
</style></head><body><div class="box">
 <h1>@@TITLE@@</h1>
 @@ROWS@@
 <p>@@BTN@@</p>
 <div class="brand">AdvPrint Pro v@@VERSION@@ - by Bit Dream IT -
   100% local - no cloud, no tracking</div>
</div></body></html>"""
             .replace("@@COLOR@@", "#166534" if ok else "#b91c1c")
             .replace("@@TITLE@@", esc_html(title))
             .replace("@@ROWS@@", rows)
             .replace("@@BTN@@", btn)
             .replace("@@VERSION@@", VERSION))

# ------------------------------------------------------------
# v2.8 - RESTART: the tray menu and the dashboard button relaunch
# the hub as a NEW process and exit this one. The new process is
# started with ADVPRINT_RESTART=1 so it waits for the old listener
# to let go of the port instead of hitting the single-instance guard.
# ------------------------------------------------------------
def _relaunch_process():
    try:
        exe = launcher_exe()
        base = hub_dir()
        script = os.path.join(base, "advprint.py")
        env = dict(os.environ)
        env["ADVPRINT_RESTART"] = "1"
        if IS_WIN:
            DETACHED = 0x00000008 | 0x00000200   # DETACHED_PROCESS | NEW_GROUP
            si = subprocess.STARTUPINFO()
            try:
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            except AttributeError:
                pass
            subprocess.Popen([exe, script, "serve"], cwd=base, env=env,
                             creationflags=DETACHED, startupinfo=si,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen([sys.executable, script, "serve"], cwd=base,
                             env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
        log("[RESTART] new hub process launched - this process exits now")
        return True
    except Exception as e:
        log("[RESTART] FAILED to launch the new hub process: %s" % e)
        return False

def _restart_and_exit():
    """v2.8: launch the replacement hub, then leave. If the launch FAILS
    this process stays alive - a restart must never take printing down."""
    if _relaunch_process():
        threading.Timer(1.0, os._exit, args=(0,)).start()
    else:
        log("[RESTART] keeping THIS process alive - the new hub could not "
            "be started (check hub.log)")

def cmd_serve():
    # v2.6.1: bracket EVERY startup in hub.log - if the hub dies on this
    # PC, hub.log now always shows how far it got and why it stopped.
    log("[BOOT] AdvPrint Pro v%s starting - python %s at %s"
        % (VERSION, "%d.%d.%d" % sys.version_info[:3], sys.executable))
    log("[BOOT] data dir: %s" % CFG["data_dir"])
    log("[BOOT] this log: %s (send the last 20 lines when asking for help)"
        % os.path.join(CFG["data_dir"], "hub.log"))
    try:
        db_init()
        start_worker()
        start_health_refresher()
        start_drop_watcher()      # v2.8 DropZone: folder -> printer
    except Exception:
        import traceback
        log("[BOOT] FATAL: startup failed before opening the port:")
        log(traceback.format_exc())
        raise
    host = CFG["host"]
    # v2.8.2: the main listener ALWAYS stays on its normal bind
    # (127.0.0.1 unless ADVPRINT_HOST pins it). LAN sharing no longer
    # rebinds THIS socket - a second listener on the specific LAN IP
    # starts right after the loopback one is up (lan_listen_start), so
    # "Enable LAN sharing" works instantly and a LAN bind failure can
    # never take local printing down.
    global BOUND_LAN
    BOUND_LAN = (host in ("0.0.0.0", "::"))
    if CFG.get("share_lan") and not _env("HOST"):
        log("[LAN] printer sharing ON at boot - the LAN listener starts"
            " right after the loopback one (http://%s:%d, token"
            " required)" % (lan_ip(), CFG["port"]))
    addr = (host, CFG["port"])
    # v2.8 RESTART support: the replacement process (ADVPRINT_RESTART=1,
    # set by _relaunch_process) SKIPS the single-instance pre-check - the
    # old hub is still answering during its last second - and instead
    # WAITS up to 12 s for the old listener to release the port.
    restarting = _env("RESTART") == "1"
    if restarting:
        log("[RESTART] ADVPRINT_RESTART=1 - waiting for the previous hub "
            "process to release port %d" % CFG["port"])
    else:
        # v2.6.3 single-instance pre-check: when OUR hub already answers on
        # the port, this second start exits cleanly BEFORE touching the
        # socket (previously the second instance could double-bind).
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/health" % CFG["port"],
                    timeout=2) as r:
                pre = json.loads(r.read().decode("utf-8", "replace"))
            if pre.get("app") == APP_NAME:
                log("[BOOT] AdvPrint Pro v%s is ALREADY running on port %d -"
                    " this second start exits (single-instance guard)."
                    % (pre.get("version", "?"), CFG["port"]))
                time.sleep(0.8)
                return
        except Exception:
            pass
    deadline = time.time() + (12.0 if restarting else 0.0)
    while True:
        try:
            httpd = HubServer(addr, Handler)
            break
        except OSError as e:
            if restarting and time.time() < deadline:
                time.sleep(0.5)       # old process is shutting down
                continue
            # second instance guard: hub already running? do not scare the user
            log("FATAL: cannot bind %s:%d (%s)"
                % (CFG["host"], CFG["port"], e))
            log("AdvPrint Pro is probably ALREADY running (check the tray icon"
                " near the clock, or Task Manager -> 'AdvPrintPro'). Exiting.")
            time.sleep(1.2)
            return
    httpd.daemon_threads = True
    # v2.6.3: warm the health snapshot BEFORE the first request (cheap:
    # cached printer data only - no PowerShell on this path).
    try:
        build_health_snapshot()
    except Exception:
        pass
    # v2.8.2: bring the LAN listener up when the saved config says LAN
    # sharing was ON last time. A bind failure is LOGGED, never fatal -
    # local printing (127.0.0.1) is already up at this point.
    if CFG.get("share_lan") and not _env("HOST"):
        err = lan_listen_start()
        if err:
            log("[LAN] %s" % err)
    print(BANNER)
    log("%s" % BRANDING)
    log("AdvPrint Pro v%s listening on http://%s:%d" % (VERSION, CFG["host"], CFG["port"]))
    log("Health check -> http://127.0.0.1:%d/health" % CFG["port"])
    # v2.9.1 (audit L8 fix): the startup line no longer prints the FULL
    # dashboard URL with the token in it (console transcripts get pasted
    # into chats / tickets). The tray menu and the loopback 302 auto-repair
    # still open the real dashboard with one click.
    log("Dashboard     -> http://127.0.0.1:%d/dashboard?token=%s"
        % (CFG["port"], mask_token(CFG["token"])))
    if DEFAULT_TOKEN_WARNING:
        log("[SECURITY] WARNING: the default token is still in use!"
            " Change it with:  %s" % cli_cmd("token-rotate"))
    log("Open THE ONE UI console:  http://127.0.0.1:%d/ui  (the toolbar "
        "icon opens it too). Press Ctrl+C to stop." % CFG["port"])
    _start_tray(httpd)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("stopped by user (Ctrl+C)")


def _start_tray(httpd):
    """Windows tray icon ('AdvPrint Pro' next to the clock) with a control
    menu. 100% optional: any failure just means no tray icon."""
    if not IS_WIN:
        return
    try:
        import tray_windows
    except Exception as e:
        log("tray icon unavailable (%s) - printing still works" % e)
        return

    def _open_status():
        # v2.6: the tray ALWAYS opens the real dashboard with the
        # current token (the user never has to know the token).
        webbrowser.open("http://127.0.0.1:%d/dashboard?token=%s"
                        % (CFG["port"], urllib.parse.quote(CFG["token"])))

    def _open_console():
        # v3.1.2: the tray opens THE ONE UI - the IDM-style console at
        # /ui (same page as the gui_app window and the extension).
        webbrowser.open("http://127.0.0.1:%d/ui?token=%s"
                        % (CFG["port"], urllib.parse.quote(CFG["token"])))

    def _test():
        data, _ = thermal_pdf_bytes(
            "#big AdvPrint Pro TEST PAGE\n\nIf this page printed, the hub works.\n"
            "Time: %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tray-test", paper="a4")
        job, _dup = enqueue_print("a4", "tray-test", data, dedupe=False,
                                  origin_ip="tray")
        log("[OK] test page queued from tray (job #%d)" % job)

    def _pause_toggle():
        if RESUME_EVENT.is_set():
            RESUME_EVENT.clear()
            log("[QUEUE] paused via tray menu")
            return True
        RESUME_EVENT.set()
        log("[QUEUE] resumed via tray menu")
        return False

    def _auto_toggle():
        newv = not autostart_enabled()
        return autostart_set(newv)

    def _restart():
        # v2.8: Restart hub - relaunch as a NEW process, then exit this
        # one. Used after changing share_lan / host settings so the user
        # never has to find the process in Task Manager.
        db_audit("hub.restart", actor="tray",
                 details="restart from the tray menu")
        log("[RESTART] restart requested from the tray menu")
        threading.Timer(0.4, _restart_and_exit).start()

    def _fw_allow():
        # v2.8.2: one-click Windows firewall fix from the tray. Runs in
        # a helper thread - the UAC prompt can stay open for a while
        # and the tray menu must never freeze behind it.
        log("[FIREWALL] 'Allow LAN in firewall' requested from the tray")
        threading.Thread(target=firewall_allow, daemon=True,
                         name="advprint-fw").start()

    def _exit():
        log("AdvPrint Pro stopped from the tray icon menu")
        threading.Timer(0.5, os._exit, args=(0,)).start()
        try:
            threading.Thread(target=httpd.shutdown, daemon=True).start()
        except Exception:
            pass

    tray_windows.start(
        icon=hub_icon_path(),
        tooltip="AdvPrint Pro v%s - running on http://127.0.0.1:%d"
                % (VERSION, CFG["port"]),
        callbacks={
            "on_open": _open_status,
            "on_console": _open_console,
            "on_test": _test,
            "is_paused": lambda: not RESUME_EVENT.is_set(),
            "on_pause_toggle": _pause_toggle,
            "is_autostart": autostart_enabled,
            "on_autostart_toggle": _auto_toggle,
            "on_restart": _restart,
            "on_firewall": _fw_allow,
            "on_exit": _exit,
        },
        logf=log)
    log("[TRAY] icon active next to the clock - right-click it for the"
        " control menu (Open dashboard / test page / pause / auto-run"
        " / restart / allow LAN in firewall / exit).")

def cmd_testprint(kind):
    db_init(); start_worker()
    kind = kind if kind in ("a4", "thermal") else "a4"
    if kind == "thermal":
        data, _ = thermal_pdf_bytes(
            "#big AdvPrint Pro\n|center|Bit Dream IT - TEST RECEIPT\n"
            "--------------------------------\n"
            "Item 1              10.00\nItem 2              25.50\n"
            "--------------------------------\nTOTAL               35.50\n"
            "\n|center|Thank you!\n", "testprint")
    else:
        data, _ = thermal_pdf_bytes(
            "#big AdvPrint Pro TEST PAGE\n\nIf this page printed, the hub works.\n"
            "Time: %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "testprint", paper="a4")
    job, _dup = enqueue_print(kind, "cli-" + kind, data, dedupe=False,
                              origin_ip="cli")
    print("Job #%d queued (%s). Watch the printer..." % (job, kind))

def cmd_history(limit):
    db_init()
    rows = db_list(limit)
    if not rows:
        print("No print jobs yet.")
        return
    print("%-4s %-19s %-8s %-22s %-9s %-9s %-7s %s" %
          ("ID", "TIME", "KIND", "PRINTER", "STATUS", "SOURCE", "MS", "TITLE"))
    print("-" * 100)
    for r in rows:
        print("%-4s %-19s %-8s %-22s %-9s %-9s %-7s %s" %
              (r["id"], (r["created_at"] or "")[0:19], r["kind"],
               (r["printer"] or "-")[:22], r["status"],
               r.get("source") or "-", r["duration_ms"] or "-",
               r["title"] or "-"))

def cmd_reprint(job_id, reason=None, printer=None):
    db_init(); start_worker()
    j = db_get(int(job_id))
    if not j:
        print("Job #%s not found." % job_id); sys.exit(1)
    if not (j.get("file_path") and os.path.exists(j["file_path"])):
        print("Original file of job #%s is gone - cannot reprint." % job_id); sys.exit(1)
    with open(j["file_path"], "rb") as f:
        data = f.read()
    if CFG.get("reprint_watermark"):
        data = pdf_watermark(data)
    nid, _dup = enqueue_print(j["kind"], (j["title"] or "reprint") + "-reprint",
                              data, printer or j["printer"] or "",
                              j["copies"] or 1, "cli", "cli",
                              dedupe=False, reason=reason)
    db_audit("reprint", job_id=nid, actor="cli", reason=reason,
             printer=printer or j["printer"],
             details="reprint of job #%s" % job_id)
    print("Reprinted as job #%d (copy of #%d)." % (nid, j["id"]))

def cmd_token():
    db_init()
    print("Current hub token: %s" % CFG["token"])
    print("(enter it in the extension Options page; stored in %s)"
          % config_path())
    if DEFAULT_TOKEN_WARNING:
        print("WARNING: this is the DEFAULT token - rotate it with:")
        print("  python advprint.py token-rotate")

def cmd_token_rotate():
    db_init()
    old = CFG["token"]
    CFG["token"] = secrets.token_urlsafe(24)
    disk = {k: CFG[k] for k in CONFIG_KEYS}
    write_config_file(disk)
    db_audit("token.rotated", actor="cli",
             details="token changed via CLI")
    print("Token ROTATED.")
    print("  old: %s" % old)
    print("  new: %s" % CFG["token"])
    print("Enter the new token in the extension Options page.")

def cmd_diagnostics():
    db_init()
    diag = build_diagnostics()
    fname = "diagnostics-%s.json" % datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(CFG["data_dir"], fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(diag, f, indent=2, ensure_ascii=False)
    print(BANNER)
    print("Diagnostics written to:")
    print("  %s" % path)
    print("(the token is redacted - attach this file to support requests)")
    return path

def cmd_queue():
    db_init()
    paused = not RESUME_EVENT.is_set()
    cur = None
    with _CURRENT_LOCK:
        if _CURRENT["id"]:
            cur = db_get(_CURRENT["id"])
    print("Queue: %s | pending: %d" % ("PAUSED" if paused else "running",
                                       db_count_pending()))
    if cur:
        print("Current: job #%d %s -> %s" % (cur["id"], cur["title"],
                                             cur["printer"] or "default"))

def run_livetest(do_print=False):
    """v2.6 LIVE TEST: the A-to-Z production check, shared by
    POST /livetest (dashboard button), the desktop tool and
    "python advprint.py livetest". Returns {ok, steps:[...]}.
    With do_print=True a REAL test page is queued and polled."""
    steps = []

    def step(name, passed, info=""):
        steps.append({"name": name, "pass": bool(passed),
                      "info": str(info)[:220]})
        return bool(passed)

    ok = True
    # 1 python
    ok &= step("Python >= 3.8", sys.version_info >= (3, 8),
               sys.version.split()[0])
    # 2 data dir
    try:
        db_init()
        step("Data folder + history.db writable", True, CFG["data_dir"])
    except Exception as e:
        ok &= step("Data folder + history.db writable", False, str(e))
    # 3 token
    tok_ok = bool(CFG.get("token"))
    ok &= step("API token configured", tok_ok,
               "(default token - rotate it: python advprint.py token-rotate)"
               if DEFAULT_TOKEN_WARNING else "private random token")
    # 4 print engine
    if IS_WIN:
        sfind = find_sumatra()
        ok &= step("SumatraPDF (silent PDF printing)", bool(sfind),
                   sfind or "NOT FOUND - " + SUMATRA_HINT)
    else:
        lp = shutil.which("lp")
        ok &= step("CUPS lp command", bool(lp),
                   lp or "apt install cups-client")
    b = find_browser()
    step("Chrome/Edge (HTML page printing)", bool(b),
         b or "optional - needed only for web-page jobs")
    # 5 port: free, or already serving = BOTH are success (the self-test
    # is usually run from the live hub itself)
    serving = False
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/health" % CFG["port"], timeout=1.5) as r:
            serving = (r.getcode() == 200)
    except Exception:
        serving = False
    free = False
    if not serving:
        sock = socket.socket()
        try:
            sock.bind((CFG["host"], CFG["port"]))
            free = True
        except OSError:
            free = False
        finally:
            sock.close()
    ok &= step("Port %d (free or serving)" % CFG["port"],
               free or serving,
               "hub is serving on 127.0.0.1:%d" % CFG["port"] if serving
               else ("free" if free else "busy - another program?"))
    # 6 queue mechanics: insert/read/update a DB row directly (status
    # canceled from the start - the worker never touches it, no printer
    # involved). Proves history.db + FIFO bookkeeping end to end.
    try:
        jid = db_add("a4", "livetest-internal", "__none__", 1, "",
                     "livetest", "livetest", status="canceled",
                     content_hash="livetest-%d" % time.time())
        row = db_get(jid)
        db_update(jid, error="canceled by livetest")
        row2 = db_get(jid)
        ok &= step("Queue DB enqueue/read/update (job #%d)" % jid,
                   bool(row and row["id"] == jid and row2
                        and row2.get("error") == "canceled by livetest"))
    except Exception as e:
        ok &= step("Queue DB enqueue/read/update", False, repr(e))
    # 7 printers
    dps = list_printers()
    dp = default_printer()
    step("Printers detected", bool(dps),
         ", ".join(dps[:5]) or "none found")
    step("Default printer", bool(dp), dp or "none set")
    # 8 optional real print
    if do_print and dps:
        try:
            job, _dup = enqueue_print("a4", "livetest-page",
                                      thermal_pdf_bytes(
                                          "#big AdvPrint Pro LIVE TEST\n"
                                          "If this printed, everything works.\n"
                                          "Time: %s" % datetime.now()
                                          .strftime("%Y-%m-%d %H:%M:%S"),
                                          "livetest", paper="a4")[0],
                                      dedupe=False, origin_ip="livetest")
            step("Real test page queued (job #%d)" % job, True,
                 "watch it on the dashboard Queue tab")
        except Exception as e:
            ok &= step("Real test page", False, repr(e))
    return {"ok": True, "all_ok": bool(ok), "version": VERSION,
            "app": APP_NAME, "steps": steps}


def cmd_livetest(do_print=False):
    db_init()
    init_config()
    print(BANNER)
    res = run_livetest(do_print=do_print)
    for st in res["steps"]:
        print("  [%s] %-38s %s" % ("OK" if st["pass"] else "!!",
                                   st["name"], st["info"]))
    print("\n  %s" % ("ALL CHECKS PASSED - AdvPrint Pro is ready for"
                       " production." if res["all_ok"] else
                       "Fix the [!!] items above, then run livetest again."))
    return 0 if res["all_ok"] else 1


def cmd_doctor():
    print(BANNER)
    results = []
    results.append(("Python >= 3.8", sys.version_info >= (3, 8),
                    sys.version.split()[0]))
    results.append(("OS", True, "windows" if IS_WIN else ("macos" if IS_MAC else "linux")))
    if IS_WIN:
        s = find_sumatra()
        results.append(("SumatraPDF (silent PDF print)", bool(s),
                        s or "NOT FOUND - " + SUMATRA_HINT))
    else:
        lp = shutil.which("lp")
        results.append(("CUPS lp command", bool(lp), lp or "apt install cups-client"))
    b = find_browser()
    results.append(("Chrome/Edge (page printing)", bool(b), b or "optional - needed only for HTML/page printing"))
    try:
        db_init(); results.append(("Data dir + history.db writable", True, CFG["data_dir"]))
    except Exception as e:
        results.append(("Data dir + history.db writable", False, str(e)))
    import socket
    sock = socket.socket()
    try:
        sock.bind((CFG["host"], CFG["port"])); free = True
    except OSError:
        free = False
    finally:
        sock.close()
    results.append(("Port %d free" % CFG["port"], free,
                    "OK" if free else "busy - another instance running?"))
    dps = list_printers()
    results.append(("Printers detected", bool(dps),
                    ", ".join(dps[:5]) or "none found"))
    results.append(("Default printer", bool(default_printer()),
                    default_printer() or "none set"))
    try:
        db_init()
        results.append(("v2.0 config.json", True,
                        config_path() +
                        ("  [DEFAULT TOKEN! rotate it]"
                         if DEFAULT_TOKEN_WARNING else "")))
    except Exception as e:
        results.append(("v2.0 config.json", False, str(e)))
    ok = True
    for name, passed, info in results:
        print("  [%s] %-34s %s" % ("OK" if passed else "!!", name, info))
        if not passed and "Printers" not in name and "Default printer" not in name \
                and "Chrome/Edge" not in name:
            ok = False
    print("\n  %s" % ("ALL CHECKS PASSED - start the hub with: python advprint.py serve" if ok
                      else "Fix the [!!] items above, then run doctor again."))

def cmd_help():
    print(BANNER)
    print("""Commands:
  serve                     Start the hub (default) - listens on port %d
  testprint [a4|thermal]    Send a test page to the default printer
  printers                  List installed printers (+ status)
  history [n]               Show last n print jobs (default 100)
  reprint <job_id>          Print a previous job again
  queue                     Show queue status (paused / pending / held)
  doctor                    Check everything and report [OK]/[!!]
  livetest [print]          FULL live self-test (A-to-Z; "print" also
                            queues a REAL test page on the printer)
  token                     Show the current API token
  token-rotate              Generate a NEW random token (old one stops)
  diagnostics               Export a support bundle (JSON, token redacted)
  service-install           Install AdvPrint as a Windows service (UAC)
  service-remove            Remove the Windows service (UAC)
  service-status            Show Windows service state
  service <action>          Alias: service install|remove|status
  update-check              Check GitHub for a newer release
  help                      This help

Settings (config.json in the data dir - see docs/API.md):
  allowed_origins           Restrict which websites may print (default: all)
  printer_groups            {"Front": ["A", "B"]} fallback printers
  profiles                  {"Invoice": {"paper": "a4", "duplex": true}}
  max_retries               Exponential retry attempts (default 2)
  dedupe_minutes            Block duplicate jobs window (default 5)
  hold_offline              Hold jobs while printer offline (default on)
  reprint_watermark         Stamp REPRINT on reprints (default off)
  peer_hubs / peer_forwarding   Backup hubs on the network

Options (environment variables still override config.json):
  ADVPRINT_TOKEN    API token   (new installs: random, see 'token' command)
  ADVPRINT_PORT     HTTP port   (default 9235)
  ADVPRINT_HOST     Bind addr   (default 127.0.0.1 = this PC only)
  ADVPRINT_PRINTER  Force printer name (default: OS default)
  ADVPRINT_FILE_DIR Where "destination:file" PDFs are saved
                    (default ~/Downloads/AdvPrint)
  ADVPRINT_DATA     Data folder (default ~/.advprint;
                    old ~/.printhub is migrated automatically)

One-click token fix: a wrong dashboard link offers "Fix it now" on the
error page itself (works on this PC - loopback only).

Chrome extension: see extension/ folder - load it unpacked in Chrome,
then click the AdvPrint icon and press Connect.
Dashboard: http://127.0.0.1:9235/dashboard?token=<your token>
""" % CFG["port"])

def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "serve"
    try:
        if cmd in ("serve", "start"):
            cmd_serve()
        elif cmd == "testprint":
            cmd_testprint(args[1] if len(args) > 1 else "a4")
        elif cmd == "printers":
            st = printers_status()
            ps = list_printers()
            if not ps:
                print("No printers found.")
            for p in ps:
                print("%-38s %s" % (p, st.get(p, "unknown")))
        elif cmd == "history":
            cmd_history(int(args[1]) if len(args) > 1 else HISTORY_DEFAULT)
        elif cmd == "reprint":
            if len(args) < 2:
                print("usage: python advprint.py reprint <job_id> [reason]")
                sys.exit(1)
            reason = args[2] if len(args) > 2 else None
            cmd_reprint(args[1], reason=reason)
        elif cmd == "queue":
            cmd_queue()
        elif cmd == "doctor":
            cmd_doctor()
        elif cmd == "livetest":
            sys.exit(cmd_livetest(
                do_print=(len(args) > 1 and args[1] == "print")))
        elif cmd == "token":
            cmd_token()
        elif cmd == "token-rotate":
            cmd_token_rotate()
        elif cmd == "diagnostics":
            cmd_diagnostics()
        elif cmd == "service-install":
            cmd_service("install")
        elif cmd == "service-remove":
            cmd_service("remove")
        elif cmd == "service-status":
            cmd_service("status")
        elif cmd == "service" and len(args) > 1 \
                and args[1] in ("install", "remove", "status"):
            # v2.5.2: the service-install.ps1 / service-remove.ps1 helpers
            # call "advprint.py service install" (space form) - accept it
            # (args = sys.argv[1:], so the action is args[1])
            cmd_service(args[1])
        elif cmd == "update-check":
            rc = cmd_update_check()
            if rc:
                sys.exit(rc)
        elif cmd in ("help", "--help", "-h"):
            cmd_help()
        elif cmd in ("--version", "version"):
            print("AdvPrint Pro v%s by %s" % (VERSION, VENDOR))
        else:
            print("Unknown command: %s\n" % cmd)
            cmd_help(); sys.exit(1)
    except KeyboardInterrupt:
        print("\nBye!")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        # v2.6.1: a silent death is the worst failure mode (pythonw has no
        # console) - ALWAYS leave the reason in hub.log so the desktop tool
        # can show it and support can see exactly what happened.
        try:
            import traceback
            log("[BOOT] FATAL - the hub crashed with an exception:")
            log(traceback.format_exc())
        except Exception:
            pass
        raise

