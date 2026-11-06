#!/usr/bin/env bash
# ============================================================
#  AdvPrint Pro - ONE-COMMAND Unix setup  (v1.2.0)
#  Linux + macOS. Zero questions, no sudo needed for the
#  auto-run itself:
#    1. stops any OLD hub still holding port 9235
#    2. checks python3 + CUPS lp
#    3. starts the hub now and health-checks it
#    4. registers AUTO-RUN at every login:
#         Linux + systemd -> systemd --user service
#         macOS           -> LaunchAgent
#         other desktop   -> XDG autostart
#  Undo = bash uninstall-unix.sh (same folder)
# ============================================================
set -u

echo ""
echo "  =============================================="
echo "   AdvPrint Pro  -  one-click setup + auto-run"
echo "  =============================================="
echo ""

BASE="$(cd "$(dirname "$0")/.." && pwd)"
HUB="$BASE/hub/advprint.py"
PORT=9235
OS="$(uname -s)"

# ---- 0) --service: install as a SYSTEM service (Linux + systemd) -------
#   sudo bash install-unix.sh --service
#   Real headless service: starts at boot, survives logout, no desktop.
#   Data dir: /var/lib/advprint.  The normal (no-sudo) user auto-run
#   below stays the default when --service is not passed.
if [ "${1:-}" = "--service" ]; then
    [ "$(id -u)" = "0" ] || { echo "[!] --service needs root:"; echo "    sudo bash install-unix.sh --service"; exit 1; }
    [ "$OS" = "Darwin" ] && { echo "[!] --service is Linux/systemd only (macOS uses the LaunchAgent auto-run)"; exit 1; }
    command -v systemctl >/dev/null 2>&1 || { echo "[!] systemctl not found"; exit 1; }
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    UNIT_SRC=""
    for cand in "$SCRIPT_DIR/advprint.service.system" \
                "$SCRIPT_DIR/../unix/advprint.service.system"; do
        [ -f "$cand" ] && UNIT_SRC="$cand" && break
    done
    [ -n "$UNIT_SRC" ] || { echo "[!] advprint.service.system not found next to this script"; exit 1; }
    PYBIN="$(command -v python3)"
    mkdir -p /var/lib/advprint
    sed -e "s|__PYTHON__|$PYBIN|g" -e "s|__HUB__|$HUB|g" \
        "$UNIT_SRC" > /etc/systemd/system/advprint.service
    chmod 644 /etc/systemd/system/advprint.service
    systemctl daemon-reload
    systemctl enable --now advprint
    sleep 1
    if curl -s "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q version; then
        echo "[OK] AdvPrint Pro SYSTEM service is running (starts at boot, no login needed)"
        echo "     control : systemctl status|stop|restart advprint"
        echo "     data    : /var/lib/advprint   logs: journalctl -u advprint -e"
    else
        echo "[!] Unit installed but the hub did not answer yet - check:"
        echo "     systemctl status advprint ; journalctl -u advprint -e"
    fi
    exit 0
fi

# ---- 1) python3 -------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
    echo "[OK] Python 3: $(python3 --version 2>&1)"
else
    echo "[!] python3 not found."
    echo "    Debian/Ubuntu :  sudo apt install python3"
    echo "    Fedora        :  sudo dnf install python3"
    echo "    macOS         :  brew install python3"
    exit 1
fi

# ---- 2) printing backend (CUPS lp) ------------------------------------
if [ "$OS" = "Darwin" ]; then
    echo "[OK] macOS - lp is built in"
elif command -v lp >/dev/null 2>&1; then
    echo "[OK] CUPS lp found: $(command -v lp)"
else
    echo "[..] lp not found - installing cups-client (one sudo) ..."
    if command -v apt >/dev/null 2>&1; then
        sudo apt install -y cups-client || true
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y cups || true
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm cups || true
    fi
    command -v lp >/dev/null 2>&1 \
        && echo "[OK] CUPS lp installed" \
        || echo "[!] lp still missing - PDF printing will fail until cups-client is installed"
fi

# ---- 3) stop any OLD hub holding the port -----------------------------
if command -v lsof >/dev/null 2>&1; then
    OLD="$(lsof -ti tcp:$PORT -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$OLD" ]; then
        kill -9 $OLD 2>/dev/null || true
        echo "[OK] Old hub on port $PORT stopped"
    else
        echo "[OK] Port $PORT was already free"
    fi
else
    echo "[..] lsof not available - skipped old-hub cleanup"
fi

# ---- 4) start the hub now ---------------------------------------------
mkdir -p "$HOME/.advprint"
( cd "$BASE/hub" && nohup python3 advprint.py serve >> "$HOME/.advprint/hub.out" 2>&1 & )
UP=0
for _ in 1 2 3 4 5 6 7 8; do
    sleep 1
    if curl -s "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q version; then UP=1; break; fi
done
if [ "$UP" = "1" ]; then
    echo "[OK] Hub is running:  http://127.0.0.1:$PORT"
else
    echo "[!] Health check failed - see ~/.advprint/hub.out"
fi

# ---- 5) AUTO-RUN at every login (no questions asked) -------------------
SYSTEMD_UNIT="$HOME/.config/systemd/user/advprint.service"
PLIST="$HOME/Library/LaunchAgents/com.bitdream.it.advprint.plist"
XDG_AUTOSTART="$HOME/.config/autostart/advprint.desktop"
PYBIN="$(command -v python3)"

if [ "$OS" = "Darwin" ]; then
    # macOS: LaunchAgent - starts at login, restarts if it crashes
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.bitdream.it.advprint</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYBIN</string>
        <string>$HUB</string>
        <string>serve</string>
    </array>
    <key>WorkingDirectory</key><string>$BASE/hub</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$HOME/.advprint/hub.out</string>
    <key>StandardErrorPath</key><string>$HOME/.advprint/hub.out</string>
</dict>
</plist>
XML
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    echo "[OK] macOS auto-run installed (LaunchAgent com.bitdream.it.advprint)"
    echo "     control:  launchctl list | grep advprint"

elif command -v systemctl >/dev/null 2>&1 && [ -n "${XDG_RUNTIME_DIR:-}" ] \
     && systemctl --user is-system-running >/dev/null 2>&1; then
    # Linux with a user systemd: NO sudo required at all
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$SYSTEMD_UNIT" <<UNIT
[Unit]
Description=AdvPrint Pro - local print hub

[Service]
ExecStart=$PYBIN $HUB serve
WorkingDirectory=$BASE/hub
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable --now advprint 2>/dev/null || systemctl --user restart advprint
    echo "[OK] Linux auto-run installed (systemd --user service)"
    echo "     control:  systemctl --user status|stop|restart advprint"
    # optional: run even before first login / after logout (one root command)
    if ! loginctl show-user "$USER" 2>/dev/null | grep -q "Linger=yes"; then
        if sudo -n loginctl enable-linger "$USER" 2>/dev/null; then
            echo "[OK] Linger enabled - hub survives logout and runs before login"
        else
            echo "[..] Optional: run 'sudo loginctl enable-linger $USER' once"
            echo "     to keep the hub alive even when you log out."
        fi
    fi

else
    # last resort: XDG autostart (any desktop Linux, no sudo)
    mkdir -p "$HOME/.config/autostart"
    WRAPPER="$HOME/.advprint/start-hub.sh"
    cat > "$WRAPPER" <<SH
#!/bin/sh
exec "$PYBIN" "$HUB" serve
SH
    chmod +x "$WRAPPER"
    cat > "$XDG_AUTOSTART" <<DESK
[Desktop Entry]
Type=Application
Name=AdvPrint Pro
Comment=Silent print bridge - http://127.0.0.1:9235
Exec="$WRAPPER"
Terminal=false
X-GNOME-Autostart-enabled=true
DESK
    echo "[OK] Auto-run installed (XDG autostart - starts with your desktop)"
fi

# ---- 6) v3.0.7: SILENT extension install policy (machine-wide) --------
#  Linux Chrome/Chromium/Edge/Brave read /etc/*/policies/managed/*.json.
#  The force-install entry points the browser at the hub's OWN
#  /extension/updates.xml, so it installs the SIGNED extension silently
#  and auto-updates it on every newer release (no domain requirement
#  on Linux). Written when we are root or have passwordless sudo;
#  otherwise the exact commands are printed for one manual run.
EXTID="likldbkamojokkfdlcjibiljpgbbnohc"
EXTVAL="${EXTID};http://127.0.0.1:9235/extension/updates.xml"
POLJSON="{\"ExtensionInstallForcelist\":[\"${EXTVAL}\"]}"
EXT_DIRS="/etc/opt/chrome/policies/managed /etc/chromium/policies/managed /etc/opt/edge/policies/managed /etc/brave/policies/managed"
WROTE_POLICY=0
if [ "$(id -u)" = "0" ]; then
    for D in $EXT_DIRS; do
        mkdir -p "$D"
        printf '%s\n' "$POLJSON" > "$D/advprint-pro.json"
        chmod 644 "$D/advprint-pro.json"
    done
    WROTE_POLICY=1
    echo "[OK] Extension force-install policy written for Chrome/Chromium/Edge/Brave"
elif sudo -n true 2>/dev/null; then
    for D in $EXT_DIRS; do
        sudo mkdir -p "$D"
        printf '%s\n' "$POLJSON" | sudo tee "$D/advprint-pro.json" >/dev/null
    done
    WROTE_POLICY=1
    echo "[OK] Extension force-install policy written for Chrome/Chromium/Edge/Brave"
else
    echo "[..] Silent extension install (optional, one sudo):"
    echo "     curl -s http://127.0.0.1:9235/extension/info | grep -o '\"forcelist_value.*'"
    echo "     or run:  sudo bash install-unix.sh   (re-run as root writes the policy)"
fi

echo ""
echo "  Setup finished - automatic from now on:"
echo "    hub   : http://127.0.0.1:$PORT      logs: ~/.advprint/hub.out"
if [ "$WROTE_POLICY" = "1" ]; then
    echo "    Chrome: the extension installs SILENTLY via the force-install"
    echo "            policy - restart Chrome once and it is there."
else
    echo "    Chrome: chrome://extensions > Developer mode > Load unpacked"
    echo "            select the extension/ folder, then press Connect"
fi
echo "    uninstall:  bash uninstall-unix.sh (same folder)"
echo ""
