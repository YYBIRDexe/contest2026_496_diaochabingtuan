#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 nlp_parse.py 的 INTENTS 插入 battery 意图（在设备上运行）。

为什么要单独一个脚本而不是 ssh heredoc：
  第一次用 heredoc 内嵌 Python 时，字符串拼接被 shell/PowerShell 层层转义搞坏，
  报 "can only concatenate str (not tuple) to str"，意图根本没插进去。
  改成「本地写文件 → scp 上传 → 设备上执行」，就没有转义问题了。

用法：python3 _patch_battery_intent.py
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "nlp_parse.py")

BLOCK = '''    {
        "name": "battery",
        "desc": "查询小车电池电量",
        # 为什么要单独一个意图：用户问「小车的电量怎么样了」原本被归到 status
        # （查里程计），答非所问。车端其实有 /ros_robot_controller/battery 话题，
        # 实测能读到毫伏值（约 7041），所以单列一个意图去读它。
        # 关键词只收「电量/电池」这类明确说法，不收「小车」单独的词 ——
        # 关键词按长度取胜，那会抢走「让小车前进」。
        "keywords": ["电量", "电池", "剩余电量", "电池电量", "还有多少电",
                     "电够不够", "电池怎么样", "电量怎么样", "电量查询",
                     "查电量", "看电量", "电量多少"],
        "params": [],
    },
'''


def main():
    src = open(TARGET, encoding="utf-8").read()

    if '"name": "battery"' in src:
        print("battery 意图已存在，无需修改")
        return 0

    anchor = '"name": "car_check"'
    i = src.find(anchor)
    if i < 0:
        print("找不到 car_check 锚点，放弃")
        return 1

    # car_check 这一条的收尾是 "\n    },"
    j = src.find("\n    },", i)
    if j < 0:
        print("找不到 car_check 的结尾，放弃")
        return 1

    ins = j + len("\n    },")
    out = src[:ins] + "\n" + BLOCK.rstrip("\n") + src[ins:]

    # 先写临时文件做语法校验，通过再替换 —— 避免把好文件改坏
    tmp = TARGET + ".new"
    open(tmp, "w", encoding="utf-8").write(out)
    try:
        import ast
        ast.parse(open(tmp, encoding="utf-8").read())
    except SyntaxError as exc:
        os.unlink(tmp)
        print("插入后语法错误，已放弃：%s" % exc)
        return 1

    shutil.move(tmp, TARGET)
    print("已插入 battery 意图（%d -> %d 字节）" % (len(src), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
