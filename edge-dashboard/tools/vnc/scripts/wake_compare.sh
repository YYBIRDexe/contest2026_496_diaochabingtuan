#!/bin/bash
# 唤醒词配置对比实验的包装脚本
#
# 关键点：实验要用麦克风/扬声器，必须先把语音服务停掉（它常驻占用麦克风）。
# 用 trap 保证**无论实验成功与否，服务都会被拉回来** —— 否则会出现
# 「做完实验唤醒词再也不响应」这种更糟的状态。
set -u

restore() {
  echo
  echo "===== 恢复语音服务 ====="
  echo sunrise | sudo -S -p "" systemctl start voice-assistant.service
  sleep 12
  systemctl is-active voice-assistant.service
  ps -eo pid,args | grep -E "[v]oice_button|[w]akeword|[a]record" | cut -c1-90
}
trap restore EXIT

echo "===== 1. 先把测试音频合成好（这时服务还在、网络还在）====="
set -a
[ -r /etc/x3m-proxy.env ] && . /etc/x3m-proxy.env
[ -r /home/sunrise/voice_pipeline/选代理.sh ] && . /home/sunrise/voice_pipeline/选代理.sh
set +a
cd /home/sunrise/voice_pipeline
python3 - <<'PY'
import sys, time
sys.path.insert(0, '/home/sunrise/voice_pipeline')
import tts
phrases = ["hi openvela", "openvela",
           "然后因为那孩子年级第一第二的一帮人带着走",
           "收入够是吧因为那一年没人敢报北大",
           "实验型高中他们人少但是也强"]
for p in phrases:
    for attempt in (1, 2):        # 隧道偶尔抽风，重试一次
        try:
            print("  合成「%s」-> %s" % (p[:14], tts.synth(p)))
            break
        except Exception as e:
            print("  合成「%s」第 %d 次失败：%s" % (p[:14], attempt, e))
            time.sleep(2)
PY

echo
echo "===== 2. 停服务，腾出麦克风 ====="
echo sunrise | sudo -S -p "" systemctl stop voice-assistant.service
sleep 2
pkill -9 -f wakeword.py 2>/dev/null
pkill -9 -f arecord 2>/dev/null
sleep 1
pgrep -af "voice_button|wakeword" || echo "  已停干净"

echo
echo "===== 3. 跑对比实验（约 2 分钟）====="
timeout 400 python3 /tmp/wake_compare.py
echo "  实验退出码=$?"
