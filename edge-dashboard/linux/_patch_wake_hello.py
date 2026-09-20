#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""换唤醒词：hi openvela -> Hello, openvela。

先量后改（实测数据见下），不是拍脑袋换的
--------------------------------------
1. **"hello" 在英文小模型词表里**，"helo" 不在（Vosk 会警告 Ignoring word）、
   "openvela" 也不在 —— 所以 grammar 里必须写成 "hello open vela"，
   而匹配词表写归一化后的 "hello openvela"（两边去空格后比对）。
   TTS 播 "Hello, openvela" 录回来，三种候选下都能稳定解出 "hello open vela"。

2. **候选不能只留一条**。上一轮踩过的坑：grammar 越窄，越容易把环境噪声
   **硬凑**成唤醒词。用上一轮录下的现场中文干扰音频复测：

     窄（只有 hello open vela）        干扰误触发 1/6
     宽（hello 开头 + 宽松兜底）        干扰误触发 **0/6**   ← 采用

3. 匹配词表仍然**只认完整唤醒词**（"hello openvela"）—— 09-19 那次收紧的结论：
   误触发的形式全是缺前缀的碎片。

改了三个文件：
    wakeword.py      PRESETS['en'] 的 keywords / grammar
    en_hit_rate.py   命中率测试的 PHRASE / KEYS / GRAMMAR 跟着对齐
    唤醒.sh          启动横幅里印的唤醒词文案

用法（在设备 /home/sunrise/voice_pipeline 下执行）：
    python3 _patch_wake_hello.py            # 打补丁
    python3 _patch_wake_hello.py --check    # 只看状态
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WAKE = os.path.join(HERE, "wakeword.py")
RATE = os.path.join(HERE, "en_hit_rate.py")
START = os.path.join(HERE, "唤醒.sh")

MARK = "hello open vela"

# ---------------- wakeword.py ----------------
W_OLD_KW = '"keywords": "hi openvela",'
W_NEW_KW = ('# 【09-19 换词】唤醒词改为 "Hello, openvela"。\n'
            '        # 实测（TTS 播→麦克风录→同样解码逻辑）：\n'
            '        #   · "hello" 在词表里，"helo" 不在，"openvela" 不在（要拆成 open vela）\n'
            '        #   · 候选只留一条时，现场中文干扰有 1/6 被**硬凑**成唤醒词；\n'
            '        #     带上宽松兜底候选后是 0/6 —— 所以下面 grammar 留四条。\n'
            '        #   · 匹配词表仍只认完整唤醒词（缺前缀的碎片一律不认）。\n'
            '        "keywords": "hello openvela",')

W_OLD_GR = '"grammar": "hi open vela,open vela,hi open,open",'
W_NEW_GR = '"grammar": "hello open vela,hello open,open vela,open",'


def patch_wakeword(check_only):
    src = open(WAKE, encoding="utf-8").read()
    if W_NEW_KW in src and W_OLD_GR not in src:
        print("  wakeword.py 已是 hello 版")
        return 0
    if W_OLD_KW not in src or W_OLD_GR not in src:
        print("  [X] wakeword.py 找不到锚点（keywords/grammar），跳过")
        return 2
    if check_only:
        print("  wakeword.py 还是 hi 版")
        return 1
    out = src.replace(W_OLD_KW, W_NEW_KW, 1).replace(W_OLD_GR, W_NEW_GR, 1)
    try:
        compile(out, WAKE, "exec")
    except SyntaxError as exc:
        print("  [X] wakeword.py 编译不过，已放弃：%s" % exc)
        return 3
    bak = WAKE + ".bak-before-hello-" + time.strftime("%m%d_%H%M")
    shutil.copyfile(WAKE, bak)
    open(WAKE, "w", encoding="utf-8").write(out)
    print("  [OK] wakeword.py 已换词（%d -> %d 字节），备份 %s"
          % (len(src), len(out), os.path.basename(bak)))
    return 0


# ---------------- en_hit_rate.py ----------------
R_OLD = [
    'PHRASE = "hi openvela"',
    'KEYS = ["hi openvela"]          # 09-19 收紧：与 wakeword.py 的预设保持一致',
    'GRAMMAR = ["hi open vela", "open vela", "hi open", "open"]',
]
R_NEW = [
    'PHRASE = "Hello, openvela"',
    'KEYS = ["hello openvela"]       # 与 wakeword.py 预设一致（只认完整唤醒词）',
    'GRAMMAR = ["hello open vela", "hello open", "open vela", "open"]',
]


def patch_hit_rate(check_only):
    if not os.path.isfile(RATE):
        print("  en_hit_rate.py 不存在，跳过")
        return 0
    src = open(RATE, encoding="utf-8").read()
    if R_NEW[0] in src:
        print("  en_hit_rate.py 已对齐")
        return 0
    if not all(old in src for old in R_OLD):
        print("  [X] en_hit_rate.py 锚点对不上，跳过（只改 wakeword.py 也能用）")
        return 2
    if check_only:
        print("  en_hit_rate.py 还是 hi 版")
        return 1
    out = src
    for old, new in zip(R_OLD, R_NEW):
        out = out.replace(old, new, 1)
    try:
        compile(out, RATE, "exec")
    except SyntaxError as exc:
        print("  [X] en_hit_rate.py 编译不过，已放弃：%s" % exc)
        return 3
    shutil.copyfile(RATE, RATE + ".bak-before-hello-" + time.strftime("%m%d_%H%M"))
    open(RATE, "w", encoding="utf-8").write(out)
    print("  [OK] en_hit_rate.py 已对齐")
    return 0


# ---------------- 唤醒.sh ----------------
S_OLD = '  echo "   唤醒词：hi openvela"'
S_NEW = '  echo "   唤醒词：Hello, openvela"'
S_OLD2 = '#   对着板子说「hi openvela」，它会应一声并开始录你这句指令。'
S_NEW2 = '#   对着板子说「Hello, openvela」，它会应一声并开始录你这句指令。'


def patch_start_sh(check_only):
    if not os.path.isfile(START):
        print("  唤醒.sh 不存在，跳过")
        return 0
    src = open(START, encoding="utf-8").read()
    if S_NEW in src:
        print("  唤醒.sh 已对齐")
        return 0
    if S_OLD not in src:
        print("  [X] 唤醒.sh 锚点对不上，跳过")
        return 2
    if check_only:
        print("  唤醒.sh 还是 hi 版")
        return 1
    out = src.replace(S_OLD, S_NEW, 1)
    if S_OLD2 in out:
        out = out.replace(S_OLD2, S_NEW2, 1)
    shutil.copyfile(START, START + ".bak-before-hello-" + time.strftime("%m%d_%H%M"))
    open(START, "w", encoding="utf-8").write(out)
    print("  [OK] 唤醒.sh 横幅已改")
    return 0


def main():
    check_only = "--check" in sys.argv
    print("换成 Hello, openvela：")
    rc = [patch_wakeword(check_only), patch_hit_rate(check_only), patch_start_sh(check_only)]
    if not check_only and 0 in rc:
        print("\n重启语音服务后生效：")
        print("  echo sunrise | sudo -S systemctl restart voice-assistant.service")
    return 0 if all(r in (0, 1) for r in rc) else max(rc)


if __name__ == "__main__":
    sys.exit(main())
