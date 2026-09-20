#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把损坏的「重试块」从 voice_button.py 里精准摘掉，保留文件其余部分不动。

背景
----
之前加的「麦克风被占就重试一次」用了 `continue` 放在 `except` 块里，
Python 不允许（'continue' not properly in loop），导致 voice_button.py
直接编译不过、voice-assistant.service 起不来。

本脚本只做减法：
  1. 把 if not data: 分支恢复成原来的三行（打印 + busy + return）
  2. 删掉残留的 `except _VgMicRetry:` 块（含块体）
  3. 删掉 _VgMicRetry 类定义与 _vg_retried 标志行

⚠️ 校验必须用 compile()，不能用 ast.parse()：
   ast.parse() 会放过 'continue' not properly in loop 这种错误
   （AST 层结构合法，编译期才报），这正是上次没拦住的原因。
"""
import io
import os
import shutil
import sys
import time

TARGET = "/home/sunrise/voice_pipeline/voice_button.py"

BROKEN_BRANCH = (
    '                # VG_RETRY_BUSY: 首次建立失败几乎都是「上一轮的 arecord 还没让出麦克风」，\n'
    '                # 清掉残留再重试一次通常就好。只重试一次，避免真故障时死循环。\n'
    '                print("采集流中断（设备被占或驱动卡死？）", file=sys.stderr)\n'
    '                if not _vg_retried:\n'
    '                    _vg_retried = True\n'
    '                    raise _VgMicRetry()\n'
    '                args.last_rec_reason = "busy"\n'
    '                return None, 0.0\n'
)
FIXED_BRANCH = (
    '                print("采集流中断（设备被占或驱动卡死？）", file=sys.stderr)\n'
    '                args.last_rec_reason = "busy"\n'
    '                return None, 0.0\n'
)

EXC_HEAD = "    except _VgMicRetry:\n"
EXC_CLASS = (
    '\n\nclass _VgMicRetry(Exception):\n'
    '    """VG_RETRY_BUSY: 内部信号，用于从读循环跳到重试分支。"""\n'
)


def compiles(src):
    try:
        compile(src, "<vg>", "exec")
        return True, ""
    except SyntaxError as e:
        return False, "%s (line %s)" % (e.msg, e.lineno)


def main():
    if not os.path.isfile(TARGET):
        print("失败: 找不到 %s" % TARGET)
        return 1

    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    ok, err = compiles(src)
    if ok:
        print("当前文件本来就能编译，无需修复")
        return 0
    print("当前编译错误: %s" % err)

    changed = []

    if BROKEN_BRANCH in src:
        src = src.replace(BROKEN_BRANCH, FIXED_BRANCH, 1)
        changed.append("恢复 if not data 分支")

    lines = src.splitlines(keepends=True)
    # 删 except 块：从 except 行到块体结束（块体缩进 > 4 空格且非空）
    out = []
    i = 0
    while i < len(lines):
        if lines[i] == EXC_HEAD:
            changed.append("删除 except _VgMicRetry 块")
            i += 1
            while i < len(lines):
                ln = lines[i]
                if ln.strip() == "":
                    i += 1
                    continue
                if ln.startswith("        "):
                    i += 1
                    continue
                break
            continue
        if lines[i] == EXC_CLASS:
            changed.append("删除 _VgMicRetry 类定义")
            i += 1
            continue
        if "_vg_retried = False" in lines[i]:
            changed.append("删除 _vg_retried 标志行")
            i += 1
            continue
        out.append(lines[i])
        i += 1
    src = "".join(out)

    if not changed:
        print("失败: 没有识别出任何可修复的内容，未做修改")
        return 1

    ok, err = compiles(src)
    if not ok:
        print("失败: 修完仍编译不过: %s，未写入" % err)
        return 1

    bak = TARGET + ".bak-vgunbreak-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(TARGET, bak)
    tmp = TARGET + ".tmp-vgunbreak"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(src)
    os.replace(tmp, TARGET)

    print("已修复: %s" % TARGET)
    print("  备份: %s" % bak)
    print("  改动: %s" % "；".join(changed))
    print("  编译检查: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
