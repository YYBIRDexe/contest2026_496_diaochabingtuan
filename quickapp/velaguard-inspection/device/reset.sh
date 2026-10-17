#!/usr/bin/env bash
# ============================================================
# 录制前复位：把 E5 屏恢复到干净的「未开始巡检」初始画面
#
# 用法（在设备上，或从 Windows 用 ssh 调用）：
#   bash ~/velaguard/demo/reset.sh
#
# 它做三件事：
#   1. 关掉演示页并重开（等价于刷新，store 状态归零）
#   2. 等页面就绪
#   3. 截一张图确认是初始画面（提示条在、按钮在）
# ============================================================
set -u
PORTAL="$HOME/velaguard/demo"
PORT=8126
URL="http://127.0.0.1:${PORT}/demo-e5.html"
FFPROFILE="$HOME/.mozilla/firefox/vg-demo"
export DISPLAY=:0
export XAUTHORITY="$HOME/.Xauthority"

echo "=== [1/4] 关掉当前 kiosk ==="
pkill -9 -f firefox 2>/dev/null
sleep 3
echo "  剩余 firefox: $(pgrep -c firefox 2>/dev/null || echo 0)"

echo "=== [2/4] 确认静态服务在跑 ==="
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null)
if [ "$CODE" != "200" ]; then
  echo "  服务没跑（HTTP $CODE），重新起"
  pkill -f "http.server ${PORT}" 2>/dev/null
  sleep 1
  cd "$PORTAL" && setsid nohup python3 -m http.server "$PORT" --bind 127.0.0.1 \
    > "$PORTAL/server.log" 2>&1 &
  sleep 2
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null)
fi
echo "  HTTP $CODE"

echo "=== [3/4] 重开 kiosk（页面重新加载，store 归零）==="
cd "$PORTAL"
setsid nohup firefox --kiosk --no-remote "$URL" --profile "$FFPROFILE" \
  > "$PORTAL/kiosk.log" 2>&1 &
sleep 12

echo "=== [4/4] 截屏确认是初始画面 ==="
xwd -root -silent -out "$PORTAL/reset.xwd" 2>/dev/null
python3 - <<'PY'
import struct, os
from PIL import Image
from collections import Counter
base = os.path.expanduser('~/velaguard/demo')
p = os.path.join(base, 'reset.xwd')
if not os.path.exists(p):
    print('  截屏失败'); raise SystemExit
d = open(p, 'rb').read()
q = struct.unpack('>25I', d[:100]); w,h,bpl,nc,hsz = q[4],q[5],q[12],q[19],q[0]
img = Image.frombytes('RGBA',(w,h),d[hsz+nc*12:hsz+nc*12+bpl*h],'raw','BGRA',bpl).convert('RGB')
img.save(os.path.join(base, 'reset.png'))
px = list(img.resize((160,90)).getdata())
uniq = len(set((r//8*8,g//8*8,b//8*8) for r,g,b in px))
top = Counter((r//16*16,g//16*16,b//16*16) for r,g,b in px).most_common(1)[0]
print('  %dx%d  色块=%d  主色=#%02x%02x%02x %.0f%%' % (w,h,uniq,top[0][0],top[0][1],top[0][2],100.0*top[1]/len(px)))
print('  初始画面参照：色块 300+，主色 #001020')
PY

echo
echo "✓ 已复位。E5 屏上应是「尚未开始巡检」+ 底部「开始巡检」按钮"
echo "  录制时：用手指点「开始巡检」，约 9 秒走完全流程"
