#!/bin/bash
# 换唤醒词前的实测包装：先停服务腾麦克风，跑完**无论成败都恢复服务**（trap）
set -u

restore() {
  echo
  echo "===== 恢复语音服务 ====="
  echo sunrise | sudo -S -p "" systemctl start voice-assistant.service
  sleep 12
  systemctl is-active voice-assistant.service
  pgrep -af wakeword.py | head -1
}
trap restore EXIT

echo "===== 1. 先合成测试音频（这时服务还在、网络还在）====="
set -a
[ -r /etc/x3m-proxy.env ] && . /etc/x3m-proxy.env
[ -r /home/sunrise/voice_pipeline/选代理.sh ] && . /home/sunrise/voice_pipeline/选代理.sh
set +a
cd /home/sunrise/voice_pipeline
python3 - <<'PY'
import sys, time
sys.path.insert(0, '/home/sunrise/voice_pipeline')
import tts
for p in ("Hello, openvela", "hello open vela"):
    for attempt in (1, 2):
        try:
            print("  合成「%s」-> %s" % (p, tts.synth(p)))
            break
        except Exception as e:
            print("  合成「%s」第 %d 次失败：%s" % (p, attempt, e))
            time.sleep(2)
PY

echo
echo "===== 2. 停服务腾麦克风 ====="
echo sunrise | sudo -S -p "" systemctl stop voice-assistant.service
sleep 2
pkill -9 -f wakeword.py 2>/dev/null
pkill -9 -f arecord 2>/dev/null
sleep 1
pgrep -af "voice_button|wakeword" || echo "  已停干净"

echo
echo "===== 3. 跑实测（约 1 分钟）====="
timeout 300 python3 /tmp/wake_hello_measure.py
echo "  退出码=$?"
