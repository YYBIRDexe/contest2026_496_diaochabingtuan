#!/usr/bin/env bash
# ============================================================
# start-patrol.sh -- VelaGuard real-car patrol executor (device side)
#
# ASCII ONLY. This file is copied to the U2P box and run there.
#
# What it does: brings up patrol_controller.py on 127.0.0.1:8127,
# the service that the E5 demo page's "开始巡检" button calls.
#
#   bash ~/velaguard/demo/start-patrol.sh            # start + health check
#   bash ~/velaguard/demo/start-patrol.sh --status    # is it up?
#   bash ~/velaguard/demo/start-patrol.sh --stop      # stop + send STOP to cars
#   bash ~/velaguard/demo/start-patrol.sh --selftest  # validate routes only
#   bash ~/velaguard/demo/start-patrol.sh --log       # last 40 log lines
# ============================================================
set -u

PORTAL="$HOME/velaguard/demo"
PY="$PORTAL/patrol_controller.py"
LOG="$PORTAL/patrol-controller.log"
PIDF="$PORTAL/patrol-controller.pid"
PORT=8127
URL="http://127.0.0.1:${PORT}"

kill_existing() {
  if [ -f "$PIDF" ]; then
    OLD=$(cat "$PIDF" 2>/dev/null || echo "")
    if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
      kill "$OLD" 2>/dev/null
      sleep 2
      kill -9 "$OLD" 2>/dev/null
    fi
    rm -f "$PIDF"
  fi
  pkill -f "patrol_controller.py" 2>/dev/null
  sleep 1
}

case "${1:-}" in
  --stop)
    kill_existing
    # safety: no matter what, tell the four cars to stop
    for i in 1 2 3 4; do
      python3 "$HOME/voice_pipeline/ros_car.py" --robots "$i" --cmd STOP >/dev/null 2>&1 &
    done
    wait
    echo "patrol controller stopped; STOP sent to cars 1-4"
    exit 0 ;;
  --status)
    if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
      echo "controller pid $(cat "$PIDF")"
    else
      echo "controller NOT running"
    fi
    curl -s --max-time 4 "$URL/health" || echo "(health endpoint not reachable)"
    echo
    exit 0 ;;
  --log)
    tail -40 "$LOG" 2>/dev/null || echo "(no log yet)"
    exit 0 ;;
  --selftest)
    python3 "$PY" --selftest
    exit $? ;;
esac

echo "=== [1/4] stop any previous instance ==="
kill_existing

echo "=== [2/4] validate route table ==="
if ! python3 "$PY" --selftest; then
  echo "route table invalid -- refusing to start"
  exit 2
fi

echo "=== [3/4] start controller on port ${PORT} ==="
cd "$PORTAL" || exit 1
setsid nohup python3 "$PY" --port "$PORT" --bind 127.0.0.1 > "$LOG" 2>&1 &
sleep 2
# resolve the pid from the listening socket -- matching the command line is a trap
# (pgrep -f can match this very script, since the script text contains the pattern)
PID=$(ss -ltnp 2>/dev/null | grep ":${PORT} " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
if [ -z "$PID" ]; then
  PID=$(pgrep -f "patrol_controller" | head -1)
fi
if [ -z "$PID" ]; then
  echo "controller failed to start; log tail:"
  tail -20 "$LOG"
  exit 3
fi
echo "$PID" > "$PIDF"
echo "  pid $PID"

echo "=== [4/4] health check ==="
H=$(curl -s --max-time 4 "$URL/health" || true)
echo "  $H"
case "$H" in
  *'"ok": true'*) ;;
  *'"ok":true'*) ;;
  *) echo "  health check FAILED"; exit 4 ;;
esac

echo
echo "OK. The E5 page can now drive the cars."
echo "  status : curl -s $URL/patrol/status"
echo "  start  : curl -s -X POST $URL/patrol/start"
echo "  stop   : curl -s -X POST $URL/patrol/stop"
