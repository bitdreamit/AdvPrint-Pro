#!/usr/bin/env python3
"""
AdvPrint Pro v3.1.2 - PREMIUM GRAPHICAL WINDOW (gui_app v2)
by Bit Dream IT - Innovative Healthcare Solutions. MIT license.

The native window hosts THE ONE UI: the hub serves the console at
http://127.0.0.1:9235/ui and this process just WRAPS it - one UI,
identical everywhere (window / Chrome / extension options tab).

Backend ladder (first available wins, ~11 MB installer instead of
the old 241 MB PySide6 bundle):

  1. pywebview    - WebView2 (Edge/Chromium) on Windows, WebKit/GTK
                    or Cocoa on Linux/macOS. pip install pywebview
  2. Qt WebEngine - PyQt6 / PyQt5 WebEngineWidgets
  3. GTK WebKit   - python3-gi + WebKit2 (preinstalled on Ubuntu GNOME)
  4. Chrome/Edge  - native "--app=" window (zero extra install)
  5. Browser      - default browser fallback (the console is still
                    THE ONE UI - just without the native frame)

The hub is started automatically when it is not running yet, so the
window never shows a dead page.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

VERSION = "3.1.2"
PORT = 9235
URL = "http://127.0.0.1:%d/ui" % PORT
TITLE = "AdvPrint Pro Console v%s - THE ONE UI" % VERSION
HERE = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.join(HERE, "advprint.py")


def hub_token():
    """Read the hub's current token from its config (best effort)."""
    for base in (os.environ.get("ADVPRINT_DATA") or
                 os.path.expanduser("~/.advprint"), HERE):
        try:
            import json
            with open(os.path.join(base, "config.json")) as fh:
                return str(json.load(fh).get("token") or "")
        except Exception:
            continue
    return ""


def hub_up():
    try:
        s = socket.create_connection(("127.0.0.1", PORT), timeout=0.6)
        s.close()
        return True
    except OSError:
        return False


def hub_reachable():
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/health" % PORT, timeout=2) as r:
            return r.getcode() == 200
    except Exception:
        return False


def start_hub():
    """Start the hub in the background when it is not answering yet."""
    if hub_up():
        return True
    cmd = [sys.executable or "python", HUB, "serve"]
    try:
        if os.name == "nt":
            det = 0x00000008 | 0x00000200          # DETACHED_PROCESS|NEW_GROUP
            subprocess.Popen(cmd, creationflags=det,
                             cwd=HERE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
    except Exception as e:
        print("[gui] cannot start hub:", e)
        return False
    for _ in range(40):                            # ~10 s
        time.sleep(0.25)
        if hub_up():
            return True
    return False


def page_url():
    tok = hub_token()
    return URL + ("?token=" + urllib.parse.quote(tok) if tok else "")


# ------------------------------------------------------------
# 1) pywebview (WebView2 / WebKitGTK / Cocoa)
# ------------------------------------------------------------
def run_pywebview(url):
    import webview                                   # noqa
    w = webview.create_window(
        TITLE, url, width=1280, height=840, min_size=(980, 640),
        background_color="#1e3a8a")
    webview.start(http_server=False)
    return True


# ------------------------------------------------------------
# 2) Qt WebEngine (PyQt6 / PyQt5)
# ------------------------------------------------------------
def run_qt(url):
    try:
        from PyQt6.QtCore import QUrl               # noqa
        from PyQt6.QtWidgets import QApplication    # noqa
        from PyQt6.QtWebEngineWidgets import QWebEngineView   # noqa
        app = QApplication(sys.argv)
        v = QWebEngineView()
        v.setWindowTitle(TITLE)
        v.resize(1280, 840)
        v.load(QUrl(url))
        v.show()
        app.exec()
        return True
    except Exception:
        try:
            from PyQt5.QtCore import QUrl               # noqa
            from PyQt5.QtWidgets import QApplication    # noqa
            from PyQt5.QtWebEngineWidgets import QWebEngineView   # noqa
            app = QApplication(sys.argv)
            v = QWebEngineView()
            v.setWindowTitle(TITLE)
            v.resize(1280, 840)
            v.load(QUrl(url))
            v.show()
            app.exec()
            return True
        except Exception:
            return False


# ------------------------------------------------------------
# 3) GTK + WebKit2 (python3-gi, preinstalled on Ubuntu GNOME)
# ------------------------------------------------------------
def run_gtk(url):
    try:
        import gi                                   # noqa
        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.0")
        from gi.repository import Gtk, WebKit2      # noqa
        win = Gtk.Window(title=TITLE)
        win.set_default_size(1280, 840)
        view = WebKit2.WebView()
        view.load_uri(url)
        win.add(view)
        win.show_all()
        win.connect("delete-event", Gtk.main_quit)
        Gtk.main()
        return True
    except Exception:
        return False


# ------------------------------------------------------------
# 4) Chrome / Edge --app window (zero install, looks native)
# ------------------------------------------------------------
def find_app_browser():
    cands = []
    if os.name == "nt":
        for root in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     os.environ.get("PROGRAMFILES(X86)",
                                    r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA",
                                    os.path.expanduser("~") +
                                    r"\AppData\Local")):
            for rel in (r"Google\Chrome\Application\chrome.exe",
                        r"Microsoft\Edge\Application\msedge.exe",
                        r"Chromium\Application\chrome.exe"):
                cands.append(os.path.join(root, rel))
    else:
        import shutil
        for name in ("google-chrome", "microsoft-edge", "microsoft-edge-stable",
                     "chromium", "chromium-browser", "brave-browser"):
            p = shutil.which(name)
            if p:
                cands.append(p)
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def run_browser_app(url):
    exe = find_app_browser()
    if not exe:
        return False
    args = [exe, "--app=" + url,
            "--window-size=1280,840",
            "--user-data-dir=" + os.path.join(
                os.path.expanduser("~"), ".advprint", "app-window"),
            "--no-first-run", "--no-default-browser-check"]
    try:
        if os.name == "nt":
            det = 0x00000008
            subprocess.Popen(args, creationflags=det)
        else:
            subprocess.Popen(args, start_new_session=True)
        return True
    except Exception:
        return False


def main():
    url = page_url()
    if not start_hub():
        print("[gui] hub not answering on port %d - opening the page"
              " anyway (it shows an offline card + retry)." % PORT)
    else:
        # give the HTTP handler one extra beat so /ui answers instantly
        for _ in range(8):
            if hub_reachable():
                break
            time.sleep(0.25)

    ladder = [("pywebview", run_pywebview),
              ("Qt WebEngine", run_qt),
              ("GTK WebKit", run_gtk),
              ("Chrome/Edge app window", run_browser_app)]
    for name, fn in ladder:
        try:
            if fn(url):
                print("[gui] backend: %s -> %s" % (name, url))
                return 0
        except Exception as e:
            print("[gui] backend %s failed: %s" % (name, e))
    # 5) default browser - still THE ONE UI
    print("[gui] no native backend found - opening the default browser")
    webbrowser.open(url)
    print("[gui] tip: pip install pywebview for the real native window")
    return 0


if __name__ == "__main__":
    sys.exit(main())
