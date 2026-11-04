#!/usr/bin/env bash
# ============================================================
# 把 E5 屏切到 VelaGuard 巡演示（干净版）
#
# 关键（这轮排查的结论）：
#   设备上原先就有一个 kiosk 在跑（旧的 8123 看板，带 --new-instance）。
#   只要还有任何 Firefox 实例存活，`firefox --kiosk URL` 就**不会**全屏，
#   只会在旧进程里开个 200x200 的小标签页。
#   → 必须先杀干净（含 contentproc 子进程），再带 --no-remote 起新实例。
# ============================================================
set -u

PORT=8126
URL="http://127.0.0.1:${PORT}/demo-e5.html"
PORTAL="$HOME/velaguard/demo"
FFPROFILE="$HOME/.mozilla/firefox/vg-demo"

export DISPLAY=:0
export XAUTHORITY="$HOME/.Xauthority"

case "${1:-}" in
  --stop)
    pkill -9 -f firefox 2>/dev/null
    pkill -f "http.server ${PORT}" 2>/dev/null
    echo "已停止演示（Firefox 与静态服务都已关）"
    exit 0 ;;
  --status)
    echo "--- 静态服务 ---"
    curl -s -o /dev/null -w "  HTTP %{http_code}\n" "http://127.0.0.1:${PORT}/demo-e5.html" 2>/dev/null || echo "  没起来"
    echo "--- firefox 进程数 ---"
    pgrep -c firefox 2>/dev/null || echo "  0"
    echo "--- 窗口（看尺寸是否 1920x1080）---"
    xwininfo -root -children 2>/dev/null | grep -iE 'firefox|velaguard' | head -5
    exit 0 ;;
esac

echo "=== [1/6] 杀干净所有 Firefox（关键步骤）==="
pkill -9 -f firefox 2>/dev/null
sleep 4
LEFT=$(pgrep -c firefox 2>/dev/null || echo 0)
echo "  剩余 firefox 进程: $LEFT"
if [ "$LEFT" != "0" ]; then
  echo "  再杀一次"
  pkill -9 -9 -f firefox 2>/dev/null
  sleep 3
  echo "  剩余: $(pgrep -c firefox 2>/dev/null || echo 0)"
fi

echo "=== [2/6] 关掉会话恢复 ==="
mkdir -p "$FFPROFILE"
cat > "$FFPROFILE/user.js" <<'EOF'
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.sessionstore.max_resumed_crashes", 0);
user_pref("browser.sessionstore.enabled", false);
user_pref("browser.startup.page", 0);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.fullscreen.autohide", true);
EOF
echo "  已写 user.js"

echo "=== [3/6] 静态服务（端口 ${PORT}）==="
pkill -f "http.server ${PORT}" 2>/dev/null
sleep 1
cd "$PORTAL" || exit 1
setsid nohup python3 -m http.server "$PORT" --bind 127.0.0.1 > "$PORTAL/server.log" 2>&1 &
sleep 2
CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/demo-e5.html")
SZ=$(curl -s -o /dev/null -w '%{size_download}' "http://127.0.0.1:${PORT}/demo-e5.html")
echo "  HTTP $CODE  ${SZ} bytes"
[ "$CODE" = "200" ] || { echo "  ✗ 服务不通"; tail -5 "$PORTAL/server.log"; exit 1; }

echo "=== [4/6] 起 Firefox kiosk（--no-remote 保证新实例）==="
setsid nohup firefox --kiosk --no-remote "$URL" --profile "$FFPROFILE" \
  > "$PORTAL/kiosk.log" 2>&1 &
sleep 14

echo "=== [5/6] 验证窗口 ==="
xwininfo -root -children 2>/dev/null | grep -iE 'firefox|velaguard' | head -6

echo "=== [6/6] 应用是否真的渲染（截屏算平均亮度）==="
if command -v import >/dev/null 2>&1; then
  import -window root "$PORTAL/shot-now.png" 2>/dev/null
  if [ -f "$PORTAL/shot-now.png" ]; then
    SZ2=$(stat -c%s "$PORTAL/shot-now.png")
    echo "  截图 $PORTAL/shot-now.png  ${SZ2} 字节"
    echo "  判据：正常深色界面 100KB+；纯白页约 10KB"
  fi
else
  echo "  没装 import（ImageMagick），跳过截图"
fi

echo
echo "✓ 完成。E5 屏上应显示 VelaGuard 巡检调度台 + 底部「开始巡检」"
