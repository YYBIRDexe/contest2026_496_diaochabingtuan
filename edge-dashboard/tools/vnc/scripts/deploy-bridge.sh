#!/bin/bash
# 更新语音桥（只换桥，不动助手和界面）并做一次自检
set -u
V=/home/sunrise/velaguard

echo "===== 1. 换桥 ====="
python3 -c "compile(open('/tmp/dep-speech-bridge.py',encoding='utf-8').read(),'x','exec'); print('  compile OK')" || exit 1
cp -f /tmp/dep-speech-bridge.py $V/linux/speech-bridge.py
chmod +x $V/linux/speech-bridge.py
pkill -f "speech-bridge.py" 2>/dev/null
sleep 1
cd $V/linux && setsid nohup python3 speech-bridge.py --port 8124 >> /tmp/vg-bridge.log 2>&1 < /dev/null &
sleep 3
pgrep -af "speech-bridge.py" || echo "  (桥没起来)"

echo
echo "===== 2. 端点自检 ====="
curl -s --max-time 8 http://127.0.0.1:8124/api/voice/state; echo
curl -s --max-time 8 "http://127.0.0.1:8124/api/voice/records?since=0" | python3 -c "
import json,sys
d = json.load(sys.stdin)
print('  records ok=%s count=%s lastSeq=%s' % (d.get('ok'), d.get('count'), d.get('lastSeq')))
r = (d.get('records') or [])
if r:
    last = r[-1]
    print('  最后一条: seq=%s text=%r said=%r' % (last['seq'], last['text'][:20], last['said']))
"

echo
echo "===== 3. 僵尸放音判断（当前是否存在僵尸 aplay）====="
pgrep -af aplay | head -5 || echo "  没有 aplay 进程"
for p in $(pgrep -f aplay); do echo "  pid=$p stat=$(ps -o stat= -p $p)"; done

echo
echo "===== 4. 语音服务状态 ====="
systemctl is-active voice-assistant.service
ps -eo pid,args | grep -cE "[v]oice_button|[w]akeword" | sed 's/^/  助手+唤醒进程数: /'
echo "--- 桥日志尾部（确认没有 restart 服务的动作）---"
tail -6 /tmp/vg-bridge.log
