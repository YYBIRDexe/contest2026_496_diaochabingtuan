#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可选小补丁：把 VAD 的「判句尾静音时长」从 0.8 秒降到 0.45 秒。

效果：说完话后助手更快收尾，用户不必按第二次。
代价：说话中间停顿超过 0.45 秒会被当成句尾（命令句短，实测影响小）。

不加这个补丁也能用 —— 界面上的「第二次按下」走 SIGUSR1 立即结束，
不依赖这个阈值。这个补丁只是让「不按第二次」的路径也更快。

改的是 argparse 的 default，不动判定逻辑；幂等。
"""
import io
import os
import shutil
import sys
import time

TARGET = "/home/sunrise/voice_pipeline/voice_button.py"
OLD = 'ap.add_argument("--end-silence", type=float, default=0.8)'
NEW = 'ap.add_argument("--end-silence", type=float, default=0.45)   # VG: 0.8 -> 0.45，收尾更快'


def main():
    if not os.path.isfile(TARGET):
        print("失败: 找不到 %s" % TARGET)
        return 1
    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()
    if "VG: 0.8 -> 0.45" in src:
        print("已经改过了，跳过")
        return 0
    if src.count(OLD) != 1:
        print("失败: 锚点出现 %d 次" % src.count(OLD))
        return 1
    src = src.replace(OLD, NEW, 1)
    bak = TARGET + ".bak-vgsil-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(TARGET, bak)
    tmp = TARGET + ".tmp-vgsil"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(src)
    os.replace(tmp, TARGET)
    import py_compile
    try:
        py_compile.compile(TARGET, cfile="/tmp/vgsil-check.pyc", doraise=True)
    except Exception as e:                                       # noqa: BLE001
        shutil.copy2(bak, TARGET)
        print("失败: 语法错误，已回滚: %s" % e)
        return 1
    print("已把 end-silence 改为 0.45 秒（备份 %s）" % bak)
    return 0


if __name__ == "__main__":
    sys.exit(main())
