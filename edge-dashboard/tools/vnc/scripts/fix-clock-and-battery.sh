#!/bin/bash
# 修两处：①校时脚本要 -k（时钟偏得离谱时证书不通过）②car_state 找不到 check_battery
set -u
V=/home/sunrise/velaguard

echo "===== 1. 更新校时脚本并立刻校时 ====="
cp -f /tmp/dep-clocksync.sh $V/linux/校时.sh && chmod +x $V/linux/校时.sh
echo "  校前：$(date '+%F %T')"
echo sunrise | sudo -S -p "" bash $V/linux/校时.sh
echo "  校后：$(date '+%F %T')"
tail -2 /tmp/clock-sync.log | sed 's/^/  /'

echo
echo "===== 2. 更新 car_state（补 check_battery 的搜索路径）====="
cp -f /tmp/dep-car_state.py $V/linux/car_state.py
python3 -c "compile(open('$V/linux/car_state.py',encoding='utf-8').read(),'x','exec'); print('  compile OK')" || exit 1
echo sunrise | sudo -S -p "" systemctl restart velaguard-cars.service
sleep 12
systemctl is-active velaguard-cars.service
echo "  --- 最近日志 ---"
echo sunrise | sudo -S -p "" journalctl -u velaguard-cars.service -n 4 --no-pager 2>/dev/null | tail -4
echo "  --- state.json 里的实测值 ---"
python3 - <<'PY'
import json
d = json.load(open('/home/sunrise/velaguard/data/state.json', encoding='utf-8'))
print("  generatedAt:", d.get('generatedAt'))
for c in d.get('cars', []):
    print("   %s %-15s %s  电量 %s%%" % (c['id'], c['ip'], '在线' if c['online'] else '离线', c['battery']))
for z in d.get('zones', []):
    print("   %s %-6s status=%-8s %s" % (z['id'], z['name'], z['status'], z['detail']))
PY

echo
echo "===== 3. 校时定时器状态 ====="
echo sunrise | sudo -S -p "" systemctl list-timers --all --no-pager 2>/dev/null | grep -E "NEXT|clock-sync" | head -3

echo
echo "===== 4. 设备时间 vs 真实时间 ====="
date '+  设备：%F %T'
TZ=Asia/Shanghai date -d "$(curl -k -sI --max-time 8 -o /dev/null -D - https://dashscope.aliyuncs.com 2>/dev/null | tr -d '\r' | sed -n 's/^[Dd]ate: //p' | head -1)" '+  真实：%F %T' 2>/dev/null || echo "  （取不到真实时间做对比）"
