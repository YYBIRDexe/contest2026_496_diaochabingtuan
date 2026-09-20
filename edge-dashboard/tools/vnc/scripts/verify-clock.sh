#!/bin/bash
# 部署修好的校时脚本并验证（注意：PowerShell 里别内联反引号/$( )，一律走脚本文件）
set -u
V=/home/sunrise/velaguard

cp -f /tmp/dep-clocksync.sh $V/linux/校时.sh
chmod +x $V/linux/校时.sh

echo "校前：$(date '+%F %T')"
echo sunrise | sudo -S -p "" bash $V/linux/校时.sh
echo "校后：$(date '+%F %T')"
echo "--- 日志 ---"
tail -2 /tmp/clock-sync.log | sed 's/^/  /'

echo
echo "===== 与真实时间对比 ====="
hdr=$(curl -k -sI --max-time 10 -o /dev/null -D - https://dashscope.aliyuncs.com 2>/dev/null \
      | tr -d '\r' | sed -n 's/^[Dd]ate: //p' | head -1)
echo "  设备：$(date '+%F %T')"
echo "  真实：$(TZ=Asia/Shanghai date -d "$hdr" '+%F %T' 2>/dev/null)（来自 HTTP Date 头）"

echo
echo "===== 定时器（开机 90 秒后 + 每 15 分钟）====="
echo sunrise | sudo -S -p "" systemctl list-timers clock-sync.timer --no-pager 2>/dev/null | head -2
