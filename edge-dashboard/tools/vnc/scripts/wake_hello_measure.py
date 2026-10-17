#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wake_hello_measure.py — 换唤醒词前的实测：'Hello, openvela' 会被解码成什么。

为什么要先量
------------
`openvela` 是生造词，不在 vosk 英文小模型词表里，必须拆成 "open vela" 才解得出来
（这是上一轮踩出来的结论）。现在唤醒词要加个 "Hello"，同样要先确认：
  · "hello" 在不在词表里（不在的话又得拆/换词）
  · 用哪种 grammar 候选能稳定解出 "hello open vela"
  · 旧词 "hi openvela" 在新 grammar 下会不会还误命中（不该）

做法：TTS 合成 → 喇叭播 → 麦克风录 → 用与 wakeword.py 相同的解码/匹配逻辑跑，
每个候选 grammar 各解一遍（不重复录音，只重复解码）。

用法（由 wake_hello.sh 调用，它会先停语音服务腾出麦克风）：
    python3 /tmp/wake_hello_measure.py
"""
from __future__ import annotations

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

from vosk import Model, KaldiRecognizer, SetLogLevel  # noqa: E402
import tts  # noqa: E402

SetLogLevel(-1)

# 候选 grammar（都给 [unk] 留出口，和 wakeword.py 一致）
GRAMMARS = {
    "只 hello open vela": ["hello open vela"],
    "hello + 常见变体": ["hello open vela", "helo open vela", "hello open"],
    "旧的（对照，不含 hello）": ["hi open vela", "open vela", "hi open", "open"],
}

PHRASES = [("Hello, openvela", "hello"), ("hi openvela", "hi")]


def play_and_record(wav, out_raw, extra=1.0):
    with wave.open(str(wav)) as w:
        dur = w.getnframes() / float(w.getframerate())
    p = subprocess.Popen(
        ["arecord", "-D", MIC, "-r", str(RATE), "-c", "1", "-f", "S16_LE",
         "-t", "raw", "-q", out_raw],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.4)
    subprocess.run(["aplay", "-D", SPK, "-q", str(wav)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(max(0.0, dur + extra))
    p.terminate()
    try:
        p.wait(timeout=3)
    except Exception:                                           # noqa: BLE001
        p.kill()
    time.sleep(0.3)
    return dur


def decode_all(model, raw_path, grammar):
    """返回 (完整句文本, [出现过的 partial], 命中集合)。匹配逻辑照抄 wakeword.py。"""
    data = open(raw_path, "rb").read()
    rec = KaldiRecognizer(model, RATE,
                          json.dumps(grammar + ["[unk]"], ensure_ascii=False))
    texts = []
    for i in range(0, len(data), 4000):
        if rec.AcceptWaveform(data[i:i + 4000]):
            t = json.loads(rec.Result()).get("text", "")
        else:
            t = json.loads(rec.PartialResult()).get("partial", "")
        if t and (not texts or texts[-1] != t):
            texts.append(t)
    t = json.loads(rec.FinalResult()).get("text", "")
    if t:
        texts.append(t)
    return texts


def main():
    print("=== 加载英文小模型 ===", flush=True)
    model = Model(MODEL)
    print("  就绪", flush=True)

    samples = []
    for phrase, tag in PHRASES:
        try:
            wav = tts.synth(phrase)
        except Exception as exc:                                # noqa: BLE001
            print("  合成「%s」失败：%s（跳过）" % (phrase, exc), flush=True)
            continue
        print("\n=== 录样本「%s」×3 ===" % phrase, flush=True)
        for i in range(1, 4):
            raw = "/tmp/wh_%s_%d.raw" % (tag, i)
            d = play_and_record(wav, raw)
            samples.append((tag, phrase, raw))
            print("  第 %d 次（%.2f 秒）-> %s" % (i, d, raw), flush=True)

    print("\n=== 解码结果 ===", flush=True)
    for gname, grammar in GRAMMARS.items():
        print("\n【grammar: %s】" % gname)
        for tag, phrase, raw in samples:
            texts = decode_all(model, raw, grammar)
            print("  %-6s %s" % (tag, " | ".join(texts[-3:]) if texts else "(无输出)"))

    print("\n=== 词表检查：hello / hello 之类在不在模型里 ===", flush=True)
    for word in ("hello", "helo", "hi", "open", "vela", "openvela"):
        rec = KaldiRecognizer(model, RATE)
        rec.AcceptWaveform(b"\x00\x00" * 800)
        rec.FinalResult()
        # 用 grammar 方式试探：把单词塞进 grammar，构造失败会抛异常/静默忽略
        try:
            KaldiRecognizer(model, RATE, json.dumps([word]))
            print("  %-10s 可以放进 grammar" % word)
        except Exception as exc:                                # noqa: BLE001
            print("  %-10s 不能放进 grammar：%s" % (word, exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
