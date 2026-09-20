#!/bin/bash
# 量一轮语音的真实时间线：
#   - 设备侧：识别/意图/执行/播报 各阶段（给 stdout 逐行打时间戳）
#   - 界面侧：桥的 /api/voice/records 什么时候能查到这条记录（界面就是靠它显示的）
# 两者对齐后，"语音比文字早多少秒"就有了确切数字。
cd /home/sunrise/voice_pipeline || exit 1

before=$(wc -l < /tmp/voice_text.jsonl)
echo "起始记录行数=$before"
date +"开始时刻 %H:%M:%S.%N"

# ---- 1. 后台每 0.4 秒问一次桥：记录出现了吗 ----
rm -f /tmp/poll.log
(
  while :; do
    ts=$(date +%H:%M:%S.%N | cut -c1-12)
    n=$(curl -s --max-time 2 "http://127.0.0.1:8124/api/voice/records?since=$before" 2>/dev/null \
        | python3 -c "import json,sys
try:
    d=json.load(sys.stdin); print(len(d.get('records') or []))
except Exception: print('ERR')" 2>/dev/null)
    echo "$ts records=$n" >> /tmp/poll.log
    sleep 0.4
  done
) &
POLLER=$!
trap 'kill $POLLER 2>/dev/null' EXIT

# ---- 2. 同时记录放音进程的出现与消失（语音什么时候开始/结束）----
(
  while :; do
    ts=$(date +%H:%M:%S.%N | cut -c1-12)
    a=$(pgrep -c -f "aplay.*tts_cache" 2>/dev/null || echo 0)
    echo "$ts aplay=$a" >> /tmp/aplay.log
    sleep 0.3
  done
) &
APLAYER=$!
trap 'kill $POLLER $APLAYER 2>/dev/null' EXIT

rm -f /tmp/aplay.log

# ---- 3. 跑一轮（注入 TTS 合成的那句话，不用人说话）----
set -a
[ -r /etc/x3m-proxy.env ] && . /etc/x3m-proxy.env
[ -r ./选代理.sh ] && . ./选代理.sh
set +a

WAV=$(python3 - <<'PY'
import sys
sys.path.insert(0, '.')
import tts
print(tts.cache_path("四辆小车都连上了吗", "Cherry"))
PY
)
echo "注入音频：$WAV"
rm -f /tmp/timeline.log
timeout 200 python3 -u voice_button.py \
  --trigger terminal --immediate --once \
  --inject-wav "$WAV" --save-wav /tmp/vb_tl.wav \
  --no-beep \
  --agent-backend command --agent-cmd "python3 /home/sunrise/voice_pipeline/llm_intent.py" \
  --cloud-first --vcmd-exec --tts 2>&1 \
| while IFS= read -r line; do printf '%s %s\n' "$(date +%H:%M:%S.%N | cut -c1-12)" "$line"; done \
> /tmp/timeline.log

sleep 3
kill $POLLER $APLAYER 2>/dev/null

echo
echo "===== 设备侧时间线（关键阶段）====="
grep -E "识别（|慢路径|播报结果|意图 |退出码|写日志|共处理|上传云端" /tmp/timeline.log

echo
echo "===== 放音起止（aplay 出现=语音开始）====="
awk '$2!="aplay=0" {print "  语音中 "$1} ' /tmp/aplay.log | head -3
awk 'BEGIN{prev=""} {if ($2=="aplay=0" && prev!="aplay=0" && prev!="") print "  语音结束 "$1; prev=$2}' /tmp/aplay.log | head -3

echo
echo "===== 桥的接口什么时候能查到（界面显示文字的时刻）====="
awk '{print "  "$0}' /tmp/poll.log | awk 'NR==1 || $2!=prev {print} {prev=$2}' | head -8

echo
echo "===== 这一轮的记录 ====="
tail -n +$((before + 1)) /tmp/voice_text.jsonl | cut -c1-160
