#!/bin/bash
# 交接用：把设备上「不在本仓库里」的关键文件抓成一份快照
set -u
S=/tmp/vgsnap2
rm -rf $S && mkdir -p $S/voice_pipeline $S/systemd $S/velaguard

cd /home/sunrise/voice_pipeline || exit 1
for f in voice_button.py wakeword.py nlp_parse.py vcmd.py vcmd_actions.json agent_slow.py \
         llm_intent.py tts.py check_cars.py check_battery.py robots.json \
         唤醒.sh 守护启动.sh 重启语音.sh 选代理.sh start_voice.sh en_hit_rate.py \
         _patch_wake_strict.py _patch_said_reply.py _patch_battery_intent.py \
         _patch_agent_battery.py _patch_voice_stop.py _fix_global_scope.py _fix_mic_retry_v2.py; do
  [ -f "$f" ] && cp -f "$f" $S/voice_pipeline/ 2>/dev/null
done

cp -f /etc/systemd/system/voice-assistant.service $S/systemd/ 2>/dev/null
cp -f /etc/x3m-proxy.env $S/systemd/x3m-proxy.env.txt 2>/dev/null

cd /home/sunrise/velaguard 2>/dev/null && {
  ls -la > $S/velaguard/树.txt 2>/dev/null
  find . -maxdepth 2 -type f -printf '%p\n' 2>/dev/null | sort > $S/velaguard/文件清单.txt
  cp -f linux/*.sh linux/*.py $S/velaguard/ 2>/dev/null
  cp -f preview/index.html $S/velaguard/index.html.snapshot 2>/dev/null
}

# 自启动与桌面配置
ls -1 $HOME/.config/autostart/ > $S/velaguard/autostart-项.txt 2>/dev/null
cat $HOME/.config/autostart/velaguard*.desktop > $S/velaguard/autostart内容.txt 2>/dev/null

# 现场证据
tail -60 /tmp/voice_text.jsonl > $S/现场-语音记录尾部.jsonl 2>/dev/null
tail -40 /tmp/voice_wake.log > $S/现场-语音日志尾部.log 2>/dev/null
sha256sum --tag $S/voice_pipeline/* 2>/dev/null > $S/voice_pipeline/校验和.txt

echo "===== 快照内容 ====="
find $S -type f | sort
echo
echo "===== 文件大小合计 ====="
du -sh $S
