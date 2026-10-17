#!/bin/bash
# 受控实验：僵尸 aplay 会不会被误判成「正在放音」
#
# 为什么要验：助手用 block=False 播报，aplay 播完没人回收 → 变成 <defunct>。
# 老代码用 pgrep 判断，僵尸也算「在放音」，于是桥每轮白等 40 秒才超时，
# 用户在界面上看到的就是「说完话半天没反应」。
python3 - <<'PY'
import subprocess, time, importlib.util, os

# 造一个僵尸：叫 aplay，立刻失败退出，父进程故意不 wait()
p = subprocess.Popen(["aplay", "-D", "definitely-not-a-device", "-q", "/nope.wav"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.2)
try:
    state = open("/proc/%d/stat" % p.pid).read().split()[2]
except OSError:
    state = "?"
print("子进程 %d 状态 = %s（Z 就是僵尸）" % (p.pid, state))
os.system("pgrep -af aplay | head -3")

spec = importlib.util.spec_from_file_location(
    "bridge", "/home/sunrise/velaguard/linux/speech-bridge.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print("_playback_running() ->", m._playback_running(),
      "（期望 False：僵尸不算在放音）")

# 对照：真放音时必须为 True
f = "/home/sunrise/voice_pipeline/tts_cache/" + sorted(
    os.listdir("/home/sunrise/voice_pipeline/tts_cache"))[0]
q = subprocess.Popen(["aplay", "-D", "plughw:0,1", "-q", f],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.8)
print("真在放音时 _playback_running() ->", m._playback_running(), "（期望 True）")
q.wait()
time.sleep(0.3)
print("放音结束后（进程已被 wait 回收）->", m._playback_running(), "（期望 False）")
p.wait()
PY

echo
echo "===== 桥里僵尸判断的代码 ====="
sed -n '/def _playback_running/,/^def /p' /home/sunrise/velaguard/linux/speech-bridge.py | head -30
