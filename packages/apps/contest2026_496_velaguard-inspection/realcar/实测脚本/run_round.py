#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从笔记本驱动一次真车巡检并全程观察（通过 M1 上的 HTTP 接口）。"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8127"


def call(path, method="GET", timeout=30):
    req = urllib.request.Request(BASE + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 409/400 也要把 body 读出来 —— 拒绝的理由就写在里面
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "message": "HTTP %s" % exc.code}


def line(st):
    parts = []
    for z in st.get("zones", []):
        parts.append("CAR%s:%s/%s%%" % (z.get("car"), z.get("status"), z.get("progress")))
    return "round=%s %-8s | %s" % (st.get("round"), st.get("status"), "  ".join(parts))


def main():
    if "--stop" in sys.argv:
        st = call("/patrol/stop", "POST")
        print("stop:", st.get("message"))
        return 0
    print("before:", line(call("/patrol/status")))
    try:
        st = call("/patrol/start", "POST", timeout=60)
    except Exception as exc:
        print("start failed:", exc)
        return 1
    print("start:", st.get("ok"), st.get("message"))
    if not st.get("ok"):
        return 1
    t0 = time.time()
    while time.time() - t0 < 80:
        time.sleep(3)
        st = call("/patrol/status")
        print("t+%2ds  %s" % (int(time.time() - t0), line(st)))
        if st.get("status") != "running":
            break
    print()
    print("=== 每一步的实际结果 ===")
    for z in (st.get("zones") or []):
        print("CAR-%s %s（%s）→ %s" % (z.get("car"), z.get("zoneName"), z.get("routeName"), z.get("status")))
        print("   %s" % z.get("detail"))
        for s in (z.get("stepLog") or []):
            print("   %d. %-14s %-12s %.2f m  完成=%.3f m  %s"
                  % (s["step"], s["label"], s["op"], s["m"],
                     (s.get("measured_m") if s.get("measured_m") is not None else -1),
                     "ok" if s.get("ok") else s.get("note")))
    print()
    for e in (st.get("events") or [])[-8:]:
        print("  %s  %s" % (e.get("ts"), e.get("text")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
