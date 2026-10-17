#!/bin/bash
# 部署：①校时（含开机后自动校 + 定时校）②每 5 秒探测四台车写 state.json ③界面
set -u
V=/home/sunrise/velaguard
P=/home/sunrise/voice_pipeline

echo "===== 1. 立刻校时（先修好当前这块表）====="
echo "  校前：$(date '+%F %T')"
cp -f /tmp/dep-clocksync.sh $V/linux/校时.sh && chmod +x $V/linux/校时.sh
echo sunrise | sudo -S -p "" bash $V/linux/校时.sh
echo "  校后：$(date '+%F %T')"
tail -1 /tmp/clock-sync.log 2>/dev/null | sed 's/^/  /'

echo
echo "===== 2. 装成开机自校 + 每 15 分钟校一次（systemd timer，以 root 跑）====="
echo sunrise | sudo -S -p "" tee /etc/systemd/system/clock-sync.service >/dev/null <<EOF
[Unit]
Description=Sync system clock via HTTP Date header (device has no NTP egress)
After=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash $V/linux/校时.sh
EOF
echo sunrise | sudo -S -p "" tee /etc/systemd/system/clock-sync.timer >/dev/null <<EOF
[Unit]
Description=Periodic clock sync (boot + every 15 min)

[Timer]
OnBootSec=90s
OnUnitActiveSec=15min
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF
echo sunrise | sudo -S -p "" systemctl daemon-reload
echo sunrise | sudo -S -p "" systemctl enable --now clock-sync.timer 2>&1 | tail -2
echo sunrise | sudo -S -p "" systemctl list-timers clock-sync.timer --no-pager 2>/dev/null | head -3

echo
echo "===== 3. 装「每 5 秒探测四台车」的服务 ====="
cp -f /tmp/dep-car_state.py $V/linux/car_state.py
python3 -c "compile(open('$V/linux/car_state.py',encoding='utf-8').read(),'x','exec'); print('  car_state.py compile OK')" || exit 1
echo "  --- 先手动跑一次看看能不能探测到 ---"
cd $V/linux && timeout 60 python3 car_state.py --once --verbose 2>&1 | sed 's/^/  /'

echo sunrise | sudo -S -p "" tee /etc/systemd/system/velaguard-cars.service >/dev/null <<EOF
[Unit]
Description=VelaGuard: probe 4 cars every 5s -> data/state.json (feeds the dashboard)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=sunrise
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=$V/linux
ExecStart=/usr/bin/python3 $V/linux/car_state.py --interval 5 --out $V/data/state.json
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
echo sunrise | sudo -S -p "" systemctl daemon-reload
echo sunrise | sudo -S -p "" systemctl enable --now velaguard-cars.service 2>&1 | tail -2
sleep 8
echo "  --- 服务状态 ---"
systemctl is-active velaguard-cars.service
pgrep -af car_state.py | head -2
echo "  --- 日志 ---"
echo sunrise | sudo -S -p "" journalctl -u velaguard-cars.service -n 5 --no-pager 2>/dev/null | tail -5

echo
echo "===== 4. 换界面 + start.sh（默认走 M1 数据源）====="
cp -f $V/preview/index.html /tmp/index.html.bak-$(date +%m%d_%H%M) 2>/dev/null
cp -f /tmp/dep-index.html $V/preview/index.html
cp -f /tmp/dep-start.sh $V/linux/start.sh && chmod +x $V/linux/start.sh
md5sum $V/preview/index.html
grep -c "src=file" $V/linux/start.sh | sed 's/^/  start.sh 里 src=file: /'

echo
echo "===== 5. 看 state.json 是不是每 5 秒在更新 ====="
for i in 1 2 3; do
  stat -c '  %y  %s 字节' $V/data/state.json
  sleep 5
done

echo
echo "===== 6. 重启看板（带 ?src=file，走实时数据源）====="
export DISPLAY=:0
export XAUTHORITY=$HOME/.Xauthority
pkill -f firefox 2>/dev/null
sleep 4
TS=$(date +%s)
cd $V
setsid nohup firefox --new-instance --kiosk \
  "http://127.0.0.1:8123/preview/index.html?src=file&v=$TS#kiosk" \
  > /tmp/vg-ff.log 2>&1 < /dev/null &
sleep 26
ps -eo pid,rss,args | grep "[f]irefox --new-instance" | head -1
