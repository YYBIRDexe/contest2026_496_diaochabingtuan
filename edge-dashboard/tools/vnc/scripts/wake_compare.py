#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wake_compare.py — 唤醒词配置对比实验（在设备上跑，用真实麦克风/扬声器）。

要回答的问题
------------
「把唤醒词改成 openvela（不要 hi）会不会好一点？」
现象：屋里正常聊天时，唤醒引擎每隔半分钟就误触发一次。

方法（不需要人说话，可重复）
--------------------------
1. 真唤醒样本：TTS 合成的「hi openvela」播 3 次录 3 次；
   再把开头那个 "hi" 剪掉，当「只说 openvela」的样本（剪出来的，
   不是真人发音，作参考）。
2. 干扰样本：**现场真实录音**（/tmp 里那些从房间录下来的中文对话）
   + TTS 中文句子，逐条播一遍并录下来 —— 误唤醒的原料就是它们。
3. 同一批音频，用**和 wakeword.py 完全相同的解码/匹配逻辑**跑 5 种配置：

   A 现状：宽语法（open vela/open 都在）+ 认 openvela + partial 也算命中
   B 宽语法 + 只认 hi openvela + partial
   C 宽语法 + 只认 hi openvela + 只认完整句
   D 窄语法（只留 hi open vela）+ 只认 hi + partial
   E 窄语法 + 认 openvela + partial

用法（由 wake_compare.sh 调用，它会先停服务腾麦克风、结束时再拉起来）：
    python3 /tmp/wake_compare.py
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
import wave

sys.path.insert(0, "/home/sunrise/voice_pipeline")

MIC = "plughw:CARD=hobotsnd5,DEV=0"
SPK = "plughw:CARD=hobotsnd5,DEV=1"
RATE = 16000
MODEL = "/home/sunrise/vosk-model-small-en-us-0.15"
AMB_SECONDS = 45
CACHE = "/home/sunrise/voice_pipeline/tts_cache"
HEAD_WAV = os.path.join(CACHE, "dfe29abb0563f80c.wav")     # TTS「hi openvela」
BARE_WAV = "/tmp/wk_bare_openvela.wav"                     # 剪掉 hi 的版本

from vosk import Model, KaldiRecognizer, SetLogLevel  # noqa: E402

SetLogLevel(-1)

LOOSE_GRAMMAR = ["hi open vela", "open vela", "hi open", "open"]
STRICT_GRAMMAR = ["hi open vela"]
BARE_KEYS = ["hi openvela", "openvela"]        # 现状：openvela 单独命中也算
HI_KEYS = ["hi openvela"]                      # 收紧：必须听到 hi

CONFIGS = [
    ("A 现状（宽语法 + 认 openvela + partial）", LOOSE_GRAMMAR, BARE_KEYS, True),
    ("B 宽语法 + 只认 hi openvela + partial", LOOSE_GRAMMAR, HI_KEYS, True),
    ("C 宽语法 + 只认 hi + 只认整句", LOOSE_GRAMMAR, HI_KEYS, False),
    ("D 窄语法 + 只认 hi + partial", STRICT_GRAMMAR, HI_KEYS, True),
    ("E 窄语法 + 认 openvela + partial", STRICT_GRAMMAR, BARE_KEYS, True),
]


def record(path, seconds):
    try:
        os.remove(path)
    except OSError:
        pass
    p = subprocess.Popen(
        ["arecord", "-D", MIC, "-r", str(RATE), "-c", "1", "-f", "S16_LE",
         "-t", "raw", "-q", path],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    time.sleep(seconds)
    p.terminate()
    try:
        p.wait(timeout=3)
    except Exception:                                       # noqa: BLE001
        p.kill()
    return os.path.getsize(path) if os.path.isfile(path) else 0


def play_and_capture(wav, out_raw):
    """播一段音频，同时录下来（近似「屋里有这个声音」）。"""
    with wave.open(str(wav)) as w:
        dur = w.getnframes() / float(w.getframerate())
    p = subprocess.Popen(
        ["arecord", "-D", MIC, "-r", str(RATE), "-c", "1", "-f", "S16_LE",
         "-t", "raw", "-q", out_raw],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    time.sleep(0.4)
    subprocess.run(["aplay", "-D", SPK, "-q", str(wav)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(max(0.0, dur + 1.0))
    p.terminate()
    try:
        p.wait(timeout=3)
    except Exception:                                       # noqa: BLE001
        p.kill()
    time.sleep(0.3)
    return dur


def trim_head(src, dst, seconds=0.55):
    """把开头那段（"hi"）剪掉，当作「只说 openvela」的样本。"""
    with wave.open(src) as w:
        rate, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    cut = int(rate * seconds) * ch * sw
    with wave.open(dst, "wb") as o:
        o.setnchannels(ch)
        o.setsampwidth(sw)
        o.setframerate(rate)
        o.writeframes(frames[cut:])
    return dst


def decode(model, raw_path, grammar, keys, use_partial):
    """返回命中列表 [(来源, 文本, 命中词)]，逻辑与 wakeword.py 一致。"""
    data = open(raw_path, "rb").read()
    rec = KaldiRecognizer(model, RATE,
                          json.dumps(grammar + ["[unk]"], ensure_ascii=False))
    seen = []
    for i in range(0, len(data), 4000):
        chunk = data[i:i + 4000]
        if rec.AcceptWaveform(chunk):
            t = json.loads(rec.Result()).get("text", "")
            if t:
                seen.append(("result", t))
        elif use_partial:
            t = json.loads(rec.PartialResult()).get("partial", "")
            if t:
                seen.append(("partial", t))
    t = json.loads(rec.FinalResult()).get("text", "")
    if t:
        seen.append(("result", t))

    hits = []
    for kind, text in seen:
        norm = text.replace(" ", "").lower()
        hit = next((k for k in keys if k.replace(" ", "").lower() in norm), None)
        if hit:
            hits.append((kind, text, hit))
    return hits


def main():
    print("=== 加载英文小模型 ===", flush=True)
    model = Model(MODEL)
    print("  就绪", flush=True)

    # ---------------- 1. 真唤醒样本 ----------------
    samples = []
    if os.path.isfile(HEAD_WAV):
        for i in range(1, 4):
            raw = "/tmp/wk_hi_%d.raw" % i
            d = play_and_capture(HEAD_WAV, raw)
            samples.append(("hi", raw))
            print("  真唤醒样本「hi openvela」第 %d 次（%.2f 秒）" % (i, d), flush=True)
        trim_head(HEAD_WAV, BARE_WAV)
        for i in range(1, 4):
            raw = "/tmp/wk_bare_%d.raw" % i
            d = play_and_capture(BARE_WAV, raw)
            samples.append(("bare", raw))
            print("  真唤醒样本「openvela（剪掉 hi）」第 %d 次（%.2f 秒）" % (i, d), flush=True)
    else:
        print("  找不到 %s，跳过真唤醒样本" % HEAD_WAV, flush=True)

    # ---------------- 2. 干扰样本（现场录音 + 中文 TTS）----------------
    print("\n=== 干扰样本：把「屋里说话」放一遍再录下来 ===", flush=True)
    inter = []
    candidates = ["/tmp/vb_inject_test.wav", "/tmp/vb_utt.wav", "/tmp/vb_16k.wav"]
    long_cache = []
    for p in glob.glob(os.path.join(CACHE, "*.wav")):
        try:
            with wave.open(p) as w:
                d = w.getnframes() / float(w.getframerate())
            if d > 3.5:
                long_cache.append((d, p))
        except Exception:                                   # noqa: BLE001
            pass
    long_cache.sort(reverse=True)
    candidates += [p for _, p in long_cache[:3]]

    for idx, src in enumerate(candidates, 1):
        if not os.path.isfile(src):
            continue
        raw = "/tmp/wk_int_%d.raw" % idx
        d = play_and_capture(src, raw)
        inter.append((os.path.basename(src), raw))
        print("  第 %d 段 %s（%.2f 秒）" % (idx, os.path.basename(src), d), flush=True)

    # ---------------- 3. 现场安静环境音 ----------------
    print("\n=== 顺带录 %d 秒真实环境音 ===" % AMB_SECONDS, flush=True)
    amb = "/tmp/wk_ambient.raw"
    size = record(amb, AMB_SECONDS)
    print("  %d 字节（%.1f 秒）" % (size, size / 2.0 / RATE), flush=True)

    # ---------------- 4. 逐配置对比 ----------------
    print("\n=== 对比结果 ===", flush=True)
    for name, grammar, keys, use_partial in CONFIGS:
        hi_hit = sum(1 for tag, r in samples
                     if tag == "hi" and decode(model, r, grammar, keys, use_partial))
        hi_n = sum(1 for tag, _ in samples if tag == "hi")
        bare_hit = sum(1 for tag, r in samples
                       if tag == "bare" and decode(model, r, grammar, keys, use_partial))
        bare_n = sum(1 for tag, _ in samples if tag == "bare")
        inter_hits = []
        for label, raw in inter:
            for kind, text, hit in decode(model, raw, grammar, keys, use_partial):
                inter_hits.append((label, kind, text, hit))
        amb_hits = decode(model, amb, grammar, keys, use_partial)

        print("\n【%s】" % name)
        print("  说「hi openvela」：%d/%d 命中" % (hi_hit, hi_n))
        print("  只说「openvela」：%d/%d 命中" % (bare_hit, bare_n))
        print("  干扰音频误触发：%d 次（%d 段）" % (len(inter_hits), len(inter)))
        for label, kind, text, hit in inter_hits[:4]:
            print("      · %s：%s → 命中「%s」(%s)" % (label, text, hit, kind))
        print("  安静环境音误触发：%d 次" % len(amb_hits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
