#!/bin/bash
# 复刻用户的真实操作，给「语音出现」与「文字出现」各打一个时间戳。
#
#   1) 调桥的 /api/voice/start（= 界面按一下「说话」）
#   2) 等设备说完「请讲」，用喇叭把指令播给麦克风听（代替人说话）
#   3) 调 /api/voice/stop（= 界面再按一下）
#   4) 全程每 0.25 秒记录：桥接口能不能查到记录、aplay 在放哪个文件
cd /home/sunrise/voice_pipeline || exit 1

SPK=plughw:CARD=hobotsnd5,DEV=1
ASK=$(python3 - <<'PY'
import sys; sys.path.insert(0,'.')
import tts
print(tts.cache_path("四辆小车都连上了吗", "Cherry"))
PY
)
PROMPT=$(python3 - <<'PY'
import sys; sys.path.insert(0,'.')
import tts
print(tts.cache_path("请讲", "Cherry"))
PY
)
echo "指令音频=$ASK"
echo "提示音频=$PROMPT"

rm -f /tmp/sync.log
before=$(curl -s --max-time 5 "http://127.0.0.1:8124/api/voice/records?since=0" \
         | python3 -c "import json,sys;print(json.load(sys.stdin).get('lastSeq',0))")
echo "起始 lastSeq=$before"

# 后台采样
(
  while :; do
    ts=$(date +%H:%M:%S.%3N)
    n=$(curl -s --max-time 3 "http://127.0.0.1:8124/api/voice/records?since=$before" 2>/dev/null \
        | python3 -c "import json,sys
try: print(len(json.load(sys.stdin).get('records') or []))
except Exception: print('E')" 2>/dev/null)
    ap=""
    for p in $(pgrep -x aplay 2>/dev/null); do
      f=$(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | grep -o 'tts_cache/[a-f0-9]*\.wav')
      [ -n "$f" ] && ap="$ap$(basename $f),"
    done
    echo "$ts records=$n aplay=$ap" >> /tmp/sync.log
    sleep 0.25
  done
) &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null' EXIT

echo
echo ">>> $(date +%H:%M:%S.%3N) 按一下「说话」（POST /api/voice/start）"
curl -s --max-time 25 -X POST -H 'Content-Type: application/json' -d '{}' \
     http://127.0.0.1:8124/api/voice/start; echo

echo ">>> 等 3.2 秒（让「请讲」播完、录音已开始）"
sleep 3.2
echo ">>> $(date +%H:%M:%S.%3N) 喇叭播指令（代替人说话）"
aplay -D $SPK -q "$ASK"
sleep 1.0

echo ">>> $(date +%H:%M:%S.%3N) 再按一下「结束」（POST /api/voice/stop，wait=2）"
s=$(date +%s%3N)
curl -s --max-time 40 -X POST -H 'Content-Type: application/json' -d '{"wait":2}' \
     http://127.0.0.1:8124/api/voice/stop; echo
e=$(date +%s%3N)
echo ">>> stop 请求耗时 $((e-s)) ms"

sleep 8
kill $SAMPLER 2>/dev/null

echo
echo "===== 采样（只显示有变化的行）====="
awk '{ key=$2" "$3; if (key!=prev) { print "  "$0 } prev=key }' /tmp/sync.log

echo
echo "===== 新增记录 ====="
curl -s --max-time 8 "http://127.0.0.1:8124/api/voice/records?since=$before" | cut -c1-300
