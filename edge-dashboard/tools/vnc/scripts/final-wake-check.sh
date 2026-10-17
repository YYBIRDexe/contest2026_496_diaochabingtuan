#!/bin/bash
echo "===== 唤醒词最终确认 ====="
grep -n '"keywords"\|"grammar"' /home/sunrise/voice_pipeline/wakeword.py | tail -2 | sed 's/^/  /'
grep -n '唤醒词：' /home/sunrise/voice_pipeline/唤醒.sh | head -2 | sed 's/^/  /'
grep -n '^PHRASE\|^KEYS\|^GRAMMAR' /home/sunrise/voice_pipeline/en_hit_rate.py | sed 's/^/  /'
echo
echo "===== 服务与引擎 ====="
systemctl is-active voice-assistant.service
ps -eo pid,args | grep -c '[w]akeword' | sed 's/^/  wakeword 进程数: /'
grep -E "模型就绪。唤醒词|解码候选" /tmp/voice_wake.log | tail -2 | sed 's/^/  /'
echo
echo "===== 最近一次唤醒命中 ====="
grep '听到唤醒词' /tmp/voice_wake.log | tail -1 | sed 's/^/  /'
echo
echo "===== 界面产物 ====="
md5sum /home/sunrise/velaguard/preview/index.html
grep -c 'Hello, openvela' /home/sunrise/velaguard/preview/index.html | sed 's/^/  界面里的 Hello 文案: /'
echo
echo "===== 两个实时服务 ====="
systemctl is-active velaguard-cars.service clock-sync.timer 2>/dev/null | paste -sd' ' - | sed 's/^/  cars \/ clock-sync: /'
date '+  设备时间: %F %T'
