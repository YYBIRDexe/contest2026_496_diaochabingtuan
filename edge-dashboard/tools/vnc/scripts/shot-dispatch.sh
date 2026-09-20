#!/bin/bash
# 点开「巡检调度台」抓屏：核对车卡上的电量是不是实测值
export DISPLAY=:0
export XAUTHORITY=$HOME/.xauthority

# 先回桌面（左上角返回），再点调度台磁贴
xdotool mousemove 60 62 click 1
sleep 2
xdotool mousemove 365 472 click 1
sleep 4
rm -f /tmp/disp.xwd /tmp/disp.png
xwd -root -silent > /tmp/disp.xwd 2>/dev/null
ffmpeg -y -loglevel error -i /tmp/disp.xwd /tmp/disp.png
echo "抓屏时刻 $(date '+%F %T')"
python3 - <<'PY'
import json
d = json.load(open('/home/sunrise/velaguard/data/state.json', encoding='utf-8'))
print("state.json:", d.get('generatedAt'))
for c in d.get('cars', []):
    print("  %s %-15s %s 电量 %s%%" % (c['id'], c['ip'], '在线' if c['online'] else '离线', c['battery']))
PY
