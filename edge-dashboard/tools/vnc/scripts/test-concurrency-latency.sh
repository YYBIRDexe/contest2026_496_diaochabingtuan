#!/bin/bash
# A) 并发实测：一个慢请求（/api/voice/stop）占着桥时，界面的轮询还回不回得来
# B) 延迟对比：同一条语音，「云端优先」与「本地规则优先」各要多久
cd /home/sunrise/voice_pipeline || exit 1

ms() { date +%s%3N; }

echo "===== A. 并发实测（慢请求 vs 轮询）====="
echo "1) 触发一轮（设备会响「请讲」并开始录音）"
curl -s --max-time 20 -X POST -H 'Content-Type: application/json' -d '{}' \
     http://127.0.0.1:8124/api/voice/start | head -c 200; echo

echo "2) 后台发一个慢请求（stop，wait=6，会占住线程数秒）"
( s=$(ms); curl -s --max-time 30 -X POST -H 'Content-Type: application/json' -d '{"wait":6}' \
      http://127.0.0.1:8124/api/voice/stop > /tmp/stop.out 2>&1; e=$(ms)
  echo "  慢请求耗时 $((e-s)) ms" > /tmp/stop.time ) &
SLOW=$!

sleep 1
echo "3) 与此同时，每 0.7 秒轮询一次 records，量每次的往返时间"
for i in 1 2 3 4 5 6 7 8; do
  s=$(ms)
  curl -s -o /dev/null --max-time 10 "http://127.0.0.1:8124/api/voice/records?since=0"
  e=$(ms)
  printf "  第 %d 次轮询：%d ms\n" "$i" "$((e-s))"
  sleep 0.7
done
wait $SLOW
cat /tmp/stop.time
echo "  慢请求返回内容：$(head -c 160 /tmp/stop.out)"

echo
echo "===== B. 延迟对比：同一条语音，两种解析策略 ====="
WAV=$(python3 - <<'PY'
import sys
sys.path.insert(0, '.')
import tts
print(tts.cache_path("四辆小车都连上了吗", "Cherry"))
PY
)
run_one () {   # run_one <标签> <附加参数...>
  local tag="$1"; shift
  rm -f /tmp/lat_$tag.log
  set -a
  [ -r /etc/x3m-proxy.env ] && . /etc/x3m-proxy.env
  [ -r ./选代理.sh ] && . ./选代理.sh
  set +a
  timeout 120 python3 -u voice_button.py \
    --trigger terminal --immediate --once \
    --inject-wav "$WAV" --save-wav /tmp/vb_lat_$tag.wav \
    --no-beep \
    --agent-backend command --agent-cmd "python3 /home/sunrise/voice_pipeline/llm_intent.py" \
    --vcmd-exec --tts "$@" 2>&1 \
  | while IFS= read -r line; do printf '%s %s\n' "$(date +%H:%M:%S.%3N)" "$line"; done \
  > /tmp/lat_$tag.log
}
run_one cloud --cloud-first
echo "  （云端优先跑完）"
run_one local
echo "  （本地优先跑完）"

for tag in cloud local; do
  echo
  echo "--- $tag ---"
  awk '/识别（/{t_asr=$1} /播报结果|慢路径|解析：/{print "  "$1" "$2" "$3" "$4}' /tmp/lat_$tag.log | head -4
  first=$(head -1 /tmp/lat_$tag.log | awk '{print $1}')
  last=$(grep -m1 "播报结果\|@@SPEAK@@" /tmp/lat_$tag.log | awk '{print $1}')
  echo "  首行 $first → 播报决策 $last"
  python3 - "$first" "$last" <<'PY'
import sys, datetime
def p(s):
    return datetime.datetime.strptime(s.split('.')[0], '%H:%M:%S')
a, b = p(sys.argv[1]), p(sys.argv[2])
print("  该轮从启动到「决定播报」共 %.1f 秒" % (b - a).total_seconds())
PY
  grep -E "识别（|慢路径|播报结果" /tmp/lat_$tag.log | sed 's/^/    /'
done
