#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wake_decode_only.py — 只做对比解码（音频已经由 wake_compare.py 录好了）。

为什么拆开：板子是 ARM，把 6 段干扰音频 × 5 种配置解一遍要几分钟，
和"播音+录音"混在一个脚本里跑，容易整体超时把采集结果一起丢掉。
采集一次、解码多次，才是这块板子上跑实验的正确姿势。

用法：python3 /tmp/wake_decode_only.py
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

LOOSE_GRAMMAR = ["hi open vela", "open vela", "hi open", "open"]
STRICT_GRAMMAR = ["hi open vela"]
BARE_KEYS = ["hi openvela", "openvela"]
HI_KEYS = ["hi openvela"]

CONFIGS = [
    ("A 现状（宽语法 + 认 openvela + partial）", LOOSE_GRAMMAR, BARE_KEYS, True),
    ("B 宽语法 + 只认 hi openvela + partial", LOOSE_GRAMMAR, HI_KEYS, True),
    ("C 宽语法 + 只认 hi + 只认整句", LOOSE_GRAMMAR, HI_KEYS, False),
    ("D 窄语法 + 只认 hi + partial", STRICT_GRAMMAR, HI_KEYS, True),
    ("E 窄语法 + 认 openvela + partial", STRICT_GRAMMAR, BARE_KEYS, True),
]


def decode(model, raw_path, grammar, keys, use_partial):
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
    hi = sorted(glob.glob("/tmp/wk_hi_*.raw"))
    bare = sorted(glob.glob("/tmp/wk_bare_*.raw"))
    inter = sorted(glob.glob("/tmp/wk_int_*.raw"),
                   key=lambda p: int(p.rsplit("_", 1)[1].split(".")[0]))
    ambient = "/tmp/wk_ambient.raw"
    print("样本：hi=%d  bare=%d  干扰=%d  环境音=%s"
          % (len(hi), len(bare), len(inter), os.path.isfile(ambient)), flush=True)

    model = Model(MODEL)
    print("模型就绪\n", flush=True)

    for name, grammar, keys, use_partial in CONFIGS:
        hi_hit = sum(1 for p in hi if decode(model, p, grammar, keys, use_partial))
        bare_hit = sum(1 for p in bare if decode(model, p, grammar, keys, use_partial))
        inter_hits = []
        for p in inter:
            for kind, text, hit in decode(model, p, grammar, keys, use_partial):
                inter_hits.append((os.path.basename(p), kind, text, hit))
        amb = decode(model, ambient, grammar, keys, use_partial) if os.path.isfile(ambient) else []

        print("【%s】" % name)
        print("  说「hi openvela」   ：%d/%d 命中" % (hi_hit, len(hi)))
        print("  只说「openvela」    ：%d/%d 命中" % (bare_hit, len(bare)))
        print("  干扰音频误触发      ：%d 次 / %d 段" % (len(inter_hits), len(inter)))
        for label, kind, text, hit in inter_hits[:5]:
            print("      · %s → 「%s」命中「%s」(%s)" % (label, text, hit, kind))
        print("  安静环境音误触发    ：%d 次" % len(amb))
        if amb:
            for kind, text, hit in amb[:3]:
                print("      · 环境音 → 「%s」命中「%s」(%s)" % (text, hit, kind))
        print(flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
