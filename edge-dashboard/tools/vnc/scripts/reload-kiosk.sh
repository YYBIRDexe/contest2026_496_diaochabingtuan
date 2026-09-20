#!/bin/bash
# 重启设备上的看板浏览器（kiosk），拿到新版界面并抓屏
export DISPLAY=:0
export XAUTHORITY=$HOME/.Xauthority
V=/home/sunrise/velaguard

echo "===== 1. 关掉旧 Firefox ====="
pkill -f firefox 2>/dev/null
sleep 4
ps -eo pid,args | grep -c "[f]irefox" | sed 's/^/  剩余 firefox 进程: /'

echo
echo "===== 2. 确认页面服务在跑 ====="
curl -s -o /dev/null -w "  index: %{http_code}\n" --max-time 8 "http://127.0.0.1:8123/preview/index.html"
curl -s --max-time 8 "http://127.0.0.1:8123/preview/index.html" | grep -c "voice/records" | sed 's/^/  服务端给出的产物里 records 轮询次数: /'

echo
echo "===== 3. 以 kiosk 方式重新打开（带 cache-bust 参数）====="
TS=$(date +%s)
cd $V
setsid nohup firefox --new-instance --kiosk "http://127.0.0.1:8123/preview/index.html?v=$TS#kiosk" \
  > /tmp/vg-ff.log 2>&1 < /dev/null &
echo "  已启动（v=$TS）"
sleep 30
ps -eo pid,rss,args | grep "[f]irefox --new-instance" | head -2

echo
echo "===== 4. 抓屏 ====="
rm -f /tmp/now.xwd /tmp/now.png
xwd -root -silent > /tmp/now.xwd 2>/dev/null && echo "  xwd ok $(stat -c%s /tmp/now.xwd)"
ffmpeg -y -loglevel error -i /tmp/now.xwd /tmp/now.png 2>&1 | tail -2
python3 -c "from PIL import Image; im=Image.open('/tmp/now.png'); print('  png', im.size)" 2>/dev/null || echo "  png 检查失败"

echo
echo "===== 5. 语音链路当前状态 ====="
curl -s --max-time 8 http://127.0.0.1:8124/api/voice/state; echo
