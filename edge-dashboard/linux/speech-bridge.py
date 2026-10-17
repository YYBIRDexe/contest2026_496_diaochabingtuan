#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
speech-bridge —— 给 VelaGuard 看板提供离线语音识别与提示音。

为什么需要它：
  Firefox 的 Web Speech API 依赖云端识别，本设备无外网，不可用。
  但设备上已装好 vosk 离线识别库与中文模型，所以改成
  「浏览器/服务端录音 → 本地 vosk 识别 → 返回文本」的闭环。

能力与限制（实测结论，务必如实呈现给用户，不要假装）：
  - 识别：vosk 中文模型 /home/sunrise/vosk-model-small-cn-0.22 加载正常。
  - 录音：设备节点存在、I2S 有时钟活动，但**采集到的音频是空的**
    （parecord 只产出 44 字节纯 WAV 头，0 帧）。
    这是硬件/接线层面的问题，软件无法修复。
    因此 /api/record 会如实报告 silent=true，前端据此提示用户改用预设指令。

端点：
  GET  /api/health         → 能力探测（模型是否可加载、录音是否可用）
  GET  /api/voice/state    → 设备语音服务进程状态
  GET  /api/voice/records  → 增量拉取对话记录（界面轮询用，since=<seq>）
  POST /api/voice/start    → 两段式第一段：提示音 + 立即开始录音
  POST /api/voice/stop     → 两段式第二段：立即结束录音（结果可稍后轮询）
  POST /api/voice/talk     → 一次性触发一轮并等结果（旧接口，保留兜底）
  POST /api/record         → 录音并识别，返回 { ok, text, silent, reason }
  POST /api/beep           → 播放提示音（「请讲」的听觉反馈）

⚠️ 服务必须是**多线程**的（ThreadingHTTPServer）。原因：界面每 1 秒轮询一次
   /api/voice/records，而 /api/voice/stop 这类请求会阻塞若干秒。单线程时
   轮询会排在它后面 —— 现象就是「语音先响、文字过十秒才出来」（实测踩过）。

用法：
  python3 speech-bridge.py [--port 8124] [--seconds 4]

依赖：python3、vosk（已装）、parecord/paplay（已装）
"""

import argparse
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:                                             # Python 2 兜底
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer as ThreadingHTTPServer

# ---------------------------------------------------------------- 配置

CN_MODEL = "/home/sunrise/vosk-model-small-cn-0.22"
EN_MODEL = "/home/sunrise/vosk-model-small-en-us-0.15"
SOURCE = "alsa_input.platform_soc_sndcard_5.stereo-fallback"

# 静音判定阈值：峰值低于此值视为没采到声音
SILENCE_PEAK = 200

# ---------------------------------------------------------------- 关于约束解码
#
# ⚠️ 不要对**整句指令**用约束解码 —— 实测会更差。
#
# 厂商在 wakeword.py 里记的「约束解码 8/8 胜出」是针对**短唤醒词**
# （「小陈同志」4 个字）测的。我把同样的手法套到整句指令上，结果崩了：
#
#   TTS 音频「...小车向右平移」  自由解码: '第一步 以后 车 二 好车 和 三号 车 向右 平移'
#                              约束解码: '[unk] [unk] 项 [unk]'
#   TTS 音频「...小车前进」      自由解码: '第二 不 二号 车 和 四 好车 前进'
#                              约束解码: '[unk] 哪 全 检'
#
# 原因：词表约束会把长句强行切碎成词表里的字，产生大量 [unk]。
# 所以本服务对**整句指令一律用自由解码**；约束解码只适用于唤醒词那种
# 极短输入（Wakeword 的活由设备上的 wakeword.py 干，不归本服务）。
#
# 下面这份词表仅作参考保留，不在识别路径中使用。
CN_GRAMMAR_WORDS = [
    "开 始 本 轮 巡 检",
    "现 在 哪 些 区 域 没 查 完",
    "展 项 区 为 什 么 阻 塞",
    "取 消 全 部 未 完 成 任 务",
    "生 成 巡 检 报 告",
    "小 陈 同 志",
    "[unk]",
]

_model = None
_model_error = None
_model_lock = threading.Lock()


def log(msg):
    sys.stderr.write("speech-bridge: %s\n" % msg)
    sys.stderr.flush()


# ---------------------------------------------------------------- 模型

def get_model():
    """惰性加载 vosk 中文模型（加载耗时较长，只做一次）。"""
    global _model, _model_error
    with _model_lock:
        if _model is not None:
            return _model
        if _model_error is not None:
            return None
        try:
            from vosk import Model, SetLogLevel
            SetLogLevel(-1)
            path = CN_MODEL if os.path.isdir(CN_MODEL) else EN_MODEL
            if not os.path.isdir(path):
                _model_error = "未找到 vosk 模型目录"
                return None
            log("加载模型 %s …" % path)
            _model = Model(path)
            log("模型加载完成")
            return _model
        except Exception as e:                                  # noqa: BLE001
            _model_error = str(e)
            log("模型加载失败: %s" % e)
            return None


# ---------------------------------------------------------------- 音频

def find_source():
    """找出可用的 PulseAudio 录音源。"""
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sources"],
                                      stderr=subprocess.DEVNULL,
                                      timeout=10).decode("utf-8", "replace")
    except Exception:                                           # noqa: BLE001
        return None
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and "monitor" not in parts[1]:
            return parts[1]
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            return parts[1]
    return None


def record_wav(path, seconds):
    """
    录音到 path。返回 (ok, reason)。

    ⚠️ 踩过的坑（务必保留这段说明）：
      1. **不要用 parecord 走 PulseAudio**：本设备 PulseAudio 只把这张声卡当成
         输入设备、且常常拿不到数据；而且 parecord 会**卡住不退**，独占总 ALSA 设备，
         之后任何录音都报 "Device or resource busy"。
      2. **必须用 16k 单声道直连 ALSA**：内核侧该卡的实际参数是
         1ch/16000Hz/S16_LE。曾按 2ch/48000Hz 请求，结果 0 帧。
      3. **录音前先清残留**：设备上运行着 voice_pipeline 的 wakeword.py，
         它用 arecord 常驻占用麦克风。不清掉就抢不到设备。
    """
    # 清掉可能残留的录音进程（否则设备被独占）
    for pat in ("arecord", "parecord"):
        try:
            subprocess.run(["pkill", "-9", "-f", pat],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
        except Exception:                                       # noqa: BLE001
            pass
    time.sleep(0.6)

    # 优先直连 ALSA 硬件；用与厂商管线一致的默认设备
    attempts = [
        ("default", ["arecord", "-D", "default", "-c", "1", "-r", "16000",
                     "-f", "S16_LE", "-d", str(seconds), path]),
        ("hw:0,0", ["arecord", "-D", "hw:0,0", "-c", "1", "-r", "16000",
                    "-f", "S16_LE", "-d", str(seconds), path]),
    ]
    errors = []
    for name, cmd in attempts:
        try:
            r = subprocess.run(cmd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=seconds + 15)
            if r.returncode == 0 and os.path.isfile(path) \
                    and os.path.getsize(path) > 44:
                log("录音完成（%s，%d 字节）" % (name, os.path.getsize(path)))
                return True, ""
            err = r.stderr.decode("utf-8", "replace").strip()[:100]
            errors.append("%s: rc=%d %s" % (name, r.returncode, err))
        except Exception as e:                                  # noqa: BLE001
            errors.append("%s: %s" % (name, e))

    return False, "；".join(errors)


def analyze_wav(path):
    """读取 wav，返回 (frames, peak, avg)。"""
    try:
        w = wave.open(path)
    except Exception as e:                                      # noqa: BLE001
        return 0, 0, 0
    n = w.getnframes()
    if n == 0:
        return 0, 0, 0
    data = w.readframes(n)
    count = len(data) // 2
    if count == 0:
        return n, 0, 0
    samples = struct.unpack("<%dh" % count, data)
    peak = max(abs(x) for x in samples)
    avg = sum(abs(x) for x in samples) // count
    return n, peak, avg


def recognize(path):
    """
    用 vosk 离线中文模型识别 wav，返回 (text, err)。

    实测结论（务必保留，避免以后重复排查）：
      · vosk 中文模型本身工作正常 —— 对 TTS 播放音频能稳定出字，例如
        7111270e55c34a6c.wav → '第一步 以后 车 二 好车 和 三号 车 向右 平移'
      · 但**现场麦克风录音识别不出来**：录音确实有声（峰值 2891~10816），
        但平均电平只有约 1104，接近本底噪声，信噪比不足以识别。
        这是声学/硬件问题（麦克风增益偏低或说话距离太远），不是软件能修的。
        → 因此界面必须如实告知用户，不能假装识别成功。
    """
    model = get_model()
    if model is None:
        return None, _model_error or "模型不可用"
    try:
        from vosk import KaldiRecognizer
        w = wave.open(path)
        ch = w.getnchannels()
        rate = w.getframerate()
        data = w.readframes(w.getnframes())

        # vosk 只接受 16bit 单声道；立体声需要抽取左声道
        if ch > 1:
            count = len(data) // 2
            samples = struct.unpack("<%dh" % count, data)
            mono = samples[0::ch]
            data = struct.pack("<%dh" % len(mono), *mono)

        rec = KaldiRecognizer(model, rate)
        for i in range(0, len(data), 4000):
            rec.AcceptWaveform(data[i:i + 4000])
        res = json.loads(rec.FinalResult())
        text = (res.get("text") or "").strip()
        log("识别(自由解码): %r" % text)
        return text, ""
    except Exception as e:                                      # noqa: BLE001
        return None, str(e)


def play_beep(kind="ready"):
    """
    播放提示音。

    ⚠️ 不能用 paplay：本设备的 PulseAudio **没有识别到真实播放设备**，
    只挂了一个 auto_null（Dummy Output）虚拟空设备，
    paplay 会返回成功（退出码 0）但声音被丢进虚空 —— 用户完全听不到。
    实测：
        pactl list short sinks → 只有 auto_null module-null-sink
        但硬件实际存在 card 0 device 1 (CS4344-1)，内核日志
        "CS4344 <-> a5007000.i2s mapping ok"

    所以直接走 ALSA 硬件设备播放，并在失败时如实上报，不假装成功。

    提示音种类（和 voice_button.py 的约定一致，用户听两次就记住了）：
        listen / ready  上行双音 1200→1600 Hz  「开始听」
        stop            下行双音 1600→1200 Hz  「结束」
        done            单声高音 1800 Hz       「出结果了」
    """
    import math

    if kind in ("listen", "ready", "start"):
        tones = [(1200, 0.11), (1600, 0.11)]
    elif kind in ("stop", "end"):
        tones = [(1600, 0.11), (1200, 0.11)]
    elif kind == "done":
        tones = [(1800, 0.13)]
    else:
        # 兜底：原来那种单声提示音
        tones = [(520, 0.25)]

    rate = 16000
    path = os.path.join(tempfile.gettempdir(), "vg-beep-%s.wav" % kind)

    try:
        with wave.open(path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            frames = bytearray()
            fade = int(rate * 0.012)
            gap = int(rate * 0.04)
            for freq, dur in tones:
                total = int(rate * dur)
                for i in range(total):
                    # 每段单独做淡入淡出，避免切换音高时爆音
                    env = 1.0
                    if i < fade:
                        env = i / float(fade)
                    elif i > total - fade:
                        env = (total - i) / float(fade)
                    v = int(18000 * env * math.sin(2 * math.pi * freq * i / rate))
                    frames += struct.pack("<h", v)
                frames += b"\x00\x00" * gap
            w.writeframes(bytes(frames))
    except Exception as e:                                      # noqa: BLE001
        log("生成提示音失败: %s" % e)
        return False, "生成失败: %s" % e

    # 依次尝试可用的播放途径，返回第一个成功的
    attempts = [
        ("aplay-hw", ["aplay", "-D", "plughw:0,1", "-q", path]),
        ("aplay-default", ["aplay", "-q", path]),
        ("paplay", ["paplay", path]),
    ]
    errors = []
    for name, cmd in attempts:
        try:
            r = subprocess.run(cmd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=10)
            if r.returncode == 0:
                log("提示音已播放（%s）" % name)
                return True, name
            errors.append("%s: %s" % (name, r.stderr.decode("utf-8", "replace").strip()[:80]))
        except Exception as e:                                  # noqa: BLE001
            errors.append("%s: %s" % (name, e))

    msg = "；".join(errors)
    log("提示音播放失败: %s" % msg)
    return False, msg


def audio_route():
    """
    报告当前播放路由状况，供 /api/health 暴露。
    重点是提醒：PulseAudio 若只有 auto_null，则 paplay 类是"假成功"。
    """
    info = {"sinks": [], "realSink": False}
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sinks"],
                                      stderr=subprocess.DEVNULL,
                                      timeout=10).decode("utf-8", "replace")
        info["sinks"] = [l.split("\t")[1] for l in out.splitlines() if "\t" in l]
        info["realSink"] = any("null" not in s for s in info["sinks"])
    except Exception:                                           # noqa: BLE001
        pass
    return info


# ---------------------------------------------------------------- 设备语音服务桥
#
# 为什么要桥接设备上那套 voice_pipeline，而不是自己录音识别：
#   设备上已有完整链路（提示音 → VAD 自动判句尾 → 云端 ASR → 意图解析 →
#   下发小车 → TTS 回报），实测端到端 1.5 秒，而且有 13 条预合成的报错话术。
#   自己重做一遍既慢又丢功能。界面按钮只要**可靠地触发它并取回结果**即可。
#
# 两个必须处理的坑：
#   1. 唤醒引擎 wakeword.py 常驻占用麦克风，此时手动触发 FIFO 会被
#      「麦克风被占用」丢弃（voice_pipeline 文档明确记录）。所以触发前先停
#      唤醒引擎，触发后再拉起。
#   2. 结果是异步产生的，要从 /tmp/voice_text.jsonl 里按时间戳取回来。
VOICE_DIR = "/home/sunrise/voice_pipeline"
VOICE_LOG = "/tmp/voice_text.jsonl"
VOICE_SERVICE = "voice-assistant.service"


def _sh(cmd, timeout=20):
    """跑一条命令，返回 (rc, stdout, stderr)。"""
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout)
        return (p.returncode,
                p.stdout.decode("utf-8", "replace").strip(),
                p.stderr.decode("utf-8", "replace").strip())
    except Exception as e:                                      # noqa: BLE001
        return (-1, "", str(e))


def voice_state():
    """报告设备语音服务的进程状态。"""
    st = {"wakeword": False, "assistant": False, "recording": False,
          "service": "unknown"}
    rc, out, _ = _sh(["pgrep", "-f", "wakeword.py"])
    st["wakeword"] = (rc == 0 and bool(out))
    rc, out, _ = _sh(["pgrep", "-f", "voice_button.py"])
    st["assistant"] = (rc == 0 and bool(out))
    rc, out, _ = _sh(["pgrep", "-f", "arecord"])
    st["recording"] = (rc == 0 and bool(out))
    rc, out, _ = _sh(["systemctl", "is-active", VOICE_SERVICE])
    st["service"] = out or "unknown"
    return st


def _pause_wakeword():
    """
    暂停唤醒引擎，把麦克风让出来给助手录音。

    不停掉它的话，手动触发必然以「麦克风被占用」失败 —— 这是实测结论。
    返回 True 表示现在（应该）可以录了。
    """
    _sh(["pkill", "-9", "-f", "wakeword.py"], timeout=10)
    _sh(["pkill", "-9", "-f", "arecord"], timeout=10)
    time.sleep(1.2)
    return True


def _wakeword_up():
    rc, out, _ = _sh(["pgrep", "-f", "wakeword.py"])
    return rc == 0 and bool(out.strip())


def _resume_wakeword():
    """
    把唤醒引擎还回去（触发前被 _pause_wakeword 停掉了）。

    ⚠️ 顺序很重要：**先试着自己把唤醒引擎拉起来，不要一上来就杀服务**。

    上一版是「kill 掉服务主进程，指望 systemd 的 Restart=always 拉回来」，
    两个实测问题：
      1. 服务单元一旦处于 failed（MainPID 早没了），kill 完就没人再拉起 ——
         用户喊「hi openvela」永远没反应，界面还看不出原因；
      2. 更危险的是：现在界面只等 8 秒就返回（不等云端识别），
         这条路会在**一轮还在识别中**被调用 —— 杀服务等于把正在跑的
         那一轮（云端 ASR）一起杀掉，用户就真的什么结果都拿不到了。

    所以现在的策略：唤醒引擎已经在了就什么都不做；不在就手动拉起
    （环境变量照抄 唤醒.sh：先载入代理配置，再让 选代理.sh 选一个能用的）；
    实在起不来，才退回到「杀主进程让 systemd 重启」这条老路。
    """
    if _wakeword_up():
        return True

    if _start_wakeword_standalone():
        return True

    rc, pid, _ = _sh(["systemctl", "show", VOICE_SERVICE, "-p", "MainPID", "--value"])
    if pid and pid.strip() not in ("", "0"):
        _sh(["kill", "-9", pid.strip()], timeout=10)
        log("手动拉起唤醒引擎失败，改为重启整个语音服务")
        return True
    log("唤醒引擎没能恢复（服务未托管且手动拉起失败）")
    return False


def _start_wakeword_standalone():
    """
    手动拉起唤醒引擎（systemd 不管用时的兜底）。

    只起 wakeword.py，**不起** 唤醒.sh —— 后者会连带 exec 一个助手进程，
    和已经在跑的那个抢麦克风。环境变量照抄 唤醒.sh 的做法：
    先载入 /etc/x3m-proxy.env，再让 选代理.sh 选出能用的代理。
    """
    if _wakeword_up():
        return True
    script = (
        "cd $HOME; "
        "set -a; "
        "[ -r /etc/x3m-proxy.env ] && . /etc/x3m-proxy.env; "
        "[ -r {d}/选代理.sh ] && . {d}/选代理.sh; "
        "set +a; "
        "setsid nohup python3 {d}/wakeword.py --fifo /tmp/voice_trigger --lang ${{WAKE_LANG:-en}} "
        ">> /tmp/voice_wake.log 2>&1 < /dev/null &"
    ).format(d=VOICE_DIR)
    rc, out, err = _sh(["bash", "-c", script], timeout=20)
    time.sleep(3.0)
    ok = _wakeword_up()
    log("手动拉起唤醒引擎：%s" % ("成功" if ok else "失败 %s" % (err or out)))
    return ok


def _playback_running():
    """
    板子上是否**真的**正在放音（aplay/paplay 在跑）。

    ⚠️ 必须排掉僵尸进程（state=Z）。助手用 say_text(..., block=False) 播报，
    它 Popen 出来的 aplay 播完后**没人回收**，会一直挂在进程表里显示为
    `<defunct>`。`pgrep aplay` 照样能匹配到它 —— 于是这里永远返回 True，
    _wait_playback_done() 每轮都白等 40 秒才超时，界面上的表现就是
    「说完话半天没有任何反应」。实测踩过：PID 79196 `[aplay] <defunct>`。
    """
    for pat in ("aplay", "paplay"):
        rc, out, _ = _sh(["pgrep", "-f", pat])
        if rc != 0 or not out.strip():
            continue
        for pid in out.split():
            # stat 的第一列就是进程状态；Z=僵尸，不算在放音
            rc2, st, _ = _sh(["ps", "-o", "stat=", "-p", pid.strip()])
            if rc2 == 0 and st.strip() and not st.strip().startswith("Z"):
                return True
    return False


def _wait_playback_done(max_wait=20):
    """
    等语音播报真正放完再返回。

    为什么必须等：助手用 say_text(..., block=False) 播报（Popen 后立即返回），
    紧接着就写 /tmp/voice_text.jsonl。桥若一看到记录就重启服务，
    会把还在出声的 aplay 一起杀掉 —— 现象就是「语音回复刚出现就停止」。
    这里改为轮询：先等它开始（最多 3 秒），再等它结束。

    时间不宜长：这几秒是**加在用户等待上的**（界面在等这个返回值）。
    助手是在写记录之前就发起播报的，所以正常情况下这里立刻就能看到 aplay。
    """
    started = False
    begin = time.time()

    # 阶段一：等播报开始（不是每轮都有播报，等不到就放过）
    while time.time() - begin < 3:
        if _playback_running():
            started = True
            break
        time.sleep(0.2)

    if not started:
        return False

    # 阶段二：等播报结束
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if not _playback_running():
            log("语音播报已放完")
            return True
        time.sleep(0.4)

    log("语音播报等待超时（%d 秒），仍然继续恢复服务" % max_wait)
    return True


def _log_size():
    try:
        return os.path.getsize(VOICE_LOG) if os.path.isfile(VOICE_LOG) else 0
    except OSError:
        return 0


def _last_record():
    """取 voice_text.jsonl 的最后一条记录。"""
    try:
        with open(VOICE_LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            back = min(size, 65536)
            f.seek(size - back)
            lines = f.read().decode("utf-8", "replace").strip().splitlines()
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except ValueError:
                    continue
    except OSError:
        pass
    return None


def _read_records():
    """
    把 /tmp/voice_text.jsonl 读成带序号（seq）的记录列表。

    seq 就是行号（从 1 开始），文件只追加不重写，所以它天然单调递增，
    可以当「游标」用：界面记住上次看到哪条，下次只要 since>seq 的新记录。

    ⚠️ 一轮可能写两行（先 slow_fail 再 error/said），所以只把「最终行」
    算作一条记录，否则界面上会出现两条一模一样的「你」气泡。
    """
    out = []
    try:
        with open(VOICE_LOG, encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f, 1):
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                # 中间态：只说明慢路径判不了，真正的结论在下一行
                if "slow_fail" in rec and not rec.get("error"):
                    continue
                out.append({
                    "seq": idx,
                    "ts": rec.get("ts") or "",
                    "text": (rec.get("text") or "").strip(),
                    "said": (rec.get("said") or "").strip(),
                    "error": rec.get("error") or "",
                    "detail": rec.get("detail") or "",
                    "intent": rec.get("intent") or "",
                    "source": rec.get("source") or "",
                    "executed": rec.get("executed"),
                })
    except OSError:
        pass
    return out


def _resume_wakeword_async():
    """
    在后台把唤醒引擎还回去，**不要**让接口等它。

    为什么：恢复动作要起进程、加载 vosk 模型，实测 3~5 秒。这段如果放在
    请求路径上，界面上「说话」按钮就会一直停在"识别中"、点不动。
    （只还唤醒引擎、不杀服务，所以放后台是安全的。）
    """
    t = threading.Thread(target=_resume_wakeword, name="resume-wakeword")
    t.daemon = True
    t.start()
    return t


def _collect_result(before_size, wait_sec, wait_playback=True):
    """
    等设备写出一条新记录，取回结果并善后。

    ⚠️ wait_playback 只在**旧的一次性接口** /api/voice/talk 里为 True。
    两段式的 /api/voice/stop 传 False —— 因为界面现在靠轮询拿结果，
    这个请求越早返回越好；等播报放完纯粹是白等（那 3~20 秒会顶在界面脸上）。

    结果迟到没关系，界面会通过 /api/voice/records 轮询补上。
    """
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        time.sleep(0.25)
        if _log_size() > before_size:
            rec = _last_record()
            if rec:
                if wait_playback:
                    _wait_playback_done()
                _resume_wakeword_async()
                recs = _read_records()
                return {
                    "ok": True,
                    "stage": "done",
                    "seq": recs[-1]["seq"] if recs else 0,
                    "ts": rec.get("ts") or "",
                    "text": rec.get("text") or "",
                    "said": rec.get("said") or "",
                    "error": rec.get("error") or "",
                    "detail": rec.get("detail") or "",
                    "intent": rec.get("intent") or "",
                    "executed": rec.get("executed"),
                }

    _resume_wakeword_async()
    return {"ok": False, "stage": "timeout",
            "reason": "等不到结果（%d 秒）。可能是唤醒引擎没让出麦克风，"
                      "或云端不通。" % wait_sec}


def trigger_voice(wait_sec=45):
    """
    触发设备的一轮语音交互，并等结果回来（一次性、阻塞式）。

    流程：停唤醒引擎（让出麦克风）→ 写 FIFO → 轮询日志 → 返回结果。
    返回 dict：{ok, text, said, error, detail, stage}

    这是「一发一收」的老接口，供不想分两步调用的场景使用。
    界面上的「按住说话」走两段式（voice_start / voice_stop），
    这样第二次按下才能真正做到**立即**结束录音，见下面的说明。
    """
    before_size = _log_size()
    st = voice_state()
    if not st["assistant"]:
        return {"ok": False, "stage": "no-service",
                "reason": "设备语音服务未运行（voice-assistant.service）"}

    _pause_wakeword()

    rc, out, err = _sh(["bash", "-c", "echo go > /tmp/voice_trigger"])
    if rc != 0:
        _resume_wakeword()
        return {"ok": False, "stage": "trigger-failed",
                "reason": "写入 /tmp/voice_trigger 失败: %s" % (err or out)}
    log("已触发设备语音交互，等待结果（最多 %d 秒）" % wait_sec)
    return _collect_result(before_size, wait_sec)


# ---------------------------------------------------------------- 两段式交互
#
# 为什么要把一轮拆成 start / stop 两段：
#
#   原来只有一个 /api/voice/talk，界面「按住说话」第二次按下时，
#   服务端其实**什么都做不了** —— 录音循环卡在 arecord 的 read() 上，
#   只能等 VAD 自己判到句尾（默认 0.8 秒静音，实测常更久）。
#   用户看到的现象就是「按了没反应，还得再等一两秒」。
#
#   现在：
#     /api/voice/start  立刻让出麦克风 + 发提示音 + 触发录音，**马上返回**，
#                       界面当场变状态，不用等 1.2 秒才亮。
#     /api/voice/stop   给 voice_button.py 发 SIGUSR1 → 录音循环立即收尾
#                       → 送云端识别 → 播报 → 取回结果。
#
#   两段之间靠一个全局会话记录（_SESSION）衔接，不依赖客户端再传参数。
_SESSION = {"active": False, "beforeSize": 0, "t0": 0.0, "stage": ""}


def _voice_pid():
    rc, out, _ = _sh(["pgrep", "-f", "voice_button.py"])
    if rc != 0 or not out.strip():
        return None
    return out.strip().splitlines()[0].strip()


def voice_start():
    """第一段：让出麦克风 → 提示音 → 开始录音。立即返回，不等结果。"""
    st = voice_state()
    if not st["assistant"]:
        return {"ok": False, "stage": "no-service",
                "reason": "设备语音服务未运行（voice-assistant.service）"}

    # 先把上一轮的残留清掉，避免第二次按开始录音时老记录还在
    _SESSION["active"] = False
    _SESSION["beforeSize"] = _log_size()

    # 1.2 秒：wakeword 一直在读麦克风，不等它真正退出，助手开 arecord 会
    # 报「麦克风被占用」。这是实测值，不要再调小。
    _pause_wakeword()

    pid = _voice_pid()
    if pid is None:
        _resume_wakeword()
        return {"ok": False, "stage": "no-service",
                "reason": "助理进程没起来（voice_button.py）"}

    rc, out, err = _sh(["bash", "-c", "echo go > /tmp/voice_trigger"])
    if rc != 0:
        _resume_wakeword()
        return {"ok": False, "stage": "trigger-failed",
                "reason": "写入 /tmp/voice_trigger 失败: %s" % (err or out)}

    _SESSION.update({"active": True, "beforeSize": _log_size(),
                     "t0": time.time(), "stage": "recording"})
    log("两段式：已开始录音（pid=%s）" % pid)
    return {"ok": True, "stage": "recording", "pid": pid}


def voice_stop(wait_sec=60):
    """第二段：立即结束录音 → 送云端 → 等结果回来。"""
    if not _SESSION.get("active"):
        '''
        没走过 start 就直接 stop（例如页面刚打开、或上一轮已经收尾）。
        这时不假装成功，如实说明，让界面提示用户先按一次「说话」。
        '''
        return {"ok": False, "stage": "not-started",
                "reason": "还没有开始录音，请先按一次「说话」"}

    pid = _voice_pid()
    killed = False
    if pid:
        # SIGUSR1 由 _patch_voice_stop.py 打进去的处理器接住，
        # 循环会把已录到的音频完整写成 wav 并立刻送去识别。
        rc, _, _ = _sh(["kill", "-USR1", pid])
        killed = (rc == 0)
        log("两段式：已请求立即结束录音（pid=%s, 信号送达=%s）" % (pid, killed))

    _SESSION["active"] = False
    _SESSION["stage"] = "recognizing"

    # wait_playback=False：界面靠轮询拿结果，这个请求不必等播报放完
    res = _collect_result(_SESSION.get("beforeSize") or 0, wait_sec, wait_playback=False)
    res["stopped"] = killed
    if not killed and res.get("ok"):
        # 信号没送到，但结果还是出来了 —— 说明 VAD 自己收了尾。
        # 这不是失败，如实标注出来，便于排查。
        res["stopMode"] = "vad-auto"
    elif killed:
        res["stopMode"] = "manual"

    '''
    【重要】等不到结果 ≠ 失败。
    云端 ASR 实测可能要 40 秒到几分钟，界面若在这里死等，用户看到的就是
    「按完了没有任何反应」。所以改成：录音确实已经结束（信号送达）时，
    如实回一个「正在识别」，结果由界面轮询 /api/voice/records 补上。
    '''
    if not res.get("ok") and killed:
        return {"ok": True, "stage": "recognizing", "stopped": True,
                "stopMode": "manual", "text": "", "said": "",
                "reason": "录音已结束，正在识别（云端识别可能要几十秒）"}
    return res


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):                          # noqa: A003
        pass

    def do_OPTIONS(self):                                       # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):                                           # noqa: N802
        if self.path.startswith("/api/health"):
            model_ok = get_model() is not None
            src = find_source()
            route = audio_route()
            self._send({
                "ok": True,
                "model": model_ok,
                "modelPath": CN_MODEL if os.path.isdir(CN_MODEL) else EN_MODEL,
                "modelError": _model_error or "",
                "source": src or "",
                "engine": "vosk (离线)",
                "sinks": route["sinks"],
                "realSink": route["realSink"],
            })
            return
        if self.path.startswith("/api/voice/state"):
            # 注意：这个端点必须放在 do_GET 里 —— 它是查询语义，浏览器用 GET 调。
            # 之前误放在 do_POST 分支，导致 GET 走到 404（实测踩过）。
            self._send({"ok": True, "state": voice_state()})
            return
        if self.path.startswith("/api/voice/records"):
            '''
            交给界面轮询的「对话记录」接口。

            为什么需要它：一轮语音从说完到出结果要几十秒（云端 ASR 慢），
            期间界面不能干等 —— 而且**按唤醒词触发的那一轮，界面根本不知道**。
            统一改成：谁触发的都写进 /tmp/voice_text.jsonl，界面按 seq 增量拉取，
            于是「按按钮说的」和「喊唤醒词说的」都会出现在同一个会话区里。

            参数：since=<seq>，只返回序号更大的记录（首次传当前最大值可避免回放开机前的旧对话）。
            '''
            q = {}
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        q[k] = v
            try:
                since = int(q.get("since") or 0)
            except ValueError:
                since = 0
            recs = _read_records()
            tail = [r for r in recs if r["seq"] > since]
            if len(tail) > 20:                      # 别把积压的历史一次性灌给界面
                tail = tail[-20:]
            self._send({"ok": True, "count": len(recs),
                        "lastSeq": recs[-1]["seq"] if recs else 0,
                        "records": tail})
            return
        self._send({"ok": False, "error": "not found"}, 404)

    def do_POST(self):                                          # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:                                       # noqa: BLE001
            payload = {}

        if self.path.startswith("/api/voice/state"):
            self._send({"ok": True, "state": voice_state()})
            return

        if self.path.startswith("/api/voice/start"):
            # 两段式第一段：提示音 + 开始录音，立即返回
            self._send(voice_start())
            return

        if self.path.startswith("/api/voice/stop"):
            # 两段式第二段：立即结束录音并等结果。
            # 单次最长等 90 秒（云端 ASR + TTS 播报都要时间）。
            wait = int(payload.get("wait") or 60)
            wait = max(5, min(wait, 90))
            self._send(voice_stop(wait))
            return

        if self.path.startswith("/api/voice/talk"):
            # 触发设备上的完整语音链路并等结果。
            # 用线程 + 超时保护：单次最长等 60 秒。
            wait = int(payload.get("wait") or 45)
            wait = max(5, min(wait, 60))
            res = trigger_voice(wait)
            self._send(res)
            return

        if self.path.startswith("/api/beep"):
            kind = payload.get("kind") or "ready"
            ok, detail = play_beep(kind)
            self._send({"ok": ok, "route": detail if ok else "",
                        "error": "" if ok else detail})
            return

        if self.path.startswith("/api/record"):
            seconds = int(payload.get("seconds") or 4)
            seconds = max(1, min(seconds, 15))
            tmp = os.path.join(tempfile.gettempdir(), "vg-rec.wav")
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

            ok, reason = record_wav(tmp, seconds)
            if not ok:
                self._send({"ok": False, "text": "", "silent": True,
                            "reason": reason})
                return

            frames, peak, avg = analyze_wav(tmp)
            if frames == 0 or peak < SILENCE_PEAK:
                self._send({
                    "ok": True, "text": "", "silent": True,
                    "frames": frames, "peak": peak, "avg": avg,
                    "reason": ("麦克风未采集到声音（帧数 %d，峰值 %d）。"
                               "设备节点与 I2S 时钟存在，但采集数据为空，"
                               "属硬件/接线问题，软件无法修复。" % (frames, peak)),
                })
                return

            text, err = recognize(tmp)
            if text is None:
                self._send({"ok": False, "text": "", "silent": False,
                            "peak": peak, "reason": "识别失败: %s" % err})
                return
            self._send({"ok": True, "text": text, "silent": False,
                        "frames": frames, "peak": peak, "avg": avg,
                        "reason": "" if text else "未识别到有效语音"})
            return

        self._send({"ok": False, "error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8124)
    ap.add_argument("--warm", action="store_true",
                    help="启动时预加载模型（首次识别更快）")
    args = ap.parse_args()

    if args.warm:
        get_model()

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv.daemon_threads = True
    log("已监听 0.0.0.0:%d（多线程：界面的轮询不会被长请求挡住）" % args.port)
    log("模型: %s" % ("已加载" if _model is not None else "待加载"))
    log("录音源: %s" % (find_source() or "未找到"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("退出")


if __name__ == "__main__":
    main()
