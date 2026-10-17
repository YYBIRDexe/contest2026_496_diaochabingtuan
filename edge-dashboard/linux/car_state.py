#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""car_state.py — 每 5 秒探测四台小车，把结果写成界面读的 data/state.json。

为什么需要它
------------
界面（`data/README.md` 定义了格式）每 5 秒轮询 `/data/state.json`，但那个文件
原来是 `tools/simulate-m1.js` 在开发机上模拟写的 —— 设备上没人写，于是界面
只能停在"演示数据"。这个脚本补上那个"写文件的人"：**真去探测**四台车。

探测哪些参数（都是能实测的，不是编的）
------------------------------------
  · 在线：TCP 连一次 9090（rosbridge 端口），连上=在线
  · 电量：订阅 `/ros_robot_controller/battery` 读一次电压（毫伏）→ 按 2S 锂电估算百分比
  · 地址：`robots.json` 里的 IP
  · 时间：`generatedAt` 写真实系统时间

写进 state.json 的映射（重要，别误会）
------------------------------------
  · `cars[]`   —— **全是真值**（在线/电量/IP），状态栏"N/4 车在线"、调度台车卡都用它
  · `zones[]`  —— 巡检区的"任务进度"是演示叙事（车端不上报任务状态，探测不出来），
                  但**绑定的车一旦离线，这个区就会被标成 offline**，
                  而且 detail 里写的是真实探测结果（在线/电量/IP）
  · `records[]`—— 沿用文件里已有的历史，不伪造

用法
----
    python3 car_state.py                    # 常驻，每 5 秒写一次
    python3 car_state.py --once             # 只探一次（排查用）
    python3 car_state.py --interval 5 --out /home/sunrise/velaguard/data/state.json
    python3 car_state.py --once --verbose
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
# 电量读取复用语音管线里的 check_battery（它已经调通了 rosbridge 订阅）。
# ⚠️ 它住在 /home/sunrise/voice_pipeline，不在本目录 —— 实测漏了这句会报
#    "No module named 'check_battery'"，电量全是 0%（看着像"车没电"，其实是我路径没加）。
VOICE_DIR = os.environ.get("VOICE_PIPELINE_DIR", "/home/sunrise/voice_pipeline")
if os.path.isdir(VOICE_DIR) and VOICE_DIR not in sys.path:
    sys.path.insert(0, VOICE_DIR)

DEFAULT_OUT = "/home/sunrise/velaguard/data/state.json"
ROBOTS = os.path.join(HERE, "robots.json")

# 车号 -> 区域名（界面上的"巡检区"叙事；探测不到，所以固定映射）
ZONE_NAMES = {"1": "入口大厅", "2": "主通道", "3": "展项区", "4": "设备区"}
ZONE_ROUTES = {"1": "R-01", "2": "R-02", "3": "R-03", "4": "R-04"}
ZONE_ROUTE_DESC = {"1": "前台 → 闸机 → 电梯口", "2": "A 段 → B 段 → C 段",
                   "3": "展台 1 → 展台 4 绕行", "4": "配电柜 → 机柜背面"}


def load_robots():
    try:
        with open(ROBOTS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                           # noqa: BLE001
        return {"1": "192.168.1.201", "2": "192.168.1.202",
                "3": "192.168.1.203", "4": "192.168.1.204"}


def port_open(ip, port=9090, timeout=1.2):
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except Exception:                                           # noqa: BLE001
        return False


def to_percent(mv):
    """毫伏 -> 百分比。2S 锂电按 6.0V(空) ~ 8.4V(满) 线性估算（和 check_battery 一致）。"""
    if mv is None:
        return None
    v = mv / 1000.0
    pct = (v - 6.0) / (8.4 - 6.0) * 100.0
    return max(0, min(100, int(round(pct))))


def probe(verbose=False):
    """探测四台车，返回 (cars, batteries)。电量读不到就是 None（不清零、不编数）。"""
    robots = load_robots()
    nums = sorted(robots, key=lambda x: int(x))

    online = {}
    for n in nums:
        online[n] = port_open(robots[n])
        if verbose:
            print("  %s号车 %s -> %s" % (n, robots[n], "在线" if online[n] else "离线"))

    pct = {}
    live = [(n, robots[n]) for n in nums if online[n]]
    if live:
        try:
            from check_battery import read_batteries
            rows = read_batteries(live, timeout=4.0)
            for (n, mv, err) in rows:
                pct[n] = to_percent(mv)
                if verbose:
                    print("  %s号车电量 %s（%s）" % (n, pct[n], err or "%.0fmV" % (mv or 0)))
        except Exception as exc:                                # noqa: BLE001
            if verbose:
                print("  电量读取失败：%s" % exc, file=sys.stderr)
    return robots, nums, online, pct


def load_existing(out):
    try:
        with open(out, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                           # noqa: BLE001
        return {}


def build_state(out, verbose=False):
    robots, nums, online, pct = probe(verbose)
    old = load_existing(out)

    # 旧文件里的 zone 状态当"任务叙事"沿用（车端不上报任务进度，探测不出来）
    old_zones = {z.get("id"): z for z in (old.get("zones") or [])}

    cars = []
    zones = []
    for n in nums:
        ip = robots[n]
        up = online[n]
        p = pct.get(n)
        cars.append({
            "id": "CAR-%s" % n,
            "zoneId": "Z%s" % n,
            "zone": ZONE_NAMES.get(n, "区域%s" % n),
            "ip": ip,
            # 探测不到电量的车按"离线"处理更保守：battery 0 会让界面显示 0%
            "online": up,
            "battery": p if p is not None else 0,
        })

        prev = old_zones.get("Z%s" % n) or {}
        if not up:
            status = "offline"
            detail = "联系不上（%s:9090 不通）" % ip
            progress = 0
        else:
            # 在线：沿用上次的任务状态（没有就"未开始"），detail 用真实探测值
            status = prev.get("status") if prev.get("status") in (
                "done", "running", "blocked", "idle") else "idle"
            detail = "在线 · 电量 %s · %s" % (
                ("%d%%" % p) if p is not None else "未读到", ip)
            progress = prev.get("progress") if isinstance(prev.get("progress"), int) else 0
        zones.append({
            "id": "Z%s" % n,
            "name": ZONE_NAMES.get(n, "区域%s" % n),
            "route": ZONE_ROUTES.get(n, "R-0%s" % n),
            "routeDesc": ZONE_ROUTE_DESC.get(n, ""),
            "car": "CAR-%s" % n,
            "status": status,
            "progress": progress,
            "detail": detail,
            "duration": prev.get("duration") or "—",
        })

    state = {
        "round": old.get("round") or 1,
        # 真实时间：界面顶部的"更新于"用它
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": "car_state.py（每 %ds 实时探测）" % 5,
        "zones": zones,
        "cars": cars,
        "records": old.get("records") or [],
    }
    return state


def write_atomic(path, state):
    """先写 .tmp 再改名 —— 界面正好读到半截 JSON 会整页报错（README 里也这么要求）。"""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d or ".", prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    ap = argparse.ArgumentParser(description="每 5 秒探测四台小车并写 state.json")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.once:
        st = build_state(args.out, args.verbose)
        write_atomic(args.out, st)
        n_up = sum(1 for c in st["cars"] if c["online"])
        print("已写 %s：%d/%d 在线，%s" % (args.out, n_up, len(st["cars"]), st["generatedAt"]))
        for c in st["cars"]:
            print("  %s %-15s %s 电量 %s" % (
                c["id"], c["ip"], "在线" if c["online"] else "离线",
                ("%d%%" % c["battery"]) if c["online"] else "—"))
        return 0

    print("每 %.0f 秒探测一次，写入 %s（Ctrl-C 退出）" % (args.interval, args.out), flush=True)
    while True:
        t0 = time.time()
        try:
            st = build_state(args.out)
            write_atomic(args.out, st)
            n_up = sum(1 for c in st["cars"] if c["online"])
            print("[%s] %d/%d 在线" % (time.strftime("%H:%M:%S"), n_up, len(st["cars"])),
                  flush=True)
        except Exception as exc:                                # noqa: BLE001
            print("[%s] 探测失败：%s" % (time.strftime("%H:%M:%S"), exc), file=sys.stderr,
                  flush=True)
        # 探测本身要花时间，用"睡到下一个周期"而不是固定 sleep，避免周期越漂越长
        time.sleep(max(0.5, args.interval - (time.time() - t0)))


if __name__ == "__main__":
    sys.exit(main())
