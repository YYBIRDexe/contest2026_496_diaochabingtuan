#!/bin/bash
# 部署 VelaGuard 侧的两处修复到设备（界面 + 语音桥 + 助手的 said 补丁）
set -u
V=/home/sunrise/velaguard
P=/home/sunrise/voice_pipeline

echo "===== 1. 语音桥：校验语法 -> 备份 -> 替换 ====="
python3 -c "compile(open('/tmp/dep-speech-bridge.py',encoding='utf-8').read(),'x','exec'); print('新桥 compile OK')" || exit 1
cp -f $V/linux/speech-bridge.py /tmp/speech-bridge.py.bak-$(date +%m%d_%H%M) 2>/dev/null
cp -f /tmp/dep-speech-bridge.py $V/linux/speech-bridge.py
chmod +x $V/linux/speech-bridge.py
grep -c "api/voice/records" $V/linux/speech-bridge.py | sed 's/^/  records 端点出现次数: /'
grep -c "startswith(\"Z\")" $V/linux/speech-bridge.py | sed 's/^/  僵尸判断出现次数: /'

echo
echo "===== 2. 助手 said 补丁 ====="
cp -f /tmp/dep-patch-said.py $P/_patch_said_reply.py
cd $P && python3 _patch_said_reply.py

echo
echo "===== 3. 界面：校验产物 -> 替换 ====="
ls -l /tmp/dep-index.html
grep -c "voice/records" /tmp/dep-index.html | sed 's/^/  产物里 records 轮询次数: /'
cp -f $V/preview/index.html /tmp/index.html.bak-$(date +%m%d_%H%M) 2>/dev/null
cp -f /tmp/dep-index.html $V/preview/index.html
md5sum $V/preview/index.html

echo
echo "===== 4. 重启语音桥 ====="
pkill -f "speech-bridge.py" 2>/dev/null
sleep 1
cd $V/linux && setsid nohup python3 speech-bridge.py --port 8124 >> /tmp/vg-bridge.log 2>&1 < /dev/null &
sleep 3
pgrep -af "speech-bridge.py" || echo "  (桥没起来)"
curl -s --max-time 8 http://127.0.0.1:8124/api/voice/records?since=0 | head -c 300
echo

echo
echo "===== 5. 重启语音服务（让补丁生效 + 唤醒引擎回来）====="
echo sunrise | sudo -S -p "" systemctl restart voice-assistant.service
sleep 14
echo "--- 服务状态 ---"
systemctl is-active voice-assistant.service
echo "--- 进程（期望：助手+唤醒+arecord 共 3 个）---"
ps -eo pid,etime,args | grep -E "[v]oice_button|[w]akeword|[a]record" | cut -c1-120
echo "--- 唤醒日志尾部 ---"
tail -6 /tmp/voice_wake.log
