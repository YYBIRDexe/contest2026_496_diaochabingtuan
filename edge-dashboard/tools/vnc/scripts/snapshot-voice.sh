#!/bin/bash
# 把设备上语音链路的关键文件取回本地做离线分析（只读，不改设备）
set -e
mkdir -p /tmp/vgsnap
cd /home/sunrise/voice_pipeline
for f in voice_button.py llm_intent.py 守护启动.sh nlp_parse.py tts.py vcmd.py check_cars.py 重启语音.sh start_voice.sh robots.json; do
  [ -f "$f" ] && cp -f "$f" /tmp/vgsnap/ 2>/dev/null || true
done
cp -f /tmp/voice_text.jsonl /tmp/vgsnap/ 2>/dev/null || true
cp -f /tmp/voice_wake.log /tmp/vgsnap/ 2>/dev/null || true
ls -l /tmp/vgsnap | head -20
echo "--- md5 ---"
md5sum /tmp/vgsnap/*.py /tmp/vgsnap/*.json 2>/dev/null
echo "--- 单元文件 ---"
cat /etc/systemd/system/voice-assistant.service
