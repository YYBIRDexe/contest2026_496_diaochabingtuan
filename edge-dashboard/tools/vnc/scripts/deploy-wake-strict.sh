#!/bin/bash
# 部署唤醒词收紧补丁 + 声学实测（真播真录，不是看代码）
set -u
P=/home/sunrise/voice_pipeline
cd $P || exit 1

echo "===== 1. 打补丁 ====="
cp -f /tmp/dep-patch-wake.py $P/_patch_wake_strict.py
python3 _patch_wake_strict.py

echo
echo "===== 2. 确认改动内容 ====="
grep -n -A3 -B1 '"keywords"' wakeword.py | head -20
python3 -c "
import sys; sys.path.insert(0,'.')
import importlib.util
spec = importlib.util.spec_from_file_location('w','wakeword.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print('  en 预设 keywords =', repr(m.PRESETS['en']['keywords']))
print('  en 预设 grammar  =', repr(m.PRESETS['en']['grammar']))
"
grep -n "^KEYS" en_hit_rate.py

echo
echo "===== 3. 重启语音服务 ====="
echo sunrise | sudo -S -p "" systemctl restart voice-assistant.service
sleep 16
systemctl is-active voice-assistant.service
ps -eo pid,args | grep -E "[w]akeword|[v]oice_button" | cut -c1-95
echo "--- 启动日志（应显示「唤醒词：hi openvela」，只有一个）---"
grep -E "唤醒词|解码候选" /tmp/voice_wake.log | tail -4

echo
echo "===== 4. 声学实测：单说 openvela 不该再触发 ====="
BARE=/tmp/wk_bare_openvela.wav
HI=$P/tts_cache/dfe29abb0563f80c.wav
before=$(grep -c '听到唤醒词' /tmp/voice_wake.log)
echo "  基线命中次数=$before"
echo "  播放「openvela（剪掉 hi）」…"
aplay -D plughw:CARD=hobotsnd5,DEV=1 -q "$BARE" 2>/dev/null
sleep 6
mid=$(grep -c '听到唤醒词' /tmp/voice_wake.log)
echo "  播完后命中次数=$mid （期望与基线相同）"

echo
echo "===== 5. 声学实测：说 hi openvela 必须仍然能唤醒 ====="
echo "  播放「hi openvela」…"
aplay -D plughw:CARD=hobotsnd5,DEV=1 -q "$HI" 2>/dev/null
sleep 10
after=$(grep -c '听到唤醒词' /tmp/voice_wake.log)
echo "  播完后命中次数=$after （期望 +1）"
echo "--- 最近两次命中记录 ---"
grep '听到唤醒词' /tmp/voice_wake.log | tail -2

echo
echo "===== 6. 结论 ====="
if [ "$mid" = "$before" ] && [ "$after" -gt "$mid" ]; then
  echo "  ✅ 收紧生效：单说 openvela 不再触发，hi openvela 仍能唤醒"
elif [ "$mid" != "$before" ]; then
  echo "  ❌ 单说 openvela 仍然触发了（收紧没生效）"
else
  echo "  ⚠️ hi openvela 这次没唤醒（可能是播放时机/引擎正忙，需再测一次）"
fi
