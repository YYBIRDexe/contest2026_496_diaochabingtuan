#!/bin/bash
echo "===== 最终状态 ====="
date "+设备时间: %Y-%m-%d %H:%M:%S"
echo "--- 语音服务 ---"
systemctl is-active voice-assistant.service
ps -eo pid,etime,args | grep -E "[v]oice_button|[w]akeword|[a]record" | cut -c1-100
echo "--- 桥 ---"
pgrep -af speech-bridge.py
curl -s --max-time 8 http://127.0.0.1:8124/api/voice/state; echo
echo "--- 界面产物（应含 voice/records 轮询）---"
md5sum /home/sunrise/velaguard/preview/index.html
grep -c "voice/records" /home/sunrise/velaguard/preview/index.html
echo "--- 助手 said 补丁在位？（应=1）---"
grep -c 'rec\["said"\] = spoke\["reply"\]' /home/sunrise/voice_pipeline/voice_button.py
echo "--- 桥的新逻辑在位？（应=2）---"
grep -c "_start_wakeword_standalone" /home/sunrise/velaguard/linux/speech-bridge.py
grep -c 'startswith("Z")' /home/sunrise/velaguard/linux/speech-bridge.py
echo "--- 记录条数 ---"
wc -l < /tmp/voice_text.jsonl
