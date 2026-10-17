#!/bin/bash
# 查「小车编队，后退0.5米」这一轮到底被解析成什么、发给了哪几台车
echo "===== 1. 记录里最近的编队/后退相关轮次 ====="
grep -nE "编队|后退|backward|formation" /tmp/voice_text.jsonl | tail -8 | cut -c1-400

echo
echo "===== 2. 最近 6 条记录全文（看 steps / robots / commands）====="
tail -6 /tmp/voice_text.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line.startswith('{'): continue
    try: r = json.loads(line)
    except Exception: continue
    print('---')
    print('  时间:', r.get('ts'), '| 文本:', repr(r.get('text'))[:70])
    print('  source:', r.get('source'), '| error:', r.get('error'), '| said:', r.get('said'))
    for s in (r.get('steps') or []):
        print('  step:', s.get('intent'), s.get('params'))
    for sr in (r.get('step_results') or []):
        print('  → intent=%s robots=%r rc=%s' % (sr.get('intent'), sr.get('robots'), sr.get('rc')))
        for c in (sr.get('commands') or []):
            print('     cmd:', c[:200])
"

echo
echo "===== 3. 现在用这句话跑一遍解析（只解析、不执行，安全）====="
cd /home/sunrise/voice_pipeline || exit 1
for t in "小车编队，后退0.5米" "后退0.5米" "四台车后退0.5米" "所有车后退0.5米"; do
  echo "--- 输入：$t"
  python3 vcmd.py --text "$t" 2>&1 | tail -6 | sed 's/^/    /'
done

echo
echo "===== 4. 本地规则怎么判的 ====="
python3 - <<'PY'
import sys
sys.path.insert(0, '.')
try:
    import nlp_parse as N
    for s in ["小车编队，后退0.5米", "后退0.5米", "四台车后退0.5米"]:
        print("  ", repr(s), "->", N.parse(s))
except Exception as e:
    print("  nlp_parse 出错:", e)
PY

echo
echo "===== 5. 目标车是怎么定的 ====="
grep -n "def _extract_robots" -A 30 voice_button.py | head -40
echo "--- ROBOTS 默认值 ---"
grep -n "CAR_IP\|ROBOTS" 唤醒.sh | head -6
grep -n "ROBOTS" robots.json 2>/dev/null | head -3
cat robots.json
