#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读：连上车的 rosbridge 订阅 /odom，打印 x/y/yaw（厘米/度）。不发任何速度。"""
import asyncio, json, math, sys
import websockets


def yaw_of(q):
    x = (q or {}).get("x", 0.0) or 0.0
    y = (q or {}).get("y", 0.0) or 0.0
    z = (q or {}).get("z", 0.0) or 0.0
    w = (q or {}).get("w", 1.0) or 1.0
    return math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))


async def once(ip, seconds=3.0):
    url = "ws://%s:9090" % ip
    async with websockets.connect(url, max_size=2 ** 22) as ws:
        await ws.send(json.dumps({"op": "subscribe", "topic": "/odom", "id": "odom"}))
        last, n, t0 = None, 0, asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - t0 < seconds:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
            except asyncio.TimeoutError:
                continue
            d = json.loads(msg)
            if d.get("topic") != "/odom":
                continue
            p = d["msg"]["pose"]["pose"]
            last = (float(p["position"]["x"]), float(p["position"]["y"]),
                    yaw_of(p.get("orientation")))
            n += 1
        return last, n


def main():
    ips = sys.argv[1:] or ["192.168.1.201", "192.168.1.202", "192.168.1.203", "192.168.1.204"]
    loop = asyncio.get_event_loop()
    for ip in ips:
        try:
            last, n = loop.run_until_complete(once(ip))
        except Exception as e:
            print("%-16s ERR %s" % (ip, e))
            continue
        if not last:
            print("%-16s 没有 /odom 数据" % ip)
            continue
        print("%-16s x=%7.3f y=%7.3f yaw=%7.1f°  (odom %d 帧)" % (ip, last[0], last[1], last[2], n))


if __name__ == "__main__":
    main()
