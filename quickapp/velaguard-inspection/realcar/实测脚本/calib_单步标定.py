#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真车标定 v2：把 /odom 读取放进后台任务（上一版在 subprocess.run 里阻塞了 recv，
导致读到的永远是同一个值 —— 那个「位移 0.000」是测量方法坏了，不是车没动）。"""
import asyncio
import json
import math
import subprocess
import sys
import time

import websockets

CAR = "192.168.1.201"
ROS_CAR = "/home/sunrise/voice_pipeline/ros_car.py"
SAMPLES = []


def yaw_deg(q):
    x = (q or {}).get("x", 0.0) or 0.0
    y = (q or {}).get("y", 0.0) or 0.0
    z = (q or {}).get("z", 0.0) or 0.0
    w = (q or {}).get("w", 1.0) or 1.0
    return math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))


async def recorder(stop_evt, started_evt):
    async with websockets.connect("ws://%s:9090" % CAR, max_size=2 ** 22) as ws:
        await ws.send(json.dumps({"op": "subscribe", "topic": "/odom", "id": "odom"}))
        started_evt.set()
        while not stop_evt.is_set():
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=0.4)
            except asyncio.TimeoutError:
                continue
            d = json.loads(msg)
            if d.get("topic") != "/odom":
                continue
            p = d["msg"]["pose"]["pose"]
            SAMPLES.append((time.time(), float(p["position"]["x"]),
                            float(p["position"]["y"]), yaw_deg(p.get("orientation"))))


def mark(label):
    SAMPLES.append((time.time(), None, None, label))


def proj_along(u, a, b):
    dx, dy = b[1] - a[1], b[2] - a[2]
    yaw0 = math.radians(a[3])
    ux, uy = math.cos(yaw0 + u), math.sin(yaw0 + u)
    return dx * ux + dy * uy, math.hypot(dx, dy), b[3] - a[3]


async def main():
    stop = asyncio.Event()
    started = asyncio.Event()
    rec = asyncio.create_task(recorder(stop, started))
    await started.wait()
    await asyncio.sleep(1.5)

    print("=== 1) 静止 6 秒：/odom 会不会自己漂 ===")
    a = SAMPLES[-1]
    await asyncio.sleep(6.0)
    b = SAMPLES[-1]
    print("  %.4f,%.4f → %.4f,%.4f   位移 %.4f m, 角度 %+.2f°  (%d 帧)"
          % (a[1], a[2], b[1], b[2], math.hypot(b[1] - a[1], b[2] - a[2]),
             b[3] - a[3], len(SAMPLES)))

    for cmd, extra_rad, label in (("FORWARD", 0.0, "前进"),
                                  ("STRAFE_LEFT", math.pi / 2, "左横移"),
                                  ("BACKWARD", math.pi, "后退"),
                                  ("STRAFE_RIGHT", -math.pi / 2, "右横移")):
        print()
        print("=== %s (%s) 0.50 m ===" % (cmd, label))
        await asyncio.sleep(0.6)
        before = SAMPLES[-1]
        n0 = len(SAMPLES)
        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, ROS_CAR, "--robots", "1", "--cmd", cmd,
             "--set", "distance_m=0.50", "--set", "speed=0.15"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        dur = time.time() - t0
        await asyncio.sleep(0.8)
        after = SAMPLES[-1]
        reported = proc.stdout.decode("utf-8", "replace").strip().splitlines()[-1].strip()
        proj, dist, dyaw = proj_along(extra_rad, before, after)
        print("  ros_car：%s   （用时 %.1f s，退出码 %d）" % (reported, dur, proc.returncode))
        print("  实测：沿该方向 %.3f m ｜ 直线 %.3f m ｜ 净转 %+.2f° ｜ %d 帧"
              % (proj, dist, dyaw, len(SAMPLES) - n0))

    stop.set()
    await rec
    print()
    print("总采样 %d 帧" % len([s for s in SAMPLES if s[1] is not None]))


asyncio.get_event_loop().run_until_complete(main())
