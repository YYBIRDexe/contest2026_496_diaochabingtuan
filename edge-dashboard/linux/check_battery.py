#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_battery.py — 查询四辆小车的电池电量，并给出一句适合播报的短结论。

为什么要它
----------
用户会问「小车的电量怎么样了」——这原本被云端模型归到了 `status`（查里程计），
答非所问。车端其实有电量话题 `/ros_robot_controller/battery`（实测能读到数值），
本脚本配上新的 `battery` 意图，让助手能真的去读电量、并把结果**说出来**。

⚠️ **只读**：只连接 rosbridge 订阅电量话题，不发布任何指令 —— 车不会动。

输出约定（与 check_cars.py 一致）
--------------------------------
给人看的明细打到 stdout；
最后一行是 `@@SPEAK@@<短句>` —— voice_button.py 会把这行**用语音播报**出来。
短句刻意压到十几个字以内：现场噪音大，长了听不清重点。

电量换算说明
------------
话题 `data` 字段是**毫伏**（实测 7041 左右，即 7.04 V）。
按 2S 锂电的常见区间 **6.0 V(空) ~ 8.4 V(满)** 做**线性**估算。
这是粗略换算：锂电放电曲线不是直线，中段平坦。
所以播报时**一起念出电压**，百分比只当参考 —— 这样即使换算有偏差，
用户听到的原始数据也是准的。

用法
----
    python3 check_battery.py                 # 查四台，播报汇总
    python3 check_battery.py --car 2         # 只查 2 号车
    python3 check_battery.py --json          # 额外输出一行 JSON
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROBOTS = os.path.join(HERE, "robots.json")

TOPIC = "/ros_robot_controller/battery"
CN = {0: "零", 1: "一", 2: "两", 3: "三", 4: "四"}

# 2S 锂电的线性估算区间（伏）
V_EMPTY = 6.0
V_FULL = 8.4


def load_robots():
    try:
        with open(ROBOTS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"1": "192.168.1.201", "2": "192.168.1.202",
                "3": "192.168.1.203", "4": "192.168.1.204"}


def to_percent(volts):
    """按 2S 线性区间估算百分比，夹到 0~100。"""
    if volts <= 0:
        return 0
    pct = (volts - V_EMPTY) / (V_FULL - V_EMPTY) * 100.0
    return int(max(0, min(100, round(pct))))


async def _read_one(ip, timeout=6.0):
    """
    连 rosbridge 读一次电量。返回 (毫伏, 错误信息)。
    只订阅、不发布；读到第一条就断开。
    """
    try:
        import websockets
    except ImportError:
        return None, "缺少 websockets 库"

    try:
        async with websockets.connect("ws://%s:9090" % ip,
                                      open_timeout=4, max_size=2 ** 22) as ws:
            await ws.send(json.dumps({"op": "subscribe", "topic": TOPIC,
                                      "id": "bat"}))
            loop = asyncio.get_event_loop()
            t0 = loop.time()
            while loop.time() - t0 < timeout:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                if m.get("op") == "publish" and m.get("topic") == TOPIC:
                    val = (m.get("msg") or {}).get("data")
                    if isinstance(val, (int, float)):
                        return float(val), ""
            return None, "%.0f 秒内没读到电量" % timeout
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)[:60]


async def _read_many(items, timeout=6.0):
    """
    并发读多台车，返回 [(车号, 毫伏, 错误), ...]。

    为什么要并发：串行读四台、每台最长等 timeout，最坏要 4×6=24 秒，
    语音助手那边早就不耐烦了。并发后总耗时约等于最慢的那一台。
    """
    results = await asyncio.gather(
        *[_read_one(ip, timeout) for (_n, ip) in items],
        return_exceptions=True)
    out = []
    for (n, _ip), r in zip(items, results):
        if isinstance(r, Exception):
            out.append((n, None, str(r)[:60]))
        else:
            out.append((n, r[0], r[1]))
    return out


def read_batteries(items, timeout=6.0):
    """同步包装：并发读多台。items 是 [(车号, ip), ...]。"""
    try:
        return asyncio.run(_read_many(items, timeout))
    except Exception as exc:  # noqa: BLE001
        return [(n, None, str(exc)[:60]) for (n, _ip) in items]


def speak_line(rows):
    """
    拼一句适合播报的短结论。

    rows: [{"num":1,"mv":7041,"pct":50,"err":""}, ...]
    """
    ok = [r for r in rows if r["mv"] is not None]
    bad = [r for r in rows if r["mv"] is None]

    if not ok:
        """
        一台都没读到 —— 最常见的原因不是脚本坏了，而是**车没上电/没连上**。
        所以话术要指路（先看小车开没开），而不是丢一句「读不到」让人无从下手。
        播报要短，所以只保留最短的那句；明细在 stdout 里。
        """
        if len(rows) == 1:
            return "%d号车联系不上" % rows[0]["num"]
        return "四台小车都联系不上，读不到电量"

    # 只查了一台：直接念它的电压和百分比
    if len(rows) == 1:
        r = rows[0]
        return "%d号车电量百分之%d，电压%.1f伏" % (r["num"], r["pct"], r["mv"] / 1000.0)

    # 多台：念最低那台（最需要关注的）与读数范围
    lowest = min(ok, key=lambda r: r["mv"])
    if len(ok) == 1:
        return "只有%d号车在线，电量百分之%d" % (lowest["num"], lowest["pct"])

    if bad:
        down = "、".join("%d号" % r["num"] for r in bad)
        return "%s读不到；最低%d号车百分之%d" % (down, lowest["num"], lowest["pct"])

    # 全部读到：报最低与最高，让人知道电量是否均衡
    highest = max(ok, key=lambda r: r["mv"])
    if lowest["num"] == highest["num"]:
        return "%d号车电量百分之%d" % (lowest["num"], lowest["pct"])
    return "最低%d号百分之%d，最高%d号百分之%d" % (
        lowest["num"], lowest["pct"], highest["num"], highest["pct"])


def main():
    ap = argparse.ArgumentParser(description="查询小车电量（只读，不动车）")
    ap.add_argument("--car", help="只查指定车号，如 2")
    ap.add_argument("--json", action="store_true", help="额外输出一行 JSON")
    ap.add_argument("--timeout", type=float, default=6.0,
                    help="每台车的等待上限（秒），默认 6")
    args = ap.parse_args()

    robots = load_robots()
    if args.car:
        nums = [n for n in robots if n == str(args.car)]
        if not nums:
            print("没有 %s 号车的配置" % args.car)
            print("@@SPEAK@@没有这台车")
            return 0
    else:
        nums = sorted(robots, key=lambda x: int(x))

    print("小车电量查询（只读订阅 %s，未发任何指令）" % TOPIC)

    # 并发读：串行的话四台最坏要等 4 倍时间，语音那边等不起
    items = [(n, robots[n]) for n in nums]
    first = read_batteries(items, args.timeout)

    rows = []
    for (n, mv, err) in first:
        row = {"num": int(n), "ip": robots[n], "mv": mv,
               "pct": to_percent(mv / 1000.0) if mv else 0, "err": err}
        rows.append(row)
        if mv is None:
            print("  %s号车 %-15s 读不到（%s）" % (n, row["ip"], err))
        else:
            print("  %s号车 %-15s %.3f V  约 %d%%"
                  % (n, row["ip"], mv / 1000.0, row["pct"]))

    line = speak_line(rows)
    print("@@SPEAK@@%s" % line)

    if args.json:
        print(json.dumps({"battery": rows, "say": line}, ensure_ascii=False))

    # **必须返回 0**：某台车读不到是一个"正常的答案"，不是命令执行失败。
    # 返回非 0 会让 vcmd 报退出码 8，voice_button 就会误报"执行失败"。
    return 0


if __name__ == "__main__":
    sys.exit(main())
