#!/usr/bin/env bash
# ============================================================
# AdvPrint Pro - build EVERYTHING from this repo, no prebuilt
# binaries needed.  by Bit Dream IT - Innovative Healthcare Solutions
#
#   bash scripts/build-all.sh
#
# Produces in dist/:
#   AdvPrint-Pro.crx                      signed extension (CRX3, repo key)
#   AdvPrint-Pro-Extension-<V>.zip        unpacked extension zip (store/dev)
#   AdvPrint-Pro-Setup-<V>.exe            Windows installer (NSIS, staged)
#   advprint-pro_<V>_all.deb              Linux DEB (systemd user service)
#   SHA256SUMS-<V>.txt                    checksums of everything
#
# Requirements: python3, zip, dpkg-deb (any Linux), and for the EXE:
#   NSIS 3.x (makensis) - Debian/Ubuntu: sudo apt-get install nsis
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

V="$(sed -n 's/^AdvPrint Pro (Advanced Printer) \([0-9.]*\) .*/\1/p' VERSION.txt | head -1)"
[ -n "$V" ] || { echo "cannot parse version from VERSION.txt"; exit 1; }
echo "== AdvPrint Pro build-all: version $V =="

DIST="$ROOT/dist"
STAGE="$ROOT/installer/stage"
rm -rf "$DIST" "$STAGE"
mkdir -p "$DIST" "$STAGE/hub/extension" "$STAGE/install" "$STAGE/docs"

# ---------- 1) signed CRX3 (repo extension + repo signing key) ----------
echo "-- CRX3"
python3 tool/crx3.py pack extension extension-signing/advprint-printer.pem \
        "$DIST/AdvPrint-Pro.crx"
cp "$DIST/AdvPrint-Pro.crx" "$STAGE/hub/extension/AdvPrint-Pro.crx"
python3 tool/crx3.py info "$DIST/AdvPrint-Pro.crx" | head -4 || true

# ---------- 2) unpacked extension zip (Web-store upload / dev load) ----------
echo "-- extension zip"
( cd extension && zip -qr "$DIST/AdvPrint-Pro-Extension-$V.zip" . )

# ---------- 3) NSIS stage (hub + installers + runtime + docs) ----------
echo "-- NSIS stage"
cp tool/windows/portable/hub/*.py "$STAGE/hub/" 2>/dev/null || true
cp tool/windows/portable/hub/*.ico "$STAGE/hub/" 2>/dev/null || true
cp tool/windows/portable/hub/*.html "$STAGE/hub/" 2>/dev/null || true
mkdir -p "$STAGE/hub/service"
cp tool/windows/portable/hub/service/*.cs "$STAGE/hub/service/" 2>/dev/null || true
cp tool/windows/portable/install/install-windows.bat \
   tool/windows/portable/install/UNINSTALL-WINDOWS.bat \
   tool/windows/portable/install/START-ADVPRINT.vbs \
   tool/windows/portable/install/START-CONSOLE.vbs \
   tool/windows/portable/install/INSTALL-WINDOWS-SERVICE.bat \
   tool/windows/portable/install/REMOVE-WINDOWS-SERVICE.bat \
   tool/windows/portable/install/service-install.ps1 \
   tool/windows/portable/install/service-remove.ps1 \
   tool/windows/portable/install/hub-stop.ps1 \
   "$STAGE/install/"
cp docs/AdvPrint-Pro-Full-Guide.html "$STAGE/docs/"
cp README.md "$STAGE/README.md"
RUNTIME="tool/windows/portable/installer/runtime"
if [ -d "$RUNTIME" ]; then
  echo "   embedding Python runtime ($(du -sh "$RUNTIME" | cut -f1))..."
  mkdir -p "$STAGE/runtime"
  cp -a "$RUNTIME/." "$STAGE/runtime/"
else
  echo "   WARNING: $RUNTIME missing - Setup EXE would need system Python"
fi

# ---------- 4) DEB ----------
echo "-- DEB"
DEBTMP="$DIST/deb-build/advprint-pro_$V"
rm -rf "$DIST/deb-build"; mkdir -p "$DEBTMP"
cp -a installer/deb/DEBIAN "$DEBTMP/DEBIAN"
sed -i "s/^Version: .*/Version: $V/" "$DEBTMP/DEBIAN/control"
mkdir -p "$DEBTMP/opt/advprint/hub/extension" \
         "$DEBTMP/opt/advprint/hub/service" \
         "$DEBTMP/etc/xdg/autostart" "$DEBTMP/usr/bin" \
         "$DEBTMP/usr/lib/systemd/user"
cp tool/unix/hub/advprint.py "$DEBTMP/opt/advprint/hub/advprint.py"
cp tool/windows/portable/hub/tool.py \
   tool/windows/portable/hub/tray_windows.py \
   tool/windows/portable/hub/service_main.py \
   tool/windows/portable/hub/advprint.ico \
   "$DEBTMP/opt/advprint/hub/"
# v3.1.2: THE ONE UI console + the gui_app window launcher
[ -e tool/unix/hub/console.html ] && cp tool/unix/hub/console.html "$DEBTMP/opt/advprint/hub/"
[ -e tool/unix/hub/gui_app.py ] && cp tool/unix/hub/gui_app.py "$DEBTMP/opt/advprint/hub/"
for f in tool/unix/hub/*.html; do
  [ -e "$f" ] && cp "$f" "$DEBTMP/opt/advprint/hub/"
done
cp "$DIST/AdvPrint-Pro.crx" "$DEBTMP/opt/advprint/hub/extension/AdvPrint-Pro.crx"
cp tool/windows/portable/hub/service/*.cs "$DEBTMP/opt/advprint/hub/service/" 2>/dev/null || true
cp installer/deb/data/advprint.desktop "$DEBTMP/etc/xdg/autostart/advprint.desktop"
install -m 755 installer/deb/data/advprint-launcher "$DEBTMP/usr/bin/advprint"
install -m 755 installer/deb/data/advprint-start "$DEBTMP/usr/bin/advprint-start"
install -m 644 installer/deb/data/advprint.service \
        "$DEBTMP/usr/lib/systemd/user/advprint.service"
chmod +x "$DEBTMP/DEBIAN/postinst" "$DEBTMP/DEBIAN/prerm"
dpkg-deb --build --root-owner-group "$DEBTMP" \
         "$DIST/advprint-pro_${V}_all.deb"
rm -rf "$DIST/deb-build"

# ---------- 5) NSIS Setup EXE ----------
# makensis is looked up on PATH; the sandbox/local prefix pattern:
#   apt-get download nsis nsis-common && dpkg -x nsis*.deb ~/nsis-root
#   NSISDIR=~/nsis-root/usr/share/nsis ~/nsis-root/usr/bin/makensis setup.nsi
if command -v makensis >/dev/null 2>&1; then
  MK="$(command -v makensis)"
  MKENV=()
elif [ -x "$HOME/nsis-root/usr/bin/makensis" ]; then
  MK="$HOME/nsis-root/usr/bin/makensis"
  MKENV=("NSISDIR=$HOME/nsis-root/usr/share/nsis"
         "LD_LIBRARY_PATH=$HOME/nsis-root/usr/lib/x86_64-linux-gnu")
  echo "-- NSIS Setup EXE (local prefix: $MK)"
else
  MK=""
  echo "!! makensis NOT installed - stage/ is ready; install NSIS"
  echo "   (sudo apt-get install nsis) and run:"
  echo "   ( cd installer && makensis setup.nsi )"
fi
if [ -n "$MK" ]; then
  ( cd installer && env "${MKENV[@]}" "$MK" -V2 setup.nsi )
  ls -la "$DIST/AdvPrint-Pro-Setup-$V.exe"
fi

# ---------- 6) SHA256SUMS ----------
echo "-- SHA256SUMS"
# v3.2.4: ONE pass - all four artifacts (the EXE line was lost when the
# second sha256sum overwrote the first; the user hit this on 3.2.2)
SUMS="AdvPrint-Pro.crx AdvPrint-Pro-Extension-$V.zip advprint-pro_${V}_all.deb"
[ -f "AdvPrint-Pro-Setup-$V.exe" ] && SUMS="$SUMS AdvPrint-Pro-Setup-$V.exe"
( cd "$DIST" && sha256sum $SUMS > "SHA256SUMS-$V.txt" )

echo "== DONE - artifacts in dist/ =="
ls -la "$DIST"
