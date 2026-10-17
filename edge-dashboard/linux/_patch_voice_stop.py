#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给设备上的 voice_button.py 加「手动立即结束录音」能力（SIGUSR1）。

为什么需要：
    现状是 VAD 判句尾才结束 —— 阈值 `--end-silence` 默认 0.8 秒，
    实测安静环境下还要更久（日志里出现过一段 12.88 秒的录音）。
    界面上「按住说话」第二次按下想让录音**立刻**停下并送云端，
    就必须有一个从外部打断录音循环的信号。

为什么用 SIGUSR1 而不是别的：
    录音循环阻塞在 `proc.stdout.read(block)` 上，没有事件循环可用；
    信号处理器由内核在 read() 被中断时投递（Python 会在信号到达后
    设置标志并让 read 抛 InterruptedError 后自动重试），
    所以只要在循环里查一个全局标志即可，改动面最小。
    不碰 VAD 的判定逻辑，正常路径（不按第二次）行为完全不变。

幂等：脚本可重复执行，检测到已有标记就跳过。
"""
import io
import os
import re
import shutil
import sys
import time

TARGET = "/home/sunrise/voice_pipeline/voice_button.py"
MARK = "_VGSIG"

IMPORT_ANCHOR = "import shutil\n"
IMPORT_INSERT = "import shutil\nimport signal\n"

# 录音循环里「语音结束」的判定处插入手动结束分支。
# 注意必须精确匹配（含缩进），并且只在 record_utterance 里出现一次。
LOOP_ANCHOR = '                if silence * BLOCK_SEC >= args.end_silence or dur > args.max_utterance:\n'
LOOP_INSERT = (
    "                if " + MARK + "_STOP and in_speech:\n"
    "                    " + MARK + "_STOP = False\n"
    "                    if dur < args.min_utterance:\n"
    "                        print(\"  [录音] 手动结束但太短（%.2f s），丢弃\" % dur)\n"
    "                        args.last_rec_reason = \"short\"\n"
    "                        return None, 0.0\n"
    "                    path = args.save_wav\n"
    "                    with wave.open(path, \"wb\") as w:\n"
    "                        w.setnchannels(args.channels)\n"
    "                        w.setsampwidth(2)\n"
    "                        w.setframerate(args.rate)\n"
    "                        w.writeframes(bytes(buf))\n"
    "                    args.last_rec_reason = \"ok\"\n"
    "                    print(\"  [录音] 手动结束 -> %.2f 秒，立即送识别\" % dur)\n"
    "                    return path, dur\n"
) + LOOP_ANCHOR

# 每轮录音前清标志，避免上一轮的残留影响这一轮。
RESET_ANCHOR = "        wav, dur = record_utterance(args)\n"
RESET_INSERT = "        " + MARK + "_STOP = False   # 每轮开始前清掉上一轮的手动结束标志\n" + RESET_ANCHOR

# 读 / 写模块级标志的函数必须显式声明 global，否则 Python 把赋值当成
# 局部变量定义，读取时直接抛 UnboundLocalError（详见 main() 里的说明）。
REC_ANCHOR = "def record_utterance(args):\n"
REC_INSERT = REC_ANCHOR + "    global " + MARK + "_STOP   # 本函数内会读也会写这个全局标志\n"
ROUND_ANCHOR = "def one_round(args, trigger=None):\n"
ROUND_INSERT = ROUND_ANCHOR + "    global " + MARK + "_STOP   # 每轮开始前清标志\n"


def die(msg):
    print("失败: %s" % msg)
    sys.exit(1)


def main():
    if not os.path.isfile(TARGET):
        die("找不到 %s" % TARGET)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if MARK in src:
        # 已经打过补丁：检查是不是带诊断打印和 global 声明的新版，不是就升级。
        #
        # ⚠️ 判断「global 声明已就位」必须**只看 record_utterance 这一个函数**。
        #    曾经用整文件搜 "global _VGSIG_STOP"，结果信号处理器自己的那行
        #    就命中了，守卫误判成已完成 → 修复被静默跳过，
        #    现象是「补丁打过了但还是 UnboundLocalError 崩溃」。
        has_rec_global = REC_INSERT in src
        has_round_global = ROUND_INSERT in src
        has_diag = "SIGUSR1 处理器已注册" in src
        if has_rec_global and has_diag:
            print("已经是最新版补丁（global 声明 + 诊断打印），跳过")
            return 0

        bak0 = TARGET + ".bak-vgstop2-" + time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(TARGET, bak0)

        if not has_rec_global:
            '''
            【必须补这一步】record_utterance 里写了 `_VGSIG_STOP = False`
            （手动结束那次赋值），Python 因此把它判定为**局部变量**，
            于是读它的那一刻抛：
                UnboundLocalError: local variable '_VGSIG_STOP'
                                      referenced before assignment
            后果极隐蔽：录音进程当场崩掉，界面看到的是「等不到结果」超时，
            日志里那条 Traceback 还夹在一堆输出中间，很容易看漏（实测踩过）。
            '''
            if REC_ANCHOR not in src:
                die("找不到 record_utterance 定义，无法补 global 声明")
            src = src.replace(REC_ANCHOR, REC_INSERT, 1)
        if not has_round_global and ROUND_ANCHOR in src:
            src = src.replace(ROUND_ANCHOR, ROUND_INSERT, 1)

        if not has_diag:
            src = src.replace(
                "    " + MARK + "_STOP = True\n",
                "    " + MARK + "_STOP = True\n"
                "    print(\"  [录音] 收到 SIGUSR1（手动结束请求）\", flush=True)\n",
                1)
            src = src.replace(
                "except (ValueError, AttributeError):\n",
                "except (ValueError, AttributeError) as _e:\n"
                "    print(\"  [启动] SIGUSR1 注册失败：%s\" % _e, flush=True)\n",
                1)
            src = src.replace(
                "    signal.signal(signal.SIGUSR1, " + MARK + "_handler)\n",
                "    signal.signal(signal.SIGUSR1, " + MARK + "_handler)\n"
                "    print(\"  [启动] SIGUSR1 处理器已注册（手动结束录音可用）\", flush=True)\n",
                1)

        with io.open(TARGET + ".tmp-vgstop2", "w", encoding="utf-8") as f:
            f.write(src)
        os.replace(TARGET + ".tmp-vgstop2", TARGET)
        import py_compile
        try:
            py_compile.compile(TARGET, cfile="/tmp/vgstop2-check.pyc", doraise=True)
        except Exception as e:                                   # noqa: BLE001
            shutil.copy2(bak0, TARGET)
            die("升级补丁后语法错误，已回滚: %s" % e)
        print("已升级补丁（global 声明 + 诊断打印）: %s" % TARGET)
        print("  备份: %s" % bak0)
        return 0

    # ---- 1. import signal ----
    if "\nimport signal\n" not in src:
        if IMPORT_ANCHOR not in src:
            die("找不到 import 锚点（import shutil）")
        src = src.replace(IMPORT_ANCHOR, IMPORT_INSERT, 1)

    # ---- 2. 全局标志 + 信号处理器（挂在 BLOCK_SEC 之后，模块级） ----
    block_anchor = "BLOCK_SEC = 0.125\n"
    if block_anchor not in src:
        die("找不到 BLOCK_SEC 锚点")
    handler = block_anchor + (
        "\n# --- 手动立即结束录音（供 8124 桥的「第二次按下」用）---\n"
        "# SIGUSR1 只置标志；真正的收尾在 record_utterance 的循环里做，\n"
        "# 这样能保证缓冲区被完整写成 wav，而不是从信号处理器里硬中断。\n"
        + MARK + "_STOP = False\n"
        "\n"
        "def " + MARK + "_handler(signum, frame):\n"
        "    global " + MARK + "_STOP\n"
        "    " + MARK + "_STOP = True\n"
        "    # 把「信号真的到了」打到日志里。排查时必须看得到这一行：\n"
        "    # 没有它就无法区分「信号没送到」和「送到了但循环没查标志」。\n"
        "    print(\"  [录音] 收到 SIGUSR1（手动结束请求）\", flush=True)\n"
        "\n"
        "try:\n"
        "    signal.signal(signal.SIGUSR1, " + MARK + "_handler)\n"
        "    print(\"  [启动] SIGUSR1 处理器已注册（手动结束录音可用）\", flush=True)\n"
        "except (ValueError, AttributeError) as _e:\n"
        "    # 非主线程里注册会抛 ValueError；真机上助手跑在主线程，正常不会走到这\n"
        "    print(\"  [启动] SIGUSR1 注册失败：%s\" % _e, flush=True)\n"
    )
    src = src.replace(block_anchor, handler, 1)

    # ---- 3. 录音循环里的手动结束分支 ----
    if src.count(LOOP_ANCHOR) != 1:
        die("录音判定锚点出现 %d 次（应为 1 次）" % src.count(LOOP_ANCHOR))
    src = src.replace(LOOP_ANCHOR, LOOP_INSERT, 1)

    # ---- 4. 每轮开始前清标志 ----
    if src.count(RESET_ANCHOR) != 1:
        die("录音调用锚点出现 %d 次（应为 1 次）" % src.count(RESET_ANCHOR))
    src = src.replace(RESET_ANCHOR, RESET_INSERT, 1)

    # ---- 5. 读 / 写模块级标志的函数必须声明 global ----
    # 少了这一步，record_utterance 里的 `_VGSIG_STOP = False` 会让 Python
    # 把它当局部变量，读的时候直接 UnboundLocalError 崩溃（实测踩过）。
    if REC_ANCHOR not in src:
        die("找不到 record_utterance 定义")
    src = src.replace(REC_ANCHOR, REC_INSERT, 1)
    if ROUND_ANCHOR in src:
        src = src.replace(ROUND_ANCHOR, ROUND_INSERT, 1)
    else:
        print("  提示: 没找到 one_round 定义，跳过它的 global 声明")

    bak = TARGET + ".bak-vgstop-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(TARGET, bak)
    tmp = TARGET + ".tmp-vgstop"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(src)
    os.replace(tmp, TARGET)

    print("已打补丁: %s" % TARGET)
    print("  备份:     %s" % bak)
    print("  原大小:   %d 字节" % os.path.getsize(bak))
    print("  新大小:   %d 字节" % os.path.getsize(TARGET))
    print("  校验:     语法编译 …")
    import py_compile
    try:
        py_compile.compile(TARGET, cfile="/tmp/vgstop-check.pyc", doraise=True)
        print("            语法 OK")
    except Exception as e:                                       # noqa: BLE001
        shutil.copy2(bak, TARGET)
        die("语法编译失败，已回滚: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
