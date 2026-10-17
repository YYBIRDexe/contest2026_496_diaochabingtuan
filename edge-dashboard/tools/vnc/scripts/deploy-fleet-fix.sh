#!/bin/bash
# 部署「多车目标」补丁并验证（全程 dry-run，不会真的动车）
set -u
P=/home/sunrise/voice_pipeline
cd $P || exit 1

echo "===== 1. 打补丁 ====="
cp -f /tmp/dep-patch-fleet.py $P/_patch_fleet_targets.py
python3 _patch_fleet_targets.py

echo
echo "===== 2. 设备自带回归（改完必须全绿）====="
python3 nlp_parse.py --selftest 2>&1 | tail -3
python3 vcmd.py --selftest 2>&1 | tail -3
python3 run_tests.py 2>&1 | tail -3

echo
echo "===== 3. _extract_robots 目标车判定（设备上跑真代码）====="
python3 - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("vb", "/home/sunrise/voice_pipeline/voice_button.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
for s in ["小车编队，后退0.5米", "四台车后退0.5米", "所有车后退", "1号和3号前进",
          "2号车左转", "后退0.5米", "大家一起编队"]:
    print("  %-22s -> %r" % (s, m._extract_robots(s)))
PY

echo
echo "===== 4. 重启语音服务（让补丁生效）====="
echo sunrise | sudo -S -p "" systemctl restart voice-assistant.service
sleep 16
systemctl is-active voice-assistant.service
ps -eo pid,args | grep -cE "[v]oice_button|[w]akeword" | sed 's/^/  助手+唤醒进程数: /'

echo
echo "===== 5. 合成测试音频并注入跑一轮（dry-run，不动车）====="
set -a
[ -r /etc/x3m-proxy.env ] && . /etc/x3m-proxy.env
[ -r ./选代理.sh ] && . ./选代理.sh
set +a
python3 tts.py --presynth "小车编队，后退0.5米" 2>&1 | tail -2
WAV=$(python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import tts
print(tts.cache_path("小车编队，后退0.5米", "Cherry"))
PY
)
echo "  音频: $WAV"
before=$(wc -l < /tmp/voice_text.jsonl)
rm -f /tmp/fleet_test.log
timeout 200 python3 -u voice_button.py \
  --trigger terminal --immediate --once \
  --inject-wav "$WAV" --save-wav /tmp/vb_fleet.wav \
  --no-beep \
  --agent-backend command --agent-cmd "python3 /home/sunrise/voice_pipeline/llm_intent.py" \
  --cloud-first --tts 2>&1 | tee /tmp/fleet_test.log | grep -E "识别（|慢路径|目标车|解析：|播报结果"

echo
echo "===== 6. 这一轮的记录（重点看 robots / commands）====="
tail -n +$((before + 1)) /tmp/voice_text.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line.startswith('{'): continue
    r = json.loads(line)
    print('  文本:', r.get('text'))
    print('  source:', r.get('source'), '| said:', r.get('said'))
    for s in (r.get('steps') or []):
        print('  step:', s.get('intent'), s.get('params'))
    for sr in (r.get('step_results') or []):
        print('  → intent=%s robots=%r rc=%s executed=%s' % (
            sr.get('intent'), sr.get('robots'), sr.get('rc'), sr.get('executed')))
        for c in (sr.get('commands') or []):
            print('     cmd:', c[:180])
"
