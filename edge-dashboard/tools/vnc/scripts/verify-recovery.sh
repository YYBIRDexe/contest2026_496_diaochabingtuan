#!/bin/bash
# 代理恢复后的连通性复核
echo "===== 设备经隧道出网 ====="
https_proxy=http://127.0.0.1:7890 curl -s -o /dev/null -w "  dashscope: %{http_code}  (%{time_total}s)\n" --max-time 15 https://dashscope.aliyuncs.com
https_proxy=http://127.0.0.1:7890 curl -s -o /dev/null -w "  deepseek : %{http_code}\n" --max-time 15 https://api.deepseek.com
echo
echo "===== 语音服务 ====="
systemctl is-active voice-assistant.service
ps -eo pid,etime,args | grep -E "[v]oice_button|[w]akeword|[a]record" | cut -c1-90
echo
echo "===== 唤醒词配置（应只有 hi openvela）====="
grep -A1 '"keywords"' /home/sunrise/voice_pipeline/wakeword.py | grep keywords | tail -2
echo
echo "===== 最近一轮语音记录 ====="
tail -2 /tmp/voice_text.jsonl | cut -c1-200
