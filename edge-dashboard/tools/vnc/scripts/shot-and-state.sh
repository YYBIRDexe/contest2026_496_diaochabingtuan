#!/bin/bash
# 抓真机屏幕 + 打印实时数据与时钟，用于核对「界面显示 = 实测值」
export DISPLAY=:0
export XAUTHORITY=$HOME/.Xauthority
rm -f /tmp/now.xwd /tmp/now.png
xwd -root -silent > /tmp/now.xwd 2>/dev/null
ffmpeg -y -loglevel error -i /tmp/now.xwd /tmp/now.png

echo "抓屏时刻：$(date '+%F %T')"
echo "--- state.json（界面每 5 秒读一次的就是它）---"
python3 - <<'PY'
import json, os, time
p = '/home/sunrise/velaguard/data/state.json'
d = json.load(open(p, encoding='utf-8'))
print("  generatedAt:", d.get('generatedAt'))
print("  文件年龄: %.1f 秒" % (time.time() - os.path.getmtime(p)))
for c in d.get('cars', []):
    print("  %s %-15s %s 电量 %s%%" % (c['id'], c['ip'], '在线' if c['online'] else '离线', c['battery']))
PY
echo "--- car_state 服务 ---"
systemctl is-active velaguard-cars.service
