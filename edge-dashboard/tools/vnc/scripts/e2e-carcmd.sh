#!/bin/bash
# 用 TTS 合成「四辆小车都连上了吗」当作测试音频（TTS 音频喂 ASR 的识别率实测很稳）
# 然后注入跑一轮，验证：car_check 意图 -> check_cars -> @@SPEAK@@ 播报 -> 记录里的 said
cd /home/sunrise/voice_pipeline || exit 1

echo "===== 1. 合成测试音频 ====="
set -a
[ -r /etc/x3m-proxy.env ] && . /etc/x3m-proxy.env
[ -r ./选代理.sh ] && . ./选代理.sh
set +a
python3 tts.py --presynth "四辆小车都连上了吗" 2>&1 | tail -3
WAV=$(python3 - <<'PY'
import sys
sys.path.insert(0, '.')
import tts
print(tts.cache_path("四辆小车都连上了吗", "Cherry"))
PY
)
echo "  音频: $WAV"
ls -l "$WAV"

echo
echo "===== 2. 注入这一轮 ====="
before=$(wc -l < /tmp/voice_text.jsonl)
echo "  注入前记录行数=$before"
rm -f /tmp/vg-inject2.log
timeout 200 python3 voice_button.py \
  --trigger terminal --immediate --once \
  --inject-wav "$WAV" --save-wav /tmp/vb_inject2.wav \
  --no-beep --no-net-check \
  --agent-backend command --agent-cmd "python3 /home/sunrise/voice_pipeline/llm_intent.py" \
  --cloud-first --vcmd-exec --tts \
  --tee-log /tmp/vg-inject2.log

echo
echo "===== 3. 关键链路行 ====="
grep -nE "识别（|慢路径|播报结果|-> 意图|执行：|退出码|四车在线|@@SPEAK@@" /tmp/vg-inject2.log | tail -20

echo
echo "===== 4. 新增记录（重点看有没有 said）====="
tail -n +$((before + 1)) /tmp/voice_text.jsonl

echo
echo "===== 5. 桥的接口 ====="
curl -s --max-time 8 "http://127.0.0.1:8124/api/voice/records?since=$before"
echo
