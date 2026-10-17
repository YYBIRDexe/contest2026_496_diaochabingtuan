#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 battery 意图加进 agent_slow.py 的云端提示词（慢路径）。

改三处：
  1. AGENT_ALLOWED_INTENTS —— 白名单，不加的话云端判出 battery 也会被丢弃
  2. SYSTEM_PROMPT 的意图表 —— 让模型知道有这个意图
  3. Few-shot 示例 —— 实测加例子比只写说明有效得多

和 _patch_battery_intent.py 一样用「本地写 → scp 上传 → 设备执行」，
避免 heredoc 的转义问题。

用法：python3 _patch_agent_battery.py
"""
import ast
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "agent_slow.py")


def patch_whitelist(src):
    # "car_check": set(),  之后插入 battery
    anchor = '"car_check": set(),'
    i = src.find(anchor)
    if i < 0:
        return src, "找不到 car_check 白名单条目"
    j = src.find("\n", i)
    add = ('\n    # 查询小车电池电量（只读：只订阅 /ros_robot_controller/battery）\n'
           '    "battery": set(),')
    return src[:j] + add + src[j:], ""


def patch_prompt(src):
    # 在意图表的 car_check 之后插入 battery 说明
    anchor = '- forward         : 前进。参数 distance_m(米,数字)'
    i = src.find(anchor)
    if i < 0:
        return src, "找不到意图表的 forward 行"
    add = ('- battery         : 查询小车**电池电量**（用户问"电量怎么样""电池还有多少电"\n'
           '                    "剩余电量"这类问题时用它。只读，不移动车）\n')
    return src[:i] + add + src[i:], ""


def patch_fewshot(src):
    # 在 car_check 的示例行之后插入 battery 示例
    anchor = '用户：小车现在状态怎么样'
    i = src.find(anchor)
    if i < 0:
        return src, "找不到 Few-shot 的 status 示例"
    add = ('用户：小车的电量怎么样了 / 电池还有多少电 / 查一下剩余电量\n'
           '输出：{"intent":"battery","params":{},"confidence":0.95}\n\n')
    return src[:i] + add + src[i:], ""


def main():
    src = open(TARGET, encoding="utf-8").read()
    orig = len(src)

    if '"battery"' in src:
        print("agent_slow.py 里已经有 battery，无需修改")
        return 0

    errs = []
    for fn in (patch_whitelist, patch_prompt, patch_fewshot):
        src, err = fn(src)
        if err:
            errs.append(err)

    if errs:
        print("补丁未全部命中，已放弃：")
        for e in errs:
            print("   -", e)
        return 1

    tmp = TARGET + ".new"
    open(tmp, "w", encoding="utf-8").write(src)
    try:
        ast.parse(open(tmp, encoding="utf-8").read())
    except SyntaxError as exc:
        os.unlink(tmp)
        print("插入后语法错误，已放弃：%s" % exc)
        return 1

    shutil.move(tmp, TARGET)
    print("已更新 agent_slow.py（%d -> %d 字节）" % (orig, len(src)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
