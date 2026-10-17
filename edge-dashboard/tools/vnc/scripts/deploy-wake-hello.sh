#!/bin/bash
# 换唤醒词：打补丁 -> 重启服务 -> 声学实测（新词该唤醒、旧词不该再作为唯一入口）
set -u
P=/home/sunrise/voice_pipeline
cd $P || exit 1

echo "===== 1. 打补丁 ====="
cp -f /tmp/dep-patch-hello.py $P/_patch_wake_hello.py
python3 _patch_wake_hello.py

echo
echo "===== 2. 确认改动 ====="
grep -n '"keywords"\|"grammar"' wakeword.py | sed 's/^/  /'
python3 - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location('w', '/home/sunrise/voice_pipeline/wakeword.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print("  en keywords =", repr(m.PRESETS['en']['keywords']))
print("  en grammar  =", repr(m.PRESETS['en']['grammar']))
PY
grep -n 'PHRASE\|^KEYS\|^GRAMMAR' en_hit_rate.py | sed 's/^/  /'
grep -n '唤醒词：' 唤醒.sh | sed 's/^/  /'

echo
echo "===== 3. 重启语音服务 ====="
echo sunrise | sudo -S -p "" systemctl restart voice-assistant.service
sleep 16
systemctl is-active voice-assistant.service
grep -E "模型就绪。唤醒词|解码候选" /tmp/voice_wake.log | tail -2 | sed 's/^/  /'

echo
echo "===== 4. 声学实测：播「Hello, openvela」应唤醒 ====="
HELLO=$P/tts_cache/3b6a47f8183b1712.wav
before=$(grep -c '听到唤醒词' /tmp/voice_wake.log)
echo "  基线命中=$before，播放 $HELLO"
aplay -D plughw:CARD=hobotsnd5,DEV=1 -q "$HELLO" 2>/dev/null
sleep 10
after=$(grep -c '听到唤醒词' /tmp/voice_wake.log)
echo "  播完命中=$after （期望 +1）"
grep '听到唤醒词' /tmp/voice_wake.log | tail -2 | sed 's/^/  /'

echo
echo "===== 5. 结论 ====="
if [ "$after" -gt "$before" ]; then
  echo "  [OK] Hello, openvela 能唤醒"
else
  echo "  [X] 这次没唤醒（可能是播放时机/引擎忙，需再测一次）"
fi
