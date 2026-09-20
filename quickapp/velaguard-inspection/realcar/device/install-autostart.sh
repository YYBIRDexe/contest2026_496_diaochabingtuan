#!/usr/bin/env bash
# ============================================================
# install-autostart.sh -- run on the U2P box.
#
# Adds ONE xdg autostart entry: start the real-car patrol executor, then the
# E5 kiosk demo. Idempotent; --remove takes it back out.
#
# Why xdg autostart and not systemd: the patrol controller is a user process
# that must follow the same DISPLAY/X session as the kiosk. Adding a system
# unit would need sudo, and it would start before X exists.
# ============================================================
set -u

PORTAL="$HOME/velaguard/demo"
ENTRY="$HOME/.config/autostart/velaguard-patrol.desktop"

if [ "${1:-}" = "--remove" ]; then
  rm -f "$ENTRY"
  echo "removed $ENTRY"
  exit 0
fi

mkdir -p "$HOME/.config/autostart"
cat > "$ENTRY" <<EOF
[Desktop Entry]
Type=Application
Name=VelaGuard 真车巡检执行器 + E5 演示页
Comment=开机先把车端执行器起在 127.0.0.1:8127，再拉起 E5 全屏演示页
Exec=/bin/bash $PORTAL/start-demo-with-patrol.sh
Path=$PORTAL
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "wrote $ENTRY"
cat "$ENTRY"
