#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""让 voice_button.py 把「实际念出来的那句」也写进对话记录。

问题（用户报的「没有文字回复」根因之一）
--------------------------------------
有些指令的**结果本身就是答案**，由命令自己用 `@@SPEAK@@` 那行要求播报
（例如 check_cars.py 的「小车都联系不上」）。voice_button 确实念了，
但写进 /tmp/voice_text.jsonl 的记录里没有 `said` 字段 ——
界面拿到的 `said` 是空的，于是会话区只有「你」那一半，
用户看到的就是「它好像没回我」。

改动只有一处、纯新增：在写日志前，把 spoke["reply"] 补进 rec["said"]。
不碰任何控制流，失败也不影响主流程。

用法（在设备上，voice_pipeline 目录里执行）：
    python3 _patch_said_reply.py            # 打补丁
    python3 _patch_said_reply.py --check    # 只看有没有打过
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "voice_button.py")

ANCHOR = "    # 出口 4：日志（放在最后写，这样能带上解析结果与实际命令）"
ADD = '''    # 【补丁】把「念出来的那句」也记进日志，界面靠它显示助手的回复。
    # @@SPEAK@@ 播报的结果（如「小车都联系不上」）以前只有设备自己知道，
    # 界面拿到的 said 是空的 —— 会话区就只有「你」、没有助手那半句。
    if spoke.get("reply") and not rec.get("said"):
        rec["said"] = spoke["reply"]
'''
MARK = 'rec["said"] = spoke["reply"]'


def main():
    check_only = "--check" in sys.argv
    src = open(TARGET, encoding="utf-8").read()

    if MARK in src:
        print("已经打过这个补丁（voice_button.py 里有 said 补写）")
        return 0
    if check_only:
        print("还没打补丁")
        return 1

    i = src.find(ANCHOR)
    if i < 0:
        print("找不到锚点，未改动：%s" % ANCHOR)
        return 2

    # 行首对齐：锚点本身带 4 空格缩进，插在它前面即可
    out = src[:i] + ADD + src[i:]

    # compile() 而不是 ast.parse()：ast 能过、compile 才能拦住
    # 「'continue' not properly in loop」这类只在编译期报的错（实测踩过）
    try:
        compile(out, TARGET, "exec")
    except SyntaxError as exc:
        print("打完补丁编译不过，已放弃：%s" % exc)
        return 3

    bak = TARGET + ".bak-before-said-" + time.strftime("%m%d_%H%M")
    shutil.copyfile(TARGET, bak)
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(out)
    print("补丁已应用：%s -> %s 字节" % (len(src), len(out)))
    print("备份：%s" % bak)
    print("（重启语音服务后生效：sudo systemctl restart voice-assistant.service）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
