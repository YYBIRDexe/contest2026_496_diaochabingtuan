#!/bin/bash
# 部署"语音/文字同步"修复：桥换多线程 + 界面换 1 秒轮询，然后重启桥与看板
set -u
V=/home/sunrise/velaguard

echo "===== 1. 换桥（多线程 + stop 不再等播报）====="
python3 -c "compile(open('/tmp/dep-speech-bridge.py',encoding='utf-8').read(),'x','exec'); print('  compile OK')" || exit 1
cp -f $V/linux/speech-bridge.py /tmp/speech-bridge.py.bak-$(date +%m%d_%H%M) 2>/dev/null
cp -f /tmp/dep-speech-bridge.py $V/linux/speech-bridge.py
grep -c "ThreadingHTTPServer" $V/linux/speech-bridge.py | sed 's/^/  ThreadingHTTPServer 出现次数: /'
grep -c "wait_playback=False" $V/linux/speech-bridge.py | sed 's/^/  stop 不等播报: /'
pkill -f "speech-bridge.py" 2>/dev/null
sleep 1
cd $V/linux && setsid nohup python3 speech-bridge.py --port 8124 >> /tmp/vg-bridge.log 2>&1 < /dev/null &
sleep 3
pgrep -af "speech-bridge.py" | head -2
tail -3 /tmp/vg-bridge.log

echo
echo "===== 2. 换界面（1 秒轮询 + stop wait=2）====="
grep -c "voice/records" /tmp/dep-index.html | sed 's/^/  产物 records 轮询: /'
grep -c "}, 1000);" /tmp/dep-index.html | sed 's/^/  1 秒间隔出现次数: /'
cp -f $V/preview/index.html /tmp/index.html.bak-$(date +%m%d_%H%M) 2>/dev/null
cp -f /tmp/dep-index.html $V/preview/index.html
md5sum $V/preview/index.html

echo
echo "===== 3. 重启看板（带 cache-bust）====="
export DISPLAY=:0
export XAUTHORITY=$HOME/.Xauthority
pkill -f firefox 2>/dev/null
sleep 4
TS=$(date +%s)
cd $V
setsid nohup firefox --new-instance --kiosk "http://127.0.0.1:8123/preview/index.html?v=$TS#kiosk" \
  > /tmp/vg-ff.log 2>&1 < /dev/null &
sleep 25
ps -eo pid,rss,args | grep "[f]irefox --new-instance" | head -1

echo
echo "===== 4. 服务状态 ====="
systemctl is-active voice-assistant.service
curl -s --max-time 8 http://127.0.0.1:8124/api/voice/state; echo
