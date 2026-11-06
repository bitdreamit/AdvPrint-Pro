#!/usr/bin/env bash
# ============================================================
#  AdvPrint Pro - Unix uninstall  (v1.2.0)
#  Removes every auto-run registration and stops the hub.
#  Does NOT delete your print data in ~/.advprint
# ============================================================
OS="$(uname -s)"

echo "[..] Removing auto-run registrations ..."

# systemd user service (Linux)
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now advprint 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/advprint.service"
    systemctl --user daemon-reload 2>/dev/null || true
fi

# LaunchAgent (macOS)
PLIST="$HOME/Library/LaunchAgents/com.bitdream.it.advprint.plist"
if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
fi

# XDG autostart (desktop Linux fallback)
rm -f "$HOME/.config/autostart/advprint.desktop"
rm -f "$HOME/.advprint/start-hub.sh"

# stop any hub still running on the port
if command -v lsof >/dev/null 2>&1; then
    PIDS="$(lsof -ti tcp:9235 -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$PIDS" ]; then
        kill -9 $PIDS 2>/dev/null || true
        echo "[OK] Hub on port 9235 stopped"
    fi
fi

# v3.0.7: remove the silent-install policy files (Chrome uninstalls
# the force-installed extension at its next start automatically)
for D in /etc/opt/chrome/policies/managed /etc/chromium/policies/managed \
         /etc/opt/edge/policies/managed /etc/brave/policies/managed; do
    if [ -f "$D/advprint-pro.json" ]; then
        if [ "$(id -u)" = "0" ]; then
            rm -f "$D/advprint-pro.json"
        elif sudo -n rm -f "$D/advprint-pro.json" 2>/dev/null; then
            :
        else
            echo "[..] Remove manually once:  sudo rm -f $D/advprint-pro.json"
        fi
    fi
done

echo "[OK] AdvPrint Pro uninstalled."
echo "     Print data kept in ~/.advprint - delete it manually if you want:"
echo "       rm -rf ~/.advprint"
echo "     Remove the Chrome extension in chrome://extensions"
