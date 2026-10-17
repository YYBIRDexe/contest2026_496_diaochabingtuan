#!/bin/bash
# 在真机上验证「左侧会话区自动下滑」：进入语音助手 -> 连点常用指令 -> 抓屏看是否贴底
export DISPLAY=:0
export XAUTHORITY=$HOME/.Xauthority

tap() {   # tap <x> <y>
  xdotool mousemove "$1" "$2" click 1
  sleep 0.6
}

shot() {  # shot <名字>
  rm -f /tmp/shot.xwd /tmp/shot-$1.png
  xwd -root -silent > /tmp/shot.xwd 2>/dev/null
  ffmpeg -y -loglevel error -i /tmp/shot.xwd /tmp/shot-$1.png 2>&1 | tail -1
  echo "  抓屏 -> /tmp/shot-$1.png"
}

echo "===== 0. 窗口与 xdotool ====="
which xdotool || echo "  xdotool 不在"
xdotool search --onlyvisible --name "." getwindowname %@ 2>/dev/null | head -5

echo
echo "===== 1. 点开「语音助手」磁贴 ====="
tap 960 472
sleep 3
shot 1-voice

echo
echo "===== 2. 连点常用指令（每点一次加「你」+「助手」两条气泡）====="
for i in 1 2 3 4 5; do
  echo "  第 $i 次点击"
  tap 160 895
done
sleep 2
shot 2-filled

echo
echo "===== 3. 再点一条别的指令，确认跟着往下走 ====="
tap 441 895
sleep 2
shot 3-last

echo
echo "===== 4. 页面里的会话状态（用 CDP 拿不到，这里只报进程）====="
ps -eo pid,rss,comm | grep -i firefox | head -3
