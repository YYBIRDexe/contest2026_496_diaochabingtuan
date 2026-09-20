#!/bin/bash
# 校时.sh — 用 HTTP 响应头里的时间给这块板子校时。
#
# 为什么不用 NTP：设备没有公网出口，唯一的路是笔记本上的 HTTP 代理，
# 而 NTP 走的是 UDP 123 —— 代理转发不了。所以改用"HTTP Date 头"：
#
#   https_proxy=http://127.0.0.1:7890 curl -sI https://dashscope.aliyuncs.com
#     → Date: Sat, 19 Sep 2026 05:20:15 GMT
#   date -s "Sat, 19 Sep 2026 05:20:15 GMT"      # GNU date 认 RFC1123
#
# 这块板子的 RTC 已经坏了（显示 1970-01-01），所以**每次开机都要校**，
# 而且运行中也会慢慢漂 —— 由 clock-sync.timer 定时调用本脚本（以 root 跑）。
#
# 用法：sudo bash 校时.sh          （systemd 里就是 /bin/bash 直接跑）
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 代理环境：先读系统配置，再让"选代理.sh"挑一个能用的（和唤醒.sh 同样的做法）
[ -r /etc/x3m-proxy.env ] && . /etc/x3m-proxy.env
#
# ⚠️ 选代理.sh 住在 /home/sunrise/voice_pipeline，**不一定和本脚本同目录**
#   （本脚本装在 velaguard/linux 下）。漏了这句的后果是：没有代理 → curl 出不去
#   → 四个站点全拿不到 Date 头 → 校时静默失败（实测踩过，日志里只写"代理不通"）。
for cand in "$HERE/选代理.sh" /home/sunrise/voice_pipeline/选代理.sh; do
  if [ -r "$cand" ]; then
    . "$cand"
    break
  fi
done

LOG=/tmp/clock-sync.log
log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

# 取时间：多试几个站点，任何一个返回 Date 头就行。
#
# ⚠️ 必须带 -k（跳过证书校验）：时钟偏得离谱时（这块板子的 RTC 坏了，开机
#    可能停在几天前甚至 1970），HTTPS 证书会"尚未生效/已过期"而握手失败 ——
#    于是拿不到 Date 头，永远校不了时。这是个鸡生蛋问题，只能先不看证书。
#    我们只要响应头里的时间，不传任何数据，-k 在这里是可接受的。
for url in https://dashscope.aliyuncs.com https://www.baidu.com https://api.deepseek.com http://www.baidu.com; do
  hdr=$(curl -k -sI --max-time 8 -o /dev/null -D - "$url" 2>/dev/null | tr -d '\r' | sed -n 's/^[Dd]ate: //p' | head -1)
  if [ -n "$hdr" ]; then
    before=$(date '+%F %T')
    if date -s "$hdr" >/dev/null 2>&1; then
      hwclock -w >/dev/null 2>&1 || true     # 顺手写回 RTC（能写就写）
      log "校时成功：$before -> $(date '+%F %T')（来源 $url）"
      exit 0
    fi
    log "取到了时间但设置失败：$hdr"
  fi
done

log "校时失败：四个站点都没拿到 Date 头（代理不通？）"
exit 1
