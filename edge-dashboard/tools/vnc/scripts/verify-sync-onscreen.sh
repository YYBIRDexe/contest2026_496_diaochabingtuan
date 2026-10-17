#!/bin/bash
# 真机证据：点开语音助手 -> 走一整轮（按钮流程）-> 抓屏看会话区
export DISPLAY=:0
export XAUTHORITY=$HOME/.Xauthority

echo "===== 1. 点开「语音助手」磁贴 ====="
xdotool mousemove 960 472 click 1
sleep 4

echo "===== 2. 走一轮（start -> 喇叭播指令 -> stop）====="
bash /tmp/verify-sync.sh 2>&1 | grep -E ">>>|stop 请求耗时|records=" | tail -12

echo
echo "===== 3. 抓屏 ====="
sleep 2
rm -f /tmp/sync.xwd /tmp/sync-shot.png
xwd -root -silent > /tmp/sync.xwd 2>/dev/null
ffmpeg -y -loglevel error -i /tmp/sync.xwd /tmp/sync-shot.png
echo "  已抓屏 /tmp/sync-shot.png"
