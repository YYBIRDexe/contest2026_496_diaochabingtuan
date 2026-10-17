#!/usr/bin/env bash
# ============================================================
# start-demo-with-patrol.sh -- E5 touch demo + real-car executor together
#
# ASCII ONLY (this file lives on the U2P box; PS 5.1 / bash both read it).
#
# Order matters: the demo page starts polling 127.0.0.1:8127 the moment
# Firefox opens it, so the patrol controller must already be listening.
# Wired into ~/.config/autostart/velaguard-patrol.desktop.
# ============================================================
set -u

PORTAL="$HOME/velaguard/demo"

# 0) Wait for the older autostart entry (velaguard.desktop -> linux/start.sh --serve,
#    the 8123 dashboard) to finish bringing up its Firefox kiosk.
#    run-demo.sh kills *every* firefox before starting, so whoever runs last owns
#    the screen. Sleeping here makes the E5 touch demo the winner deterministically,
#    instead of leaving it to a startup race between two autostart entries.
sleep 20

# 1) real-car executor first
bash "$PORTAL/start-patrol.sh" >> "$PORTAL/autostart.log" 2>&1
sleep 1

# 2) then the kiosk page (this one is slow: it restarts Firefox)
bash "$PORTAL/run-demo.sh" >> "$PORTAL/autostart.log" 2>&1

echo "[$(date '+%F %T')] demo + patrol started" >> "$PORTAL/autostart.log"
