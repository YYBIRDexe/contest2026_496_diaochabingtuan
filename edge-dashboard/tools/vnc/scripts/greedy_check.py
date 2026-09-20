#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""greedy_check.py — 用上次录下的中文干扰音频，比较两种 hello grammar 的误触发风险。

背景：上一轮实测发现「grammar 候选越窄，越容易把环境噪声**硬凑**成唤醒词」
（窄 grammar 在安静环境音上反而多出 2 次误触发）。所以换唤醒词时也要验一下。

这里不用重新录音 —— 直接解码上一轮留下的干扰 raw（/tmp/wk_int_*.raw，
都是现场中文说话的实录）。

用法：python3 /tmp/greedy_check.py
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, "/home/sunrise/voice_pipeline")
from vosk import Model, KaldiRecognizer, SetLogLevel  # noqa: E402

SetLogLevel(-1)
RATE = 16000
MODEL = "/home/sunrise/vosk-model-small-en-us-0.15"

KEYS = ["hello openvela", "hi openvela"]        # 两个都查：新的该命中、旧的该不命中

GRAMMARS = {
    "窄：只有 hello open vela": ["hello open vela"],
    "宽：hello 开头 + 宽松兜底": ["hello open vela", "hello open", "open vela", "open"],
}


def decode(model, raw, grammar):
    data = open(raw, "rb").read()
    rec = KaldiRecognizer(model, RATE, json.dumps(grammar + ["[unk]"], ensure_ascii=False))
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


def hits(texts):
    out = []
    for t in texts:
        norm = t.replace(" ", "").lower()
        for k in KEYS:
            if k.replace(" ", "").lower() in norm:
                out.append((k, t))
    return out


def main():
    files = sorted(glob.glob("/tmp/wk_int_*.raw")) + sorted(glob.glob("/tmp/wk_hi_*.raw"))
    if not files:
        print("没有可复用的干扰/样本音频（/tmp/wk_*.raw），跳过")
        return 1
    print("复用音频 %d 个：%s\n" % (len(files), ", ".join(os.path.basename(f) for f in files)))

    model = Model(MODEL)
    for gname, grammar in GRAMMARS.items():
        print("【%s】" % gname)
        for f in files:
            texts = decode(model, f, grammar)
            h = hits(texts)
            tag = os.path.basename(f)
            kind = "干扰" if "wk_int" in tag else "旧唤醒词"
            if h:
                print("  %-14s(%s) 命中 → %s" % (tag, kind, h[:2]))
            else:
                print("  %-14s(%s) 未命中（末尾解码：%s）"
                      % (tag, kind, texts[-1] if texts else "无"))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
