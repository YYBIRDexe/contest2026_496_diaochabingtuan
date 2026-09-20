#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""唤醒词收紧：只认「hi openvela」，不再认孤零零的「openvela」。

为什么要收紧（有实测数据，不是猜的）
----------------------------------
屋里正常聊天时唤醒引擎每隔半分钟就误触发一次。把真机日志里 35 次触发
按"听成了什么"分类：

    识别到 open vela / [unk] open vela / [unk][unk] open vela   29 次
    识别到 hi open vela                                          6 次

也就是说：**误触发的形式里根本没有 hi** —— 孤零零的「openvela」被英文语法
从中文说话声里硬套了出来。设备上跑的配置对比实验（同一批音频 5 种配置）：

    说「hi openvela」   4/4 命中（收紧前后一样，不损失）
    只说「openvela」    3/3 → 0/3（这是收紧的代价）

改动只有一处：`PRESETS['en']['keywords']` 去掉 `,openvela`。
**grammar（解码候选）不动** —— 候选留着是为了让 Vosk 更容易解出
"hi open vela"（openvela 不在英文小模型词表里，见文件里的说明）；
匹配用哪几个词、和解码给什么候选，本来就是两件事。

顺带把 en_hit_rate.py 的 KEYS 一起对齐，免得以后跑命中率测试时
量的是旧策略。

用法（在设备 /home/sunrise/voice_pipeline 下执行）：
    python3 _patch_wake_strict.py            # 打补丁
    python3 _patch_wake_strict.py --check    # 只看状态
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WAKE = os.path.join(HERE, "wakeword.py")
RATE = os.path.join(HERE, "en_hit_rate.py")

OLD = '"keywords": "hi openvela,openvela",'
NEW = ('# 【09-19 收紧】只认完整唤醒词。实测误触发的形式全是孤零零的\n'
       '        # 「open vela」（中文聊天被英文语法硬套出来的），29/35 次；\n'
       '        # 要求 hi 之后真唤醒命中率不变（4/4），代价是单说 openvela 不响应。\n'
       '        # grammar 故意不动：候选是给解码器用的，和解码质量有关。\n'
       '        "keywords": "hi openvela",')
MARK = '"keywords": "hi openvela",'


def patch_wakeword(check_only):
    src = open(WAKE, encoding="utf-8").read()
    if MARK in src and OLD not in src:
        print("wakeword.py：已经是收紧后的配置（只认 hi openvela）")
        return 0
    if OLD not in src:
        print("wakeword.py：找不到锚点，未改动：%s" % OLD)
        return 2
    if check_only:
        print("wakeword.py：还是宽松配置（认得 openvela）")
        return 1
    out = src.replace(OLD, NEW, 1)
    try:
        compile(out, WAKE, "exec")
    except SyntaxError as exc:
        print("wakeword.py 打完补丁编译不过，已放弃：%s" % exc)
        return 3
    bak = WAKE + ".bak-before-strict-" + time.strftime("%m%d_%H%M")
    shutil.copyfile(WAKE, bak)
    open(WAKE, "w", encoding="utf-8").write(out)
    print("wakeword.py：已收紧（%d -> %d 字节），备份 %s"
          % (len(src), len(out), os.path.basename(bak)))
    return 0


def patch_hit_rate(check_only):
    if not os.path.isfile(RATE):
        print("en_hit_rate.py：不存在，跳过")
        return 0
    src = open(RATE, encoding="utf-8").read()
    old = 'KEYS = ["hi openvela", "openvela"]'
    new = 'KEYS = ["hi openvela"]          # 09-19 收紧：与 wakeword.py 的预设保持一致'
    if old not in src:
        print("en_hit_rate.py：KEYS 已经是收紧后的（或格式变了），跳过")
        return 0
    if check_only:
        print("en_hit_rate.py：KEYS 还是宽松的")
        return 1
    out = src.replace(old, new, 1)
    try:
        compile(out, RATE, "exec")
    except SyntaxError as exc:
        print("en_hit_rate.py 编译不过，已放弃：%s" % exc)
        return 3
    shutil.copyfile(RATE, RATE + ".bak-before-strict-" + time.strftime("%m%d_%H%M"))
    open(RATE, "w", encoding="utf-8").write(out)
    print("en_hit_rate.py：KEYS 已对齐")
    return 0


def main():
    check_only = "--check" in sys.argv
    rc1 = patch_wakeword(check_only)
    rc2 = patch_hit_rate(check_only)
    if not check_only and rc1 == 0:
        print("\n重启语音服务后生效：")
        print("  echo sunrise | sudo -S systemctl restart voice-assistant.service")
    return 0 if (rc1 in (0, 1) and rc2 in (0, 1)) else max(rc1, rc2)


if __name__ == "__main__":
    sys.exit(main())
