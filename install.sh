#!/bin/bash
# Point the HP LaserJet M109-M112 queues at the local PWG-to-IPP bridge.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "This installer needs administrator rights." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
DEST="/Library/Printers/HPM111"
PPD_DST="/Library/Printers/PPDs/Contents/Resources/HP LaserJet M109-M112.ppd"
PLIST_DST="/Library/LaunchDaemons/com.local.hpm111.plist"

mkdir -p "$DEST"
install -m 755 "$ROOT/pwg-bridge.py" "$DEST/pwg-bridge.py"
install -m 644 "$ROOT/HP-LaserJet-M109-M112.ppd" "$PPD_DST"
install -m 644 "$ROOT/com.local.hpm111.plist" "$PLIST_DST"
touch "$DEST/bridge.log"
chmod 644 "$DEST/bridge.log"

launchctl bootout system/com.local.hpm111 >/dev/null 2>&1 || true
# The first backend install may still be holding port 9101 only after this loads.
launchctl bootstrap system "$PLIST_DST"
sleep 1

fix_queue() {
  local name="$1"
  if lpstat -p "$name" >/dev/null 2>&1; then
    cancel -a "$name" >/dev/null 2>&1 || true
    lpadmin -p "$name" -E -v socket://127.0.0.1:9101 -P "$PPD_DST" \
      -D "HP LaserJet M111ca" \
      -o PageSize=A4 \
      -o Resolution=600dpi
    cupsenable "$name" || true
    cupsaccept "$name" || true
    echo "Updated $name"
  fi
}

fix_queue HP_LaserJet_M109_M112_2
fix_queue HP_LaserJet_M109_M112

if lpstat -p HP_LaserJet_M109_M112_2 >/dev/null 2>&1; then
  lpadmin -d HP_LaserJet_M109_M112_2
fi

cupsctl --no-debug-logging >/dev/null 2>&1 || true
echo "Bridge: $(launchctl print system/com.local.hpm111 | awk '/state =/{print; exit}')"
lpstat -d
lpstat -v
