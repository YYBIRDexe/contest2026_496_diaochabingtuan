#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补上 one_round 里缺的 global 声明。

背景（实测踩过的坑，值得记下来）
--------------------------------
给 voice_button.py 加「手动结束录音」时，在 one_round 里插了一句：

    _VGSIG_STOP = False     # 每轮开始前清标志

这一句让 Python 把 _VGSIG_STOP 判定为**局部变量**（有赋值即局部），
于是 record_utterance 里读它的那一刻直接抛：

    UnboundLocalError: local variable '_VGSIG_STOP' referenced before assignment

第三个坑是**幂等判断写错了**：守卫原本用「整文件搜 global _VGSIG_STOP」判断
是否已修复，而信号处理器自己的那行就命中了 → 误判为已完成 →
修复被静默跳过，现象是「补丁打过了却还在崩」。

所以：判断必须只看目标函数体内有没有那行，不能整文件搜。

这个脚本用 AST 精确定位函数体，不依赖任何锚点字符串，因此对
`def one_round(args, trigger=None, /):` 这种带 `/` 的签名也有效。
幂等：已经有就跳过。
"""
import ast
import io
import os
import shutil
import sys
import time

TARGET = "/home/sunrise/voice_pipeline/voice_button.py"
GLOBAL_LINE = "    global _VGSIG_STOP   # 每轮开始前清标志（缺这行会 UnboundLocalError）\n"
NEED = ["one_round", "record_utterance"]


def function_has_global(tree, fn_name, flag="_VGSIG_STOP"):
    """用 AST 判断某个函数是否写了 global <flag>。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            for st in node.body:
                if isinstance(st, ast.Global) and flag in st.names:
                    return True
            return False
    return None                                              # 函数不存在


def main():
    if not os.path.isfile(TARGET):
        print("失败: 找不到 %s" % TARGET)
        return 1

    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    tree = ast.parse(src)
    need_fix = []
    for fn in NEED:
        got = function_has_global(tree, fn)
        if got is None:
            print("  提示: 文件里没有 %s，跳过" % fn)
        elif got:
            print("  %-18s 已有 global，无需修改" % fn)
        else:
            need_fix.append(fn)
            print("  %-18s **缺 global，将补上**" % fn)

    if not need_fix:
        print("全部就位，无需修改")
        return 0

    lines = src.splitlines(keepends=True)
    # 收集插入点后**从后往前**插入：否则先插的行会让后面记录的
    # 行号全部偏移，第二处就会插错位置。
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in need_fix:
            targets.append((node.body[0].lineno - 1, node.name))
    targets.sort(reverse=True)
    for idx, name in targets:
        lines.insert(idx, GLOBAL_LINE)
        print("  已在 %s 第 %d 行前插入 global 声明" % (name, idx + 1))

    new = "".join(lines)

    # 语法 + AST 双校验：AST 能确认 global 真的生效（不只是文本在那儿）
    try:
        ast.parse(new)
    except SyntaxError as e:
        print("失败: 改完语法错误，未写入: %s" % e)
        return 1

    bak = TARGET + ".bak-vgglobal-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(TARGET, bak)
    tmp = TARGET + ".tmp-vgglobal"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, TARGET)

    tree2 = ast.parse(new)
    ok = all(function_has_global(tree2, fn) is not False for fn in NEED)
    if not ok:
        shutil.copy2(bak, TARGET)
        print("失败: 写入后复查仍有缺失，已回滚")
        return 1

    print("完成: %s" % TARGET)
    print("  备份: %s" % bak)
    print("  复查: 所有目标函数均已声明 global")
    return 0


if __name__ == "__main__":
    sys.exit(main())
