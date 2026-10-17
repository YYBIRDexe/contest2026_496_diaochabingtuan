#!/bin/bash
# 语音链路现场诊断：设备时钟、进程、服务、最近一轮语音、小车可达性
echo "===== 0. 设备时钟 ====="
date "+%Y-%m-%d %H:%M:%S %Z"
uptime -p

echo
echo "===== 1. 语音相关进程 ====="
ps -eo pid,etime,args | grep -E "[v]oice_button|[w]akeword|[a]record|[s]peech-bridge|[p]ython3 .*assistant" | head -12
echo "--- 计数（期望 3：助手+唤醒+arecord）---"
ps -eo args | grep -cE "[v]oice_button|[w]akeword"

echo
echo "===== 2. systemd 服务 ====="
systemctl is-active voice-assistant.service
systemctl status voice-assistant.service --no-pager 2>/dev/null | head -12

echo
echo "===== 3. 语音桥 / 界面服务 ====="
pgrep -af "speech-bridge.py" || echo "(桥未运行)"
ss -ltn 2>/dev/null | grep -E "8124|8123" || echo "(8124/8123 未监听)"
pgrep -af "firefox" | head -3 || echo "(无 firefox)"

echo
echo "===== 4. /tmp/voice_wake.log 尾部 60 行 ====="
tail -60 /tmp/voice_wake.log 2>/dev/null || echo "(无日志)"

echo
echo "===== 5. /tmp/voice_text.jsonl 最后 8 条 ====="
tail -8 /tmp/voice_text.jsonl 2>/dev/null || echo "(无记录)"

echo
echo "===== 6. 小车可达性（PC 段 .201-.204）====="
for ip in 201 202 203 204; do
  if timeout 2 bash -c "echo > /dev/tcp/192.168.1.$ip/9090" 2>/dev/null; then
    echo "192.168.1.$ip:9090 通"
  else
    echo "192.168.1.$ip:9090 不通"
  fi
done

echo
echo "===== 7. 已部署界面用哪个文件 ====="
ls -la /home/sunrise/velaguard/preview/index.html 2>/dev/null
md5sum /home/sunrise/velaguard/preview/index.html 2>/dev/null
echo "--- 页面里有没有 data-auto-bottom ---"
grep -c "data-auto-bottom" /home/sunrise/velaguard/preview/index.html 2>/dev/null
