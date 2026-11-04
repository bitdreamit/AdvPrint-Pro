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
import json
import os
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
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, parse_qsl, quote

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


VERSION = "2.9.0"
VERSION_NAME = ("v2.9.0 (NETWORK PRINTER MODE: add this PC like a real"
                " IP printer - IPP at /ipp/print for Windows 10/11 'add a"
                " printer by URL' and phone print services, plus a"
                " JetDirect RAW listener on TCP 9100 for the classic"
                " 'Add a printer using TCP/IP address' flow; PDF, JPEG,"
                " PostScript, PCL, ESC/POS and ZPL payloads all routed to"
                " the real printer. Phone 'Auth fail' on the Send portal"
                " QR is FIXED (token now accepted from the portal link in"
                " token_header_only mode too), the extension shows ONE"
                " version everywhere read from the manifest, and the tray"
                " menu is smooth - every action runs in its own thread)")
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
    "share_lan": False,               # v2.1: listen on 0.0.0.0 so OTHER PCs
                                      #  on the LAN can print through this
                                      #  PC's printers (token always required)
    "ipp_printer": True,              # v2.9: expose this hub as an IPP
                                      #  network printer at /ipp/print so
                                      #  Windows 10/11 ("add a printer by
                                      #  URL") and phone print services can
                                      #  add it like a normal IP printer
    "raw_printer_port": 9100,         # v2.9: JetDirect RAW listener port for
                                      #  Windows "Standard TCP/IP port"
                                      #  printers (0 = off)
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
               "share_lan", "escpos_codepage", "thermal_text_engine",
               "log_max_mb", "log_backups", "debug", "instant_auto_queue",
               "printer", "file_dir", "sumatra_path",
               "drop_enabled", "drop_dir", "drop_delete")
CONFIG_TYPES = {"token_header_only": bool, "allowed_origins": list,
                "pdf_url_allowed_hosts": list, "max_auth_failures": int,
                "lockout_minutes": int, "lockout_exempt_loopback": bool,
                "printer_groups": dict,
                "profiles": dict, "max_retries": int,
                "retry_base_seconds": int, "dedupe_minutes": int,
                "hold_offline": bool, "audit_enabled": bool,
                "share_lan": bool, "ipp_printer": bool,
                "raw_printer_port": int,
                "reprint_watermark": bool, "reprint_reason_required": bool,
                "peer_hubs": list, "peer_forwarding": bool,
                "log_max_mb": int, "log_backups": int,
                "debug": bool, "instant_auto_queue": bool,
                "sumatra_path": str,   # v2.5: manual SumatraPDF.exe override
                "drop_enabled": bool, "drop_dir": str,
                "drop_delete": bool}   # v2.8 DropZone settings

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
            log("[TOKEN] new install - generated a private random token and"
                " saved it to %s" % config_path())
            log("[TOKEN] token: %s" % CFG["token"])
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

def db_init():
    ensure_dirs()
    init_config()
    with _DB_LOCK, db() as conn:
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
        "ipp_printer": bool(CFG.get("ipp_printer", True)),
        "ipp_url": ("http://%s:%d/ipp/print" % (lan_ip(), CFG["port"]))
                   if CFG.get("share_lan") else None,
        "raw_printer_port": int(CFG.get("raw_printer_port") or 0),
        "raw_active": bool(_RAW_TCP is not None),
        "lan_active": bool(BOUND_LAN),
        "lan_url": ("http://%s:%d" % (lan_ip(), CFG["port"]))
                   if CFG.get("share_lan") else None,
        # v2.8.2: diagnostics for "the other PC cannot connect"
        "lan_ip": lan_ip(),
        "lan_bind_ip": _LAN_BIND_IP,
        "firewall_ok": firewall_rule_ok(),
        "hostname": socket.gethostname(),
        "success_rate": st.get("success_rate") if st else None,
        "printers_ready": ready,
        "audit": bool(CFG.get("audit_enabled", True)),
        "loopback_lock_exempt": True,
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
    return bytes(out), "".join(c for c in fname if c.isalnum() or c in "-._")

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
    return bytes(out), "".join(c for c in fname if c.isalnum() or c in "-._")

def pages_h(page_lines):
    MM = 72 / 25.4
    h = 10 * MM + len(page_lines) * 3.6 * MM
    return max(60 * MM, h)

# ------------------------------------------------------------
# HTML / web page -> PDF via headless Chrome or Edge (zero pip)
# ------------------------------------------------------------
def html_to_pdf_bytes(source, is_url=True, title="page"):
    """
    Render an HTML string or a URL to PDF using headless Chrome/Edge.
    Uses a throwaway profile dir so it never fights the user's browser.
    Returns (pdf_bytes, suggested_filename).
    """
    exe = find_browser()
    if not exe:
        raise RuntimeError(
            "No Chrome/Edge found for page printing. Install Google Chrome"
            " (or print PDFs instead - SumatraPDF handles those directly).")
    out_path = os.path.join(tempfile.gettempdir(),
                            "advprint-%s.pdf" % os.getpid())
    profile = tempfile.mkdtemp(prefix="advprint-profile-")
    if is_url:
        target = source
    else:
        html_path = os.path.join(tempfile.gettempdir(),
                                 "advprint-%s.html" % os.getpid())
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(source)
        target = "file:///" + html_path.replace("\\", "/").lstrip("/")

    def attempt(headless_flag):
        cmd = [exe, headless_flag, "--disable-gpu", "--no-first-run",
               "--disable-extensions", "--user-data-dir=" + profile,
               "--no-pdf-header-footer",
               "--print-to-pdf=" + out_path, target]
        if IS_WIN:
            return subprocess.run(cmd, capture_output=True, timeout=120,
                                  creationflags=HIDE)
        return subprocess.run(cmd, capture_output=True, timeout=120)

    pdf = None
    try:
        for flag in ("--headless=new", "--headless"):
            try:
                proc = attempt(flag)
            except subprocess.TimeoutExpired:
                continue
            if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
                with open(out_path, "rb") as f:
                    pdf = f.read()
                break
        if not pdf or not pdf[:5].startswith(b"%PDF"):
            raise RuntimeError(
                "headless browser did not produce a PDF (page blocked,"
                " login required, or browser too old)")
    finally:
        for p in (out_path,):
            try:
                os.unlink(p)
            except OSError:
                pass
        shutil.rmtree(profile, ignore_errors=True)
    fname = "%s-%s.pdf" % (title or "page", datetime.now().strftime("%Y%m%d%H%M%S"))
    return pdf, "".join(c for c in fname if c.isalnum() or c in "-._")

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
    target = printer or CFG["printer"] or default_printer() or ""

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
                parts.append("paper=%s" % re.sub(r"[^A-Za-z0-9]", "",
                                                 str(paper_size)) or "A4")
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


def _write_atomic(path, data, attempts=4):
    """v2.6.7: write bytes via a .part file + os.replace so readers never
    see a partial PDF, retrying while the destination folder is briefly
    locked (antivirus / OneDrive / sync tools)."""
    tmp = "%s.part%d" % (path, os.getpid())
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


def _save_virtual_pdf(job):
    """v2.5: write the job's PDF straight into the save-as-PDF folder
    (Downloads\\AdvPrint by default). Status 'saved' - no Save-As dialog,
    works even with NO physical printer installed."""
    jid = job["id"]
    try:
        fdir = default_file_dir()
        os.makedirs(fdir, exist_ok=True)
        safe = "".join(c for c in (job.get("title") or "document")
                       if c.isalnum() or c in "-_ ")[:50].strip() or "document"
        base = "%s-%s" % (safe.replace(" ", "_"),
                          datetime.now().strftime("%Y%m%d-%H%M%S"))
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
        data = _read_locked(job["file_path"])
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
    final attempt (visible in the dead-letter list, retryable)."""
    attempts = int(job.get("attempts") or 0) + 1
    maxr = max(0, int(CFG.get("max_retries", 2)))
    if attempts <= maxr:
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

def _try_peer_forward(job):
    """Offline/unknown printer + peer_forwarding on: send the document to
    the first ALIVE peer hub that has the printer. Dead peers are skipped.
    Returns True when the job was handed over."""
    if not CFG.get("peer_forwarding"):
        return False
    peers = CFG.get("peer_hubs") or []
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
                    continue     # peer alive but no such printer - next peer
            payload = json.dumps({
                "pdf_base64": base64.b64encode(data).decode("ascii"),
                "title": job.get("title") or "peer",
                "printer": want, "copies": job.get("copies") or 1,
                "kind": job.get("kind") or "a4",
                "source": "peer:%s" % CFG["port"]}).encode()
            req = urllib.request.Request(
                url + "/print", data=payload, headers=dict(
                    headers, **{"Content-Type": "application/json"}))
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read().decode("utf-8", "replace"))
            if resp.get("ok"):
                db_update(job["id"], status="forwarded", peer=url,
                          error=None,
                          held_reason=None,
                          duration_ms=None)
                db_audit("job.forwarded", job_id=job["id"], printer=want,
                         details="forwarded to peer %s (job %s)" %
                                 (url, resp.get("job_id")))
                log("[PEER] job #%d forwarded to %s (remote job %s)"
                    % (job["id"], url, resp.get("job_id")))
                return True
        except Exception as e:
            log("[PEER] %s skipped (%s)" % (url, str(e)[:80]))
            continue
    return False

def _execute_job(job, t0):
    """Print one job - the status-aware group pick goes first, the other
    group members follow as real fallback, then history + audit + retry."""
    path, kind, printer = _job_print_args(job)
    members = printer_group_members(job.get("printer") or "")
    if members:
        first = pick_group_printer(job.get("printer") or "") or members[0]
        candidates = [first] + [m for m in members if m != first]
    else:
        candidates = [printer] if printer else [""]
    last_err = None
    for cand in candidates:
        try:
            target = print_file(path, kind, cand, job.get("copies") or 1,
                                job_id=job["id"], pages=job.get("pages"),
                                duplex=job.get("duplex"),
                                paper_size=job.get("paper_size"),
                                tray=job.get("tray"),
                                per_sheet=job.get("per_sheet"),
                                quality=job.get("quality"))
                                
            ms = int((time.time() - t0) * 1000)
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
                time.sleep(0.35)
                continue
            if CFG.get("debug"):
                log("[DEBUG] worker picked job #%d (%s) for printer %r"
                    % (job["id"], job.get("kind"), job.get("printer")))
            # HOLD: printer offline / out of paper / error state (raw jobs
            # skip the status check - receipt printers rarely report state)
            if CFG.get("hold_offline", True) and job.get("kind") != "raw":
                pstat = printer_ready(job.get("printer") or "")
                if pstat in ("offline", "paper-out", "error"):
                    _hold_job(job, "printer '%s' is %s - job held until it"
                                  " is ready ('Print now' overrides this,"
                                  " or switch off 'Printer status hold' in"
                                  " the dashboard)"
                                  % (job.get("printer") or "default", pstat))
                    continue
                if pstat != "ready" and _try_peer_forward(job):
                    continue
            # v2.5: virtual PDF printer (Microsoft Print to PDF etc.) ->
            # save the PDF directly - no renderer, no Save-As dialog.
            if job.get("kind") != "raw" and is_virtual_pdf_printer(
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

def save_job_file(kind, title, data, ext="pdf"):
    """Write payload bytes into the jobs dir; returns full path."""
    ensure_dirs()
    safe = "".join(c for c in (title or "job") if c.isalnum() or c in "-_ ")[:40] or "job"
    fname = "%s-%s-%s.%s" % (safe.replace(" ", "_"),
                             datetime.now().strftime("%Y%m%d%H%M%S"),
                             os.getpid(), ext)
    path = os.path.join(CFG["data_dir"], "jobs", fname)
    with open(path, "wb") as f:
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
    path = save_job_file(kind, title, data, ext=ext)
    if not content_hash:
        content_hash = hashlib.sha256(data).hexdigest()
    dedupe_key = hashlib.sha256(("%s|%s|%s|%s" % (title, printer, kind,
                                                  content_hash))
                                .encode()).hexdigest()[:32]
    dup = None
    if dedupe:
        dup = db_find_duplicate(dedupe_key,
                                int(CFG.get("dedupe_minutes", 5)))
    if dup:
        log("[DEDUPE] job identical to #%d (%s) from %s - blocked"
            % (dup["id"], dup["title"], dup["created_at"]))
        try:
            os.unlink(path)
        except OSError:
            pass
        return dup["id"], dup["id"]
    status = "queued"
    next_at = None
    if run_at:
        status = "scheduled"
        next_at = run_at
    # v2.6.9 FIX (double print): decide direct-vs-queued BEFORE the DB row
    # exists. Queue Mode OFF used to insert the row as 'queued' and only
    # flip it to 'printing' AFTER the slow printer-status probe (hundreds
    # of ms on Windows) - the FIFO worker polls every 0.35 s and could
    # claim the job inside that window, so BOTH paths sent the same job to
    # the printer: two Sumatra runs, two '[OK] job #N' lines and the page
    # physically printed twice. Now the row is BORN in its final state
    # ('printing' for direct jobs) - the worker, which only claims
    # 'queued' rows, can never see a direct job.
    direct = (status == "queued" and not queue_mode)
    auto_hold = None
    # v2.3 INSTANT PRINT fallback: queue mode OFF + the printer is NOT
    # active -> auto-queue the job instead of firing a doomed direct
    # print. The FIFO worker then handles it like any other job (with
    # hold_offline it even waits for the printer to come back and
    # prints automatically). Raw/ESC-POS jobs skip the check - receipt
    # printers rarely report a usable status.
    if direct and CFG.get("instant_auto_queue", True) and kind != "raw":
        pstat = printer_ready(printer)
        if pstat in ("offline", "paper-out", "error"):
            auto_hold = pstat
            direct = False
    if direct:
        status = "printing"        # row never visible as 'queued'
    job_id = db_add(kind, title, printer, copies, path, source, origin_ip,
                    status=status, priority=max(1, min(9, int(priority or 5))),
                    run_at=run_at, next_attempt_at=next_at, site=site,
                    dedupe_key=dedupe_key, content_hash=content_hash,
                    **extra)
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
        if kind == "raw":
            with open(path, "rb") as f:
                data = f.read()
            target = print_raw(data, printer, job_id=job_id)
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
    safe = "".join(c for c in (title or "document")
                   if c.isalnum() or c in "-_ ")[:50].strip() or "document"
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
    ("Access-Control-Allow-Private-Network", "true"),   # Chrome/Firefox LAN preflight
    ("Access-Control-Max-Age", "86400"),
]

# v2.0 auth hardening state
_AUTH_FAILS = {}          # ip -> {count, until, first, last_audit, warned}
                          # 10 wrong tokens inside the window -> lock
                          # (v2.0.1: loopback IPs are exempt by default -
                          #  see lockout_exempt_loopback in CFG)
_AUTH_AUDIT_TS = {}       # ip -> last auth.failed audit write (survives
                          # success-clears so the audit log can never be
                          # flooded: max 1 row per 10 s per IP)
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
    """Read the request body as raw bytes (raw-PDF / multipart uploads)."""
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

def download_pdf(url):
    """Fetch a PDF from a URL (used by 'pdf_url' mode).
    v2.0: guarded by pdf_url_guard() - file://, ftp:// and private/local
    addresses are blocked (see pdf_url_allowed_hosts for exemptions)."""
    pdf_url_guard(url)
    req = urllib.request.Request(url, headers={"User-Agent": "AdvPrintPro/%s" % VERSION})
    with urllib.request.urlopen(req, timeout=30) as r:
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
    target = printer or CFG["printer"] or default_printer() or ""
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


class Handler(BaseHTTPRequestHandler):
    server_version = "AdvPrintPro/" + VERSION
    protocol_version = "HTTP/1.1"

    # ---- plumbing ----
    def _cors(self):
        for k, v in CORS_HEADERS:
            self.send_header(k, v)
        # v2.0 origin allowlist: echo the caller origin when allowed,
        # otherwise omit Access-Control-Allow-Origin (browser blocks it).
        # Empty list = allow every origin exactly like 1.x did.
        if CFG.get("allowed_origins"):
            origin = self.headers.get("Origin")
            if origin and (_extension_origin(origin) or origin_allowed(origin)):
                self.send_header("Access-Control-Allow-Origin", origin)
            else:
                self.send_header("Access-Control-Allow-Origin", "null")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")

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
        self.send_header("Content-Disposition",
                         'attachment; filename="%s"' % download_name)
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
        # dedupe: same peer URL -> replace the entry
        peers = [p for p in (CFG.get("peer_hubs") or [])
                 if str(p.get("url") or "").rstrip("/").lower()
                 != norm.rstrip("/").lower()]
        entry = {"url": "%s://%s" % (u.scheme, u.netloc), "token": token,
                 "name": name or host}
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
            return self._do_get_impl()
        except (BrokenPipeError, ConnectionResetError):
            pass                          # client hung up - fine
        except Exception:
            self._internal_error("GET")

    def do_POST(self):
        try:
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
                page = connect_error_html(
                    "The ?t= parameter does not match this hub's token -"
                    " the invite link is old or mistyped.").encode("utf-8")
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
            page = connect_page_html(str(it), iname).encode("utf-8")
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
        if route in ("/ipp/print", "/ipp", "/ipp/") and \
                not ipp_printer_enabled():
            return self._send(404, {"ok": False,
                                    "error": "IPP printer is off"})
        if route in ("/ipp/print", "/ipp", "/ipp/"):
            # v2.9.0: humans who open the IPP printer URL in a browser
            # get a short how-to (IPP clients POST binary IPP instead).
            host = socket.gethostname()
            return self._send_html(200, """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport"
 content="width=device-width,initial-scale=1"><title>AdvPrint Pro - IPP printer</title>
<style>body{font:15px/1.55 "Segoe UI",system-ui,sans-serif;background:#f5f8fc;
 color:#0f172a;margin:0;padding:24px}.b{max-width:560px;margin:4vh auto;background:#fff;
 border:1px solid #e2e8f0;border-radius:14px;padding:22px}
 code{background:#f1f5f9;border:1px solid #e2e8f0;border-radius:4px;padding:1px 6px;
 font-size:12.5px;word-break:break-all}</style></head><body><div class="b">
 <h1 style="font-size:19px">AdvPrint Pro - IPP network printer</h1>
 <p>This URL is the <b>IPP print endpoint of <span>%s</span></b>.
 Add it as a printer - do not open it in a browser:</p>
 <p><b>Windows 10/11:</b> Settings &rarr; Bluetooth &amp; devices &rarr;
 Printers &amp; scanners &rarr; Add device &rarr; Add manually &rarr;
 \u201cSelect a shared printer by name\u201d &rarr; paste
 <code>%s</code></p>
 <p><b>Phones:</b> a print service that supports manual IPP addresses
 (e.g. Samsung Print Service) can add <code>%s</code>. Or simply use
 the Send portal QR from the dashboard.</p>
 <p style="color:#64748b">100%% local - the hub prints on this PC's
 printer. Powered by AdvPrint Pro %s.</p>
 </div></body></html>""" % (_html_escape(host),
                             _html_escape(lan_share_url("ipp"), quote=True),
                             _html_escape(lan_share_url("ipp"), quote=True),
                             VERSION))
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
            items = []
            for n in list_printers_cached():
                items.append({"name": n, "is_default": n == dp,
                              "status": st.get(n, "unknown"),
                              "is_group": False})
            for g in groups:
                items.append({"name": g, "is_default": False,
                              "status": "group",
                              "is_group": True,
                              "members": groups[g]})
            return self._send(200, {
                "ok": True, "printers": items, "default": dp,
                "groups": groups})
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
            limit = (q.get("limit") or [str(HISTORY_DEFAULT)])[0]
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
            limit = (q.get("limit") or ["50"])[0]
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
            # Auth like every GET (?token= works), answer is an SVG image
            # that the dashboard <img> tag (and any phone camera) reads.
            kind = (q.get("kind") or ["send"])[0]
            if kind not in ("send", "invite", "ipp"):
                kind = "send"
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
        if route in ("/ipp/print", "/ipp", "/ipp/"):
            if not ipp_printer_enabled():
                return self._send(404, {"ok": False,
                                        "error": "IPP printer is off"})
            data = read_raw_body(self)
            if len(data) > MAX_PDF:
                return self._send(413, {"ok": False,
                                        "error": "IPP request too large"})
            resp = ipp_handle(data, self._client_ip())
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
                     printer=CFG.get("printer") or "(default)",
                     details="send portal upload (%d KB)"
                             % (len(raw_pdf) // 1024))
            log("[SEND] '%s' uploaded (%d KB) -> job #%d%s"
                % (fname, len(raw_pdf) // 1024, job,
                   " (already in the queue)" if dup else ""))
            return self._send(200, {"ok": True, "job_id": job})

        # POST /restart - v2.8: relaunch the hub as a NEW process and exit
        # this one (same as the tray menu Restart). The new process waits
        # for this one to release the port (ADVPRINT_RESTART=1).
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
                n = 0
                for j in db_list(limit=500, status="queued"):
                    db_update(j["id"], status="canceled",
                              error="queue cleared by user")
                    n += 1
                db_audit("queue.cleared", ip=ip, site=site, details="%d jobs" % n)
                log("[QUEUE] cleared %d pending job(s)" % n)
                return self._send(200, {"ok": True, "canceled": n})
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

        # POST /config - update v2.0 settings at runtime (persists)
        if route == "/config":
            changed = []
            for key, val in (body or {}).items():
                if key == "token":
                    return self._send(400, {
                        "ok": False,
                        "error": "use POST /token/rotate to change the token"})
                if key not in CONFIG_TYPES:
                    return self._send(400, {
                        "ok": False, "error": "unknown config key '%s'" % key})
                want = CONFIG_TYPES[key]
                try:
                    if want is bool:
                        val = bool(val)
                    elif want is int:
                        val = max(0, int(val))
                    elif want is list:
                        if not isinstance(val, list):
                            raise ValueError("must be a list")
                        val = [str(x) for x in val]
                    elif want is dict:
                        if not isinstance(val, dict):
                            raise ValueError("must be an object")
                        val = val
                except (TypeError, ValueError) as e:
                    return self._send(400, {"ok": False,
                                            "error": "config '%s': %s" % (key, e)})
                CFG[key] = val
                changed.append(key)
            if changed:
                disk = {k: CFG[k] for k in CONFIG_KEYS}
                write_config_file(disk)
                db_audit("config.changed", ip=ip, site=site,
                         details=", ".join(changed))
                log("[CONFIG] updated: %s" % ", ".join(changed))
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
                else:
                    lan_listen_stop()
                    lan_info = {"rebound": True, "lan_error": None}
            resp = {"ok": True, "changed": changed,
                    "config": redacted_config()}
            if lan_info:
                resp["lan"] = lan_info
            return self._send(200, resp)

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
                    data, _ = html_to_pdf_bytes(
                        body["page_url"], is_url=True, title=title)
                    # CSS injection applies to html payloads, not live URLs
                    if margin_mm or scale_pct or landscape:
                        log("[PRINT] note: margin/scale/orientation are not"
                            " applied to page_url jobs (server-rendered"
                            " page) - send 'html' instead")
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
            real_status = (db_get(job) or {}).get("status")
            auto_queued = (not queue_mode and not run_at and
                           dup is None and real_status == "queued")
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

        # POST /queue/shift - v2.1: move queued/held/failed jobs to ANOTHER
        # PC's hub over the LAN ("individual shift" via ids, "full shift"
        # via scope=all). Queue on/off stays /queue/pause + /queue/resume.
        if route == "/queue/shift":
            target = str(body.get("target") or "").strip().rstrip("/")
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
                    if (p.get("url") or "").rstrip("/") == target:
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

def probe_peers(timeout=3):
    """Health-probe every configured peer hub; dead ones are reported
    (and later skipped by the forwarding logic). Cached 15 s."""
    peers = CFG.get("peer_hubs") or []
    if not peers:
        return []
    if time.time() - _PEER_CACHE["t"] < 15 and _PEER_CACHE["v"]:
        return _PEER_CACHE["v"]
    out = []
    for peer in peers:
        url = (peer.get("url") or "").rstrip("/")
        entry = {"url": url, "alive": False, "version": None,
                 "latency_ms": None}
        if url:
            t0 = time.time()
            try:
                req = urllib.request.Request(
                    url + "/health",
                    headers={"X-AdvPrint-Token": peer.get("token") or "",
                             "User-Agent": "AdvPrintPro/%s" % VERSION})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
                entry["alive"] = True
                entry["version"] = data.get("version")
                entry["latency_ms"] = int((time.time() - t0) * 1000)
            except Exception as e:
                entry["error"] = str(e)[:100]
        out.append(entry)
    _PEER_CACHE["t"] = time.time()
    _PEER_CACHE["v"] = out
    return out

def _log_tail(lines=40):
    path = os.path.join(CFG["data_dir"], "hub.log")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-lines:]
    except OSError:
        return []

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
  .panel{background:var(--card);border:1px solid #e2e8f0;border-radius:12px;
         padding:6px 12px;overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{color:var(--mut);text-align:left;font-weight:600;padding:7px 8px;
     border-bottom:1px solid #eef2f7}
  td{padding:7px 8px;border-bottom:1px solid #f4f7fb;white-space:nowrap}
  .st{font-size:11px;font-weight:700;padding:2px 8px;border-radius:9px}
  .st.printed,.st.queued,.ready{background:#dcfce7;color:#166534}
  .st.printing,.st.forwarded{background:#dbeafe;color:#1e40af}
  .st.saved,.st.scheduled{background:#fef9c3;color:#854d0e}
  .st.held{background:#ffedd5;color:#9a3412}
  .st.dead,.st.failed,.st.canceled,.offline,.paper-out,.error{background:#fee2e2;color:#991b1b}
  .ready{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:9px}
  .offline,.paper-out,.error{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:9px}
  button{border:1px solid #dbe2ee;background:#fff;border-radius:7px;
         padding:5px 10px;font:600 12px "Segoe UI",system-ui;cursor:pointer}
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
  setTimeout(()=>{loadLan();refresh();},400);
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
refresh();loadHistory();loadLan();loadDebug();loadDz();
setInterval(refresh,5000);setInterval(loadHistory,10000);
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
_LAN_HTTPD = None                 # the second (LAN) listener, or None
_LAN_THREAD = None
_LAN_BIND_IP = None               # LAN IP the second listener is on

def lan_listen_active():
    """True while the dedicated LAN listener is serving."""
    return _LAN_HTTPD is not None

def lan_listen_start():
    """Bind the LAN listener to this PC's CURRENT LAN IP. Returns an
    error string, or None on success. Never touches the loopback hub:
    if this bind fails, 127.0.0.1 keeps answering."""
    global _LAN_HTTPD, _LAN_THREAD, _LAN_BIND_IP, BOUND_LAN
    if _LAN_HTTPD is not None:
        return None
    if _env("HOST"):
        # Power user pinned the main bind with ADVPRINT_HOST (e.g.
        # 0.0.0.0): that listener already covers the LAN - do not open
        # a second one, trust the boot-time BOUND_LAN value.
        return None
    ip = lan_ip()
    if ip in ("127.0.0.1", "::1", ""):
        return ("no LAN IP found (Wi-Fi/Ethernet disconnected?) - "
                "connect to the network and toggle LAN sharing again")
    port = int(CFG.get("port", 9235))
    try:
        httpd = HubServer((ip, port), Handler)
    except OSError as e:
        return ("cannot bind %s:%d (%s) - another program may own the "
                "port, or the network card just changed" % (ip, port, e))
    except Exception as e:
        return "cannot bind %s:%d (%s)" % (ip, port, e)
    httpd.daemon_threads = True
    _LAN_HTTPD = httpd
    _LAN_BIND_IP = ip
    _LAN_THREAD = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.2},
        name="advprint-lan", daemon=True)
    _LAN_THREAD.start()
    BOUND_LAN = True
    log("[LAN] listener UP on http://%s:%d - other PCs and phones can "
        "print now (the loopback listener was never touched)"
        % (ip, port))
    try:
        build_health_snapshot()
    except Exception:
        pass
    return None

def lan_listen_stop():
    """Stop the dedicated LAN listener (loopback hub keeps running)."""
    global _LAN_HTTPD, _LAN_THREAD, _LAN_BIND_IP, BOUND_LAN
    httpd = _LAN_HTTPD
    if httpd is None:
        return
    _LAN_HTTPD = None
    _LAN_THREAD = None
    _LAN_BIND_IP = None
    if not _env("HOST"):
        BOUND_LAN = False
    def _closer():
        try:
            httpd.shutdown()          # exits serve_forever (its own thread)
        except Exception:
            pass
        try:
            httpd.server_close()      # release the port
        except Exception:
            pass
        log("[LAN] listener stopped - this PC only (127.0.0.1) again")
    threading.Thread(target=_closer, daemon=True,
                     name="advprint-lan-stop").start()
    try:
        build_health_snapshot()
    except Exception:
        pass

def lan_listen_ensure():
    """Health-refresher hook (runs every 3 s): follow config changes
    AND DHCP IP changes without any user action."""
    if _env("HOST"):
        return
    want = bool(CFG.get("share_lan"))
    if want and _LAN_HTTPD is None:
        err = lan_listen_start()
        if err:
            log("[LAN] auto-start: %s" % err)
    elif want and _LAN_BIND_IP and _LAN_BIND_IP != lan_ip():
        # DHCP handed this PC a new address - follow it automatically.
        log("[LAN] LAN IP changed %s -> %s - rebinding the LAN listener"
            % (_LAN_BIND_IP, lan_ip()))
        lan_listen_stop()
        lan_listen_start()
    elif not want and _LAN_HTTPD is not None:
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

_RAW_TCP = None                   # the RAW JetDirect listener, or None
_RAW_THREAD = None
_RAW_BIND_IP = None

IPP_VERSION_STR = "1.1"
IPP_MIME = "application/ipp"

def _ipp_attr(tag, name, value):
    """Encode one IPP attribute (value-tag, name, value)."""
    nb = name.encode("utf-8") if isinstance(name, str) else name
    vb = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return (bytes([tag]) + len(nb).to_bytes(2, "big") + nb +
            len(vb).to_bytes(2, "big") + vb)

def _ipp_additional_attr(tag, value):
    """Additional-value entry: empty name (per RFC 8010)."""
    return _ipp_attr(tag, "", value)

def _ipp_group(tag, attrs):
    return bytes([tag]) + b"".join(attrs)

def _ipp_parse(data):
    """Parse an IPP request far enough to route it. Returns
    (ver_tuple, operation_id, request_id, op_attrs, document_bytes).
    op_attrs is a dict of the operation-attribute names (first value
    wins)."""
    if len(data) < 8:
        raise ValueError("IPP request too short")
    ver = (data[0], data[1])
    op = int.from_bytes(data[2:4], "big")
    rid = int.from_bytes(data[4:8], "big")
    i = 8
    op_attrs = {}
    doc = b""
    group = None
    name = b""
    value_tag = 0
    while i < len(data):
        b = data[i]
        if b == 0x03:                       # end-of-attributes tag
            doc = data[i + 1:]
            break
        if b in (0x00, 0x01, 0x02, 0x04, 0x05):
            group = b                       # begOf attribute group
            i += 1
            continue
        # value-tag + name + value triple
        value_tag = b
        nl = int.from_bytes(data[i + 1:i + 3], "big")
        i += 3
        name = data[i:i + nl]
        i += nl
        vl = int.from_bytes(data[i:i + 2], "big")
        i += 2
        value = data[i:i + vl]
        i += vl
        if group == 0x01 and nl and value_tag not in (0x35, 0x36):
            # operation attributes (skip charset/language entries)
            key = name.decode("utf-8", "replace")
            if key not in op_attrs:
                op_attrs[key] = value.decode("utf-8", "replace")
    return ver, op, rid, op_attrs, doc

def _ipp_header(ver, status, rid):
    if isinstance(ver, (tuple, list)):
        maj, mnr = int(ver[0]), int(ver[1])
    else:
        maj, mnr = 1, 1
    return (bytes([maj, mnr]) + int(status).to_bytes(2, "big") +
            int(rid).to_bytes(4, "big"))

def _ipp_response(ver, status, rid, groups):
    head = _ipp_header(ver, status, rid)
    opg = _ipp_group(0x01, [
        _ipp_attr(0x47, "attributes-charset", "utf-8"),
        _ipp_attr(0x48, "attributes-natural-language", "en"),
    ])
    return head + opg + b"".join(groups) + b"\x03"

def _ipp_printer_group():
    """Printer-attributes group for Get-Printer-Attributes - enough for
    the Microsoft IPP Class Driver and common phone print services."""
    host = socket.gethostname()
    try:
        pending = int(db_count_pending())
    except Exception:
        pending = 0
    attrs = [
        _ipp_attr(0x45, "printer-state", "3"),              # enum: idle
        _ipp_attr(0x44, "printer-state-reasons", "none"),   # keyword
        _ipp_attr(0x41, "printer-name", host),              # name w/o lang
        _ipp_attr(0x41, "printer-make-and-model",
                  "AdvPrint Pro %s (virtual)" % VERSION),
        _ipp_attr(0x44, "ipp-versions-supported", IPP_VERSION_STR),
        _ipp_attr(0x23, "printer-is-accepting-jobs", b"\x01"),  # true
        _ipp_attr(0x22, "queued-job-count",
                  int(pending).to_bytes(4, "big", signed=True)),
        _ipp_attr(0x22, "copies-supported",
                  (1).to_bytes(4, "big", signed=True) +
                  (99).to_bytes(4, "big", signed=True)),    # range 1-99
    ]
    # document formats: PDF first (phones + Windows both send PDF)
    fmts = [_ipp_attr(0x49, "document-format-supported", "application/pdf"),
            _ipp_additional_attr(0x44, "image/jpeg"),
            _ipp_additional_attr(0x44, "application/octet-stream")]
    return _ipp_group(0x04, attrs + fmts)

def _ipp_job_group(job_id, state=3):
    return _ipp_group(0x02, [
        _ipp_attr(0x21, "job-id", int(job_id).to_bytes(4, "big", signed=True)),
        _ipp_attr(0x45, "job-state", str(state)),           # enum
        _ipp_attr(0x44, "job-state-reasons", "job-queued" if state == 3
                  else "job-completed-successfully"),
    ])

def ipp_handle(data, ip):
    """Top-level IPP request entry. Returns the IPP response bytes.
    Audit + logging included; every accepted job goes through the
    same pipeline as the Send portal."""
    try:
        ver, op, rid, op_attrs, doc = _ipp_parse(data)
    except Exception as e:
        return _ipp_response((1, 1), 0x0400, 0, [])         # bad-request
    if op == 0x000B:                                        # Get-Printer-Attributes
        return _ipp_response(ver, 0x0000, rid, [_ipp_printer_group()])
    if op in (0x0002, 0x0004):                              # Print-Job / Validate-Job
        if op == 0x0004:
            return _ipp_response(ver, 0x0000, rid, [_ipp_job_group(0)])
        if not doc:
            return _ipp_response(ver, 0x0400, rid, [])
        title = (op_attrs.get("job-name") or
                 op_attrs.get("requesting-user-name") or "IPP job")
        try:
            job_id, kind = route_print_payload(doc, str(title)[:90], ip,
                                               source="ipp")
        except ValueError as e:
            log("[IPP] rejected from %s: %s" % (ip, e))
            return _ipp_response(ver, 0x040B, rid, [])      # format not supported
        except Exception as e:
            log("[IPP] print failed from %s: %s" % (ip, e))
            return _ipp_response(ver, 0x0500, rid, [])      # server error
        log("[IPP] job from %s (%d KB, %s) -> #%d" %
            (ip, len(doc) // 1024, kind, job_id))
        return _ipp_response(ver, 0x0000, rid, [_ipp_job_group(job_id)])
    # every other operation: not implemented
    return _ipp_response(ver, 0x040F, rid, [])              # operation-not-supported

def route_print_payload(data, title, ip, source="raw9100"):
    """Shared routing for IPP Print-Job and the RAW 9100 listener.
    Returns (job_id, kind). Raises ValueError for unsupported data."""
    if not data:
        raise ValueError("empty print payload")
    if len(data) > MAX_PDF:
        raise ValueError("payload too large - the limit is %d MB"
                         % (MAX_PDF // (1024 * 1024)))
    if data.startswith(b"%PDF"):
        job, dup = enqueue_print("a4", title[:90], data, source=source,
                                 dedupe=False, origin_ip=ip)
        db_audit("print", job_id=job, ip=ip, site="lan",
                 printer=CFG.get("printer") or "(default)",
                 details="%s PDF payload (%d KB)%s"
                         % (source, len(data) // 1024,
                            " (duplicate held)" if dup else ""))
        return job, "pdf"
    if data[:3] == b"\xff\xd8\xff":
        try:
            pdf, _name = image_pdf_bytes(data, title=title)
        except Exception as e:
            raise ValueError("bad JPEG: %s" % e)
        job, dup = enqueue_print("a4", title[:90], pdf, source=source,
                                 dedupe=False, origin_ip=ip)
        db_audit("print", job_id=job, ip=ip, site="lan",
                 printer=CFG.get("printer") or "(default)",
                 details="%s JPEG payload (%d KB)" % (source,
                                                      len(data) // 1024))
        return job, "jpeg"
    # everything below is printer-language passthrough (winspool RAW /
    # lp -o raw): PCL, PostScript, ZPL, ESC/POS...
    try:
        print_raw(data, job_id=None, title=title[:60])
    except Exception as e:
        db_audit("print.failed", ip=ip, site="lan",
                 details="%s raw passthrough failed: %s" % (source, e))
        raise ValueError("raw passthrough failed: %s" % e)
    db_audit("print", job_id=0, ip=ip, site="lan",
             printer=CFG.get("printer") or "(default)",
             details="%s raw passthrough %s (%d KB)"
                     % (source, _sniff_lang(data), len(data) // 1024))
    log("[RAW9100] %s payload from %s (%d KB) -> %s"
        % (_sniff_lang(data), ip, len(data) // 1024,
           CFG.get("printer") or "(default)"))
    return 0, _sniff_lang(data)

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

def _raw_conn_handler(conn, addr):
    """One JetDirect connection: read until the client closes or an
    idle timeout hits, then route the payload."""
    ip = addr[0] if isinstance(addr, tuple) else "unknown"
    try:
        conn.settimeout(15)
        chunks = []
        total = 0
        while total <= MAX_PDF:
            try:
                b = conn.recv(65536)
            except socket.timeout:
                break
            if not b:
                break
            chunks.append(b)
            total += len(b)
        data = b"".join(chunks)
        if not data:
            return
        try:
            route_print_payload(data, "RAW print", ip, source="raw9100")
        except Exception as e:
            log("[RAW9100] rejected %s: %s" % (ip, e))
    finally:
        try:
            conn.close()
        except OSError:
            pass

def raw_listen_active():
    return _RAW_TCP is not None

def raw_listen_start():
    """Bind the RAW JetDirect listener to this PC's LAN IP (never
    0.0.0.0). Returns an error string or None."""
    global _RAW_TCP, _RAW_THREAD, _RAW_BIND_IP
    port = int(CFG.get("raw_printer_port") or 0)
    if port <= 0 or not CFG.get("share_lan"):
        return None
    if _RAW_TCP is not None:
        return None
    ip = lan_ip()
    if ip in ("127.0.0.1", "::1", ""):
        return None                                  # no LAN - stay off
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((ip, port))
        srv.listen(4)
    except OSError as e:
        try:
            srv.close()
        except Exception:
            pass
        return "cannot bind RAW %s:%d (%s)" % (ip, port, e)
    _RAW_TCP = srv
    _RAW_BIND_IP = ip

    def _accept_loop():
        while _RAW_TCP is srv:
            try:
                conn, addr = srv.accept()
            except OSError:
                break
            threading.Thread(target=_raw_conn_handler, args=(conn, addr),
                             daemon=True,
                             name="advprint-raw9100").start()
        try:
            srv.close()
        except OSError:
            pass

    _RAW_THREAD = threading.Thread(target=_accept_loop, daemon=True,
                                   name="advprint-raw-accept")
    _RAW_THREAD.start()
    log("[RAW9100] JetDirect printer port UP on %s:%d - other PCs can add"
        " this PC as a Standard TCP/IP port printer" % (ip, port))
    return None

def raw_listen_stop():
    global _RAW_TCP, _RAW_THREAD, _RAW_BIND_IP
    srv = _RAW_TCP
    if srv is None:
        return
    _RAW_TCP = None
    _RAW_THREAD = None
    _RAW_BIND_IP = None
    try:
        srv.close()          # accept loop exits on the OSError
    except OSError:
        pass
    log("[RAW9100] printer port stopped")

def raw_listen_ensure():
    """Health-refresher hook (runs every 3 s): start/stop/rebind the
    RAW listener following share_lan + raw_printer_port + DHCP."""
    want = bool(CFG.get("share_lan")) and \
        int(CFG.get("raw_printer_port") or 0) > 0
    if want and _RAW_TCP is None:
        err = raw_listen_start()
        if err:
            log("[RAW9100] auto-start: %s" % err)
    elif not want and _RAW_TCP is not None:
        raw_listen_stop()
    elif want and _RAW_BIND_IP and _RAW_BIND_IP != lan_ip():
        raw_listen_stop()
        raw_listen_start()

def ipp_printer_enabled():
    return bool(CFG.get("ipp_printer", True))


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


def connect_page_html(token, name):
    host = socket.gethostname()
    peer_url = "http://%s:%d" % (lan_ip(), CFG["port"])
    who = str(name or host)[:60]
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
</style></head><body><div class="box">
 <h1>Connect to &#8220;@@WHO@@&#8221;'s printer hub?</h1>
 <p>The PC that showed you this link shares its printers over the
    local network with <b>AdvPrint Pro</b>. Clicking the button below
    adds it to YOUR PC's printer-hub list (peer_hubs) - afterwards you
    can send print jobs to its printers from your own dashboard.</p>
 <div class="kv">Peer PC: <b>@@WHO@@</b><br>
  Hub URL: <span class="mono">@@URL@@</span></div>
 <form method="post" action="http://127.0.0.1:@@PORT@@/peer-connect">
  <input type="hidden" name="url" value="@@URL@@">
  <input type="hidden" name="token" value="@@TOK@@">
  <input type="hidden" name="name" value="@@WHO@@">
  <input type="hidden" name="confirm" value="1">
  <button type="submit">Add &#8220;@@WHO@@&#8221; as a LAN print peer</button>
 </form>
 <p class="warn">Nothing is sent to the internet - this only writes the
    peer entry into your local AdvPrint Pro config. You can remove it
    any time from your dashboard's LAN card (or config.json).</p>
 <details><summary>Manual alternative (if your hub runs on another port)</summary>
  <p>Paste this into <span class="mono">peer_hubs</span> in your
     <span class="mono">config.json</span> and restart the hub:</p>
  <pre>[{"url": "@@URL@@",
 "token": "@@TOK@@",
 "name": "@@WHO@"}]</pre>
 </details>
 <div class="brand">AdvPrint Pro v@@VERSION@@ - by Bit Dream IT -
   100% local - no cloud, no tracking</div>
</div></body></html>""" \
        .replace("@@WHO@@", esc_html(who)) \
        .replace("@@URL@@", esc_html(peer_url)) \
        .replace("@@TOK@@", quote(token or "")) \
        .replace("@@PORT@@", str(DEFAULT_PEER_PORT)) \
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
    log("Dashboard     -> http://127.0.0.1:%d/dashboard?token=%s" % (CFG["port"], CFG["token"]))
    if DEFAULT_TOKEN_WARNING:
        log("[SECURITY] WARNING: the default token is still in use!"
            " Change it with:  %s" % cli_cmd("token-rotate"))
    log("Open the extension popup and click Connect. Press Ctrl+C to stop.")
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

