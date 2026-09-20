#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读四台车的 /scan_raw，算出「前后左右各还有多少空间可走」。

判定规则与 ros_car.py 的 motion_rejection 一致：
  可用距离 = min{ 距离 · cos(相对角) : 相对角横向偏移在车宽半宽(0.18m)以内 }
  要求 可用距离 ≥ 车要走的距离 + 0.20m
"""
import asyncio
import json
import math
import sys

import websockets

ROBOT_HALF_WIDTH_M = 0.18
MOTION_CLEARANCE_M = 0.20
DIRS = (("前进", 0.0), ("后退", 180.0), ("左横移", 90.0), ("右横移", -90.0))


def directional_clearance(scan, direction_deg):
    direction = math.radians(direction_deg)
    available = math.inf
    angle = scan["angle_min"]
    for d in scan["ranges"]:
        if isinstance(d, (int, float)) and math.isfinite(d) and scan["range_min"] <= d <= scan["range_max"]:
            rel = angle - direction
            lon = d * math.cos(rel)
            lat = d * math.sin(rel)
            if lon > 0.0 and abs(lat) <= ROBOT_HALF_WIDTH_M:
                available = min(available, lon)
        angle += scan["angle_increment"]
    return available


async def one(ip):
    async with websockets.connect("ws://%s:9090" % ip, max_size=2 ** 22) as ws:
        await ws.send(json.dumps({"op": "subscribe", "topic": "/scan_raw", "id": "scan"}))
        t0 = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - t0 < 4.0:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            d = json.loads(msg)
            if d.get("topic") != "/scan_raw":
                continue
            scan = d["msg"]
            out = []
            for name, deg in DIRS:
                c = directional_clearance(scan, deg)
                out.append("%s %s" % (name, ("∞" if math.isinf(c) else "%.2f m" % c)))
            n = len(scan.get("ranges") or [])
            return "%s  点数 %d  |  %s" % (ip, n, "  ".join(out))
        return "%s  4 秒内没有 /scan_raw" % ip


async def main():
    ips = sys.argv[1:] or ["192.168.1.201", "192.168.1.202", "192.168.1.203", "192.168.1.204"]
    for ip in ips:
        try:
            print(await one(ip))
        except Exception as exc:
            print("%s  ERR %s" % (ip, exc))


asyncio.get_event_loop().run_until_complete(main())
