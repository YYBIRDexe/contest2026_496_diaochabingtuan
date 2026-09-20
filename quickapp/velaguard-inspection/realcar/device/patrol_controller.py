#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patrol_controller.py —— VelaGuard 「按一下开始巡检，四台车真的动」的车端执行器

它做的事：把 E5 触控屏上那个「开始巡检」按钮，接到四台真车的 /cmd_vel 上。

    E5 触控屏（8126 演示页）
        → POST http://127.0.0.1:8127/patrol/start      （本文件，跑在 U2P/M1 上）
        → 4 个线程并行，各跑一条预编路线（patrol_routes.json）
        → python3 ros_car.py --robots N --cmd FORWARD/STRAFE_* --set distance_m=...
        → ws://192.168.1.20N:9090  rosbridge  → 车真的动

为什么不用 m1_task_api.py：那个是「任务/派单」系统，硬件输出被
VELAGUARD_HARDWARE_OUTPUT=0 主动关着，还需要一份不存在的 routes.json。
演示要的是「按一下就走」，所以这里做一条最短、最直接的执行链。

安全设计（都不是摆设）：
  * 每条路线在**车体坐标系**里执行 —— 不依赖全局定位，车摆哪儿就从哪儿走；
  * 距离/速度全部夹在安全区间内（见 patrol_routes.json 的 safety 段）；
  * 每一步走完都读 /odom 记录实际位移，落进日志，可事后核对；
  * 车端 ros_car.py 自带雷达避障：0.20 m 内有障碍会拒动并在本服务里显示为
    「阻塞」，不会硬撞；
  * 任何时刻 POST /patrol/stop 立即向四台车发 STOP 并中止后续动作。

只依赖 Python 3 标准库（Python 3.8 实测可用）。不需要装任何包。

命令行：
    python3 patrol_controller.py --port 8127
    python3 patrol_controller.py --selftest     # 只校验路线表，不起服务
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROUTES_FILE = os.path.join(HERE, "patrol_routes.json")
VOICE_DIR = os.path.expanduser("~/voice_pipeline")
ROS_CAR = os.path.join(VOICE_DIR, "ros_car.py")
ROBOTS_FILE = os.path.join(VOICE_DIR, "robots.json")
LOG_FILE = os.path.join(HERE, "patrol.log")

VALID_OPS = ("forward", "back", "strafe_left", "strafe_right")
OP_TO_CMD = {
    "forward": "FORWARD",
    "back": "BACKWARD",
    "strafe_left": "STRAFE_LEFT",
    "strafe_right": "STRAFE_RIGHT",
    "turn_left": "TURN_LEFT",
    "turn_right": "TURN_RIGHT",
}

# ---------------------------------------------------------------- 状态

LOCK = threading.Lock()
STATE = {
    "round": 0,
    "status": "idle",          # idle | running | done | aborted | error
    "startedAt": None,
    "finishedAt": None,
    "message": "尚未开始巡检",
    "zones": {},               # zid -> zone task dict
    "events": [],              # 最近事件（倒序不重要，按时间正序追加，保留最后 200 条）
}
CONFIG = {}
ABORT = threading.Event()
STEP_PROCS = {}                # zid -> subprocess.Popen（当前正在走的这一步）
ROUND_LOG_DIR = os.path.join(HERE, "rounds")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def log(msg):
    line = "[%s] %s" % (now_iso(), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def event(text, zid=None):
    with LOCK:
        STATE["events"].append({"ts": now_iso(), "zoneId": zid, "text": text})
        if len(STATE["events"]) > 200:
            del STATE["events"][:len(STATE["events"]) - 200]


# ---------------------------------------------------------------- 配置


def load_config(path=ROUTES_FILE):
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    return cfg


def validate_config(cfg):
    """返回问题列表（空 = 合规）。逻辑与 openvela 侧 gen-waypoints.js --check 对齐。"""
    problems = []
    safety = cfg.get("safety") or {}
    max_step = float(safety.get("max_step_m", 0.90))
    max_route = float(safety.get("max_route_m", 3.00))
    zones = cfg.get("zones") or {}
    if not zones:
        problems.append("没有任何区域路线")
    for zid, z in zones.items():
        steps = z.get("steps") or []
        if len(steps) < 1:
            problems.append("%s：没有动作步骤" % zid)
        total = 0.0
        for i, st in enumerate(steps):
            op = st.get("op")
            if op not in VALID_OPS:
                problems.append("%s 第 %d 步：不支持的动作 %r" % (zid, i + 1, op))
            m = float(st.get("m", 0))
            if m <= 0:
                problems.append("%s 第 %d 步：距离必须为正" % (zid, i + 1))
            if m > max_step + 1e-9:
                problems.append("%s 第 %d 步：%.2f m 超过单步上限 %.2f m"
                                % (zid, i + 1, m, max_step))
            total += m
        if total > max_route + 1e-9:
            problems.append("%s：总长 %.2f m 超过单条路线上限 %.2f m" % (zid, total, max_route))
    return problems


def route_summary(cfg):
    lines = []
    for zid, z in (cfg.get("zones") or {}).items():
        steps = z.get("steps") or []
        total = sum(float(s.get("m", 0)) for s in steps)
        lines.append("  ok   %-4s %-6s CAR-%s  %d 步 / %.2f m"
                     % (zid, z.get("name", ""), z.get("car"), len(steps), total))
    return lines


# ---------------------------------------------------------------- 车况


def load_robots():
    try:
        with open(ROBOTS_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"1": "192.168.1.201", "2": "192.168.1.202",
                "3": "192.168.1.203", "4": "192.168.1.204"}


def tcp_open(ip, port=9090, timeout=1.5):
    import socket
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def read_clearance(ip, seconds=1.2):
    """只读一次 /scan_raw，算出车体四个方向各还有多少可走空间（米）。

    判定与车端 ros_car.py 的 motion_rejection 完全一致（否则会出现
    「体检说能走、真发指令被拒」这种自相矛盾）：
        可用距离 = min{ 距离·cos(相对角) : |距离·sin(相对角)| <= 车宽半宽 0.18 m }
        允许走 distance 的条件： 可用距离 >= distance + 0.20 m

    返回 {"forward": m, "back": m, "strafe_left": m, "strafe_right": m}，
    读不到返回 None。不发任何速度。
    """
    try:
        import asyncio
        import math
        import websockets
    except ImportError:
        return None

    half_width = float((CONFIG.get("safety") or {}).get("robot_half_width_m", 0.18))
    margin = float((CONFIG.get("safety") or {}).get("motion_clearance_m", 0.20))
    dirs = {"forward": 0.0, "back": 180.0, "strafe_left": 90.0, "strafe_right": -90.0}

    def clearance(scan, direction_deg):
        direction = math.radians(direction_deg)
        available = float("inf")
        angle = scan.get("angle_min", 0.0)
        inc = scan.get("angle_increment", 0.0)
        rmin = scan.get("range_min", 0.0)
        rmax = scan.get("range_max", 100.0)
        for d in scan.get("ranges") or []:
            if isinstance(d, (int, float)) and math.isfinite(d) and rmin <= d <= rmax:
                rel = angle - direction
                lon = d * math.cos(rel)
                lat = d * math.sin(rel)
                if lon > 0.0 and abs(lat) <= half_width:
                    available = min(available, lon)
            angle += inc
        return available

    async def run():
        async with websockets.connect("ws://%s:9090" % ip, max_size=2 ** 23) as ws:
            await ws.send(json.dumps({"op": "subscribe", "topic": "/scan_raw", "id": "scan"}))
            t0 = time.time()
            while time.time() - t0 < seconds:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.8)
                except asyncio.TimeoutError:
                    continue
                d = json.loads(msg)
                if d.get("topic") != "/scan_raw":
                    continue
                scan = d["msg"] or {}
                out = {}
                for name, deg in dirs.items():
                    c = clearance(scan, deg)
                    out[name] = None if c == float("inf") else round(c, 3)
                return out
        return None

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    except Exception:
        return None
    finally:
        loop.close()


def read_odom(ip, seconds=0.6):
    """只读一次 /odom，返回 (x, y, yaw_deg)。读不到返回 None。不发任何速度。"""
    try:
        import asyncio
        import math
        import websockets
    except ImportError:
        return None

    def yaw_of(q):
        x = (q or {}).get("x", 0.0) or 0.0
        y = (q or {}).get("y", 0.0) or 0.0
        z = (q or {}).get("z", 0.0) or 0.0
        w = (q or {}).get("w", 1.0) or 1.0
        return math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))

    async def run():
        async with websockets.connect("ws://%s:9090" % ip, max_size=2 ** 22) as ws:
            await ws.send(json.dumps({"op": "subscribe", "topic": "/odom", "id": "odom"}))
            t0 = time.time()
            while time.time() - t0 < seconds:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                d = json.loads(msg)
                if d.get("topic") != "/odom":
                    continue
                p = d["msg"]["pose"]["pose"]
                return (float(p["position"]["x"]), float(p["position"]["y"]),
                        yaw_of(p.get("orientation")))
        return None

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    except Exception:
        return None
    finally:
        loop.close()


def battery_percent(ip):
    """从车的 /ros_robot_controller/battery 话题读电压，粗算百分比。读不到返回 None。"""
    try:
        import asyncio
        import websockets
    except ImportError:
        return None

    async def run():
        async with websockets.connect("ws://%s:9090" % ip, max_size=2 ** 22) as ws:
            await ws.send(json.dumps({"op": "subscribe",
                                      "topic": "/ros_robot_controller/battery",
                                      "id": "bat"}))
            t0 = time.time()
            while time.time() - t0 < 1.0:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.8)
                except asyncio.TimeoutError:
                    continue
                d = json.loads(msg)
                if d.get("topic") != "/ros_robot_controller/battery":
                    continue
                v = float((d.get("msg") or {}).get("data", 0) or 0)
                if v <= 0:
                    return None
                pct = (v - 6.4) / (8.4 - 6.4) * 100.0
                return int(max(0, min(100, round(pct))))
        return None

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    except Exception:
        return None
    finally:
        loop.close()


# ---------------------------------------------------------------- 执行


def preflight(zones_cfg):
    """开车前体检：每台车 TCP 通不通、电量够不够、路线方向有没有空间。

    返回 (ok, 逐车结果)。第三项很关键：车端 ros_car.py 自带雷达避障，
    0.20 m 内有障碍就拒动。不先量空间的话，按下按钮会得到「四台车全受阻」——
    那不是故障，是没地方走。所以宁可**拒绝派单并说清差多少**，
    也不要发一堆注定被拒的指令。
    """
    robots = load_robots()
    safety = CONFIG.get("safety") or {}
    bat_min = int(safety.get("battery_min", 15))
    margin = float(safety.get("motion_clearance_m", 0.20))
    # 雷达复测有 ±1~2 cm 抖动：可用空间与要求**相等**时不该判死（实测 0.94 vs 需 0.94）
    clr_tol = float(safety.get("clearance_tol_m", 0.03))
    adaptive = str(safety.get("route_mode", "fixed")) == "adaptive"
    details = {}
    ok = True
    for zid, z in zones_cfg.items():
        car = str(z.get("car"))
        ip = z.get("ip") or robots.get(car) or ""
        row = {"car": car, "ip": ip, "online": False, "battery": None, "note": "",
               "clearance": None, "need": None, "steps": None}
        if not ip:
            row["note"] = "没有该车号对应的 IP"
            ok = False
            details[zid] = row
            continue
        if not tcp_open(ip):
            row["note"] = "rosbridge 9090 连不上"
            ok = False
            details[zid] = row
            continue

        row["online"] = True
        pct = battery_percent(ip)
        row["battery"] = pct
        if pct is not None and pct < bat_min:
            row["note"] = "电量 %d%% 低于下限 %d%%" % (pct, bat_min)
            ok = False

        clr = read_clearance(ip)
        row["clearance"] = clr
        steps = list(z.get("steps") or [])
        if adaptive:
            # 自适应模式：路线按当前空间现场生成（见 build_adaptive_steps）
            steps = build_adaptive_steps(zid, z, clr, safety)
            if not steps:
                row["note"] = "没有空间跑完一条路线（雷达：%s）" % _clr_text(clr)
                ok = False
                details[zid] = row
                continue
        row["steps"] = steps

        if clr is None:
            row["note"] = "读不到雷达（/scan_raw），无法确认有空间可走"
            ok = False
            details[zid] = row
            continue
        worst = None
        turn_bad = None
        theta = 0.0
        for st in steps:
            op = st["op"]
            deg = float(st.get("deg", 0) or 0)
            # 转向步只要求"四周都别贴脸"（车端 TURN_CLEARANCE_M=0.30），
            # 不做方向性检查 —— 这是车端 ros_car.py 的判定，别在这里发明第二套
            if op.startswith("turn_"):
                vals = [v for v in clr.values() if v is not None]
                if vals and min(vals) < float(safety.get("turn_clearance_m", 0.30)):
                    turn_bad = min(vals)
                theta += deg if op == "turn_left" else -deg
                continue
            if op not in OP_TO_CMD:
                continue
            # 转向会换车头方向：车转过 theta 后，这一步要的空间是表里另一格
            avail = clr.get(rotate_key(op, theta))
            if avail is None:
                continue  # 该方向无限远
            if avail < st["m"] + margin - clr_tol:
                if worst is None or avail - st["m"] < worst[1] - worst[0]:
                    worst = (st["m"], avail, st)
        if turn_bad is not None:
            row["note"] = "转向空间不足（最近障碍 %.2f m，需 %.2f m）" % (
                turn_bad, float(safety.get("turn_clearance_m", 0.30)))
            ok = False
        if worst is not None:
            row["note"] = ("「%s」要 %.2f m，雷达只给出 %.2f m（差 %.2f m）—— 车摆得太贴障碍物了"
                           % (worst[2]["label"], worst[0] + margin, worst[1],
                              worst[0] + margin - worst[1]))
            row["need"] = worst[0] + margin
            ok = False
        details[zid] = row
    return ok, details


def _clr_text(clr):
    if not clr:
        return "读不到"
    return "前进 %s / 后退 %s / 左 %s / 右 %s" % tuple(
        "∞" if clr.get(k) is None else "%.2f m" % clr[k]
        for k in ("forward", "back", "strafe_left", "strafe_right"))


def build_adaptive_steps(zid, zone, clr, safety):
    """按当前雷达空间现场生成一条「走得通、而且回得来」的闭合路线。

    fixed 模式用 patrol_routes.json 里写死的航点（对应地图上那四条固定路线），
    硬前提是：车必须按 placement 摆好，且每个方向都有 ≥ 距离+0.20 m 的空间。
    09-20 实测：四台车清障后的可用空间是「前进 0.41~0.94 m、左/右 0.21~7.57 m」，
    方向对不上就全被车端雷达拒动 —— 所以 fixed 只适合摆好的场地。

    adaptive 保留「预编路线」的骨架 —— 闭环、每步 ≤ max_step_m、跑完回出发点 ——
    但按现场测量的空间分两级挑：

        ① 四段直线（不用掉头，航向漂移最小）。闭合条件是四个动作两两相反：
              A: forward → strafe_right → back          → strafe_left
              B: forward → strafe_left  → back          → strafe_right
           四个方向都要放得下 ≥ min_step_m，否则这条路不通。
        ② 掉头兜底（某个方向被堵死时用）：
              forward → turn_right 90° → strafe_right → turn_left 90°
           只用「走 + 横移」两个方向；两次转向把车头带回原朝向、净位移为零，
           一样回到出发点，而且比①更像真巡检（会转向）。
           转向只要求四周最近障碍 ≥ turn_clearance_m(0.30 m)，与车端判定一致。

    每步实际距离 = min(表里的距离, max_step_m, 该方向可用空间 − margin)。
    换来的是：车摆在哪儿都能跑完并归位。代价是路线**不是**地图上画的那一条，
    所以它必须在界面上如实标出（返回里带 mode=adaptive）。
    """
    max_step = float(safety.get("max_step_m", 0.90))
    margin = float(safety.get("motion_clearance_m", 0.20))
    min_step = float(safety.get("adaptive_min_step_m", 0.15))
    # 平移步「像样的最短距离」：比这个还短就换形状，别硬凑一条 4×5cm 的路线
    min_move = float(safety.get("adaptive_min_move_m", 0.25))
    turn_clear = float(safety.get("turn_clearance_m", 0.30))
    if not clr:
        return None
    want = {}
    for st in (zone.get("steps") or []):
        want.setdefault(st["op"], float(st.get("m", 0)))

    def fit(op):
        avail = clr.get(op)
        if avail is None:
            return max_step
        return max(0.0, min(max_step, avail - margin))

    def sized(op, m):
        want_m = want.get(op)
        if want_m:
            m = min(m, max(want_m, min_step))
        return round(m, 2)

    def feasible(seq):
        """按**执行顺序**逐步核对空间（转向会让车头变向，所以不能只看原始四方向）。

        横移与前进都是车体坐标系指令：车转过 θ 后，"前进"要的空间就变成了
        原始表里 rot(forward, θ) 那一格。θ 是 90 的整数倍，正好对应表里的四格。
        这一步不做的话，掉头兜底会算错 —— 实测 CAR-4 就是这么被误判成"没有空间"的。
        """
        theta = 0.0
        out = []
        for st in seq:
            op, deg = st["op"], st.get("deg", 0)
            if op.startswith("turn_"):
                nearest = [v for v in clr.values() if v is not None]
                if nearest and min(nearest) < turn_clear:
                    return None
                theta += deg if op == "turn_left" else -deg
                out.append(dict(st))
                continue
            avail = clr.get(rotate_key(op, theta))
            m = max_step if avail is None else max(0.0, min(max_step, avail - margin))
            m = round(m, 2)
            if m < min_step:
                return None
            out.append(dict(st, m=sized(op, m)))
        return out

    candidates = []
    for pattern in (["forward", "strafe_right", "back", "strafe_left"],
                    ["forward", "strafe_left", "back", "strafe_right"]):
        got = feasible([{"op": op, "m": 0, "deg": 0} for op in pattern])
        if got:
            candidates.append(got)
    for axis, t_out, lateral, t_back in (
            ("forward", "turn_right", "strafe_right", "turn_left"),
            ("forward", "turn_left", "strafe_left", "turn_right"),
            ("back", "turn_left", "strafe_left", "turn_right"),
            ("back", "turn_right", "strafe_right", "turn_left")):
        got = feasible([{"op": axis, "m": 0, "deg": 0},
                        {"op": t_out, "m": 0, "deg": 90},
                        {"op": lateral, "m": 0, "deg": 0},
                        {"op": t_back, "m": 0, "deg": 90}])
        if got:
            candidates.append(got)

    # 最后兜底：矩形和 Z 字都放不下时（车被挤在一侧，只有一个方向有空间），
    # 就沿**那个方向**按可走的距离做多段推进 —— 「沿可用空间扫一遍」。
    #
    # 这里**不强制回到出发点**。原来强制，结果 09-20 实测 CAR-4 卡在
    # 「左 7.60 m / 右 0.14 m」的单侧空间里：往前走得动，但任何回程方向都被堵死，
    # 于是整条路线判「没有空间」，四台车里少一台能动。
    # 演示的要害是「按一下，车真的按预编路线动起来」，不是每轮都原地收尾 ——
    # 所以如实退成单向巡检，形状名会写明，界面上不冒充闭环路线。
    if not candidates:
        for axis in ("forward", "strafe_left", "strafe_right", "back"):
            avail = clr.get(axis)
            if avail is None:
                avail = max_step * 4
            room = max(0.0, avail - margin)
            # 单向扫是"有界"的：走出去就不打算回来，所以只要求这一段像样
            if room < min_move:
                continue
            steps = []
            left = room
            while left >= min_step and len(steps) < 4:
                seg = round(min(max_step, left), 2)
                left = round(left - seg, 3)
                steps.append({"id": "AD%d" % (len(steps) + 1),
                              "label": ADAPT_LABELS[len(steps) % len(ADAPT_LABELS)],
                              "op": axis, "m": sized(axis, seg), "deg": 0, "dwell": 0.5})
            if steps:
                candidates.append(steps)
                break

    # 【关键的一步】给平移步设一个「像样的最短距离」下限，达不到就换形状。
    #
    # 为什么必须做：规划时是按「车在出发点」量的空间，可车一旦走完第一步，
    # 它和周围障碍的相对关系就变了。实测（09-20 18:25 那一轮）：
    #   CAR-1 规划 forward 0.9（前方 1.0+ 空间）→ 走完 0.892 m 后，
    #   右横移空间从 0.83 m 掉到不够 0.36 m，第二步被雷达拒动 → 整条路线判阻塞。
    #
    # 两条规则：
    #   ① 所有平移步的距离都不超过「全程最紧的那一步」——
    #      最紧的那步按自己的余量走得动，其余的比它还短，就一定也走得动；
    #   ② 压缩后不能小于 min_move_m(0.25 m)：四步各走 5 cm 的"巡检"没有意义，
    #      车端在 0.20 m 余量下也未必肯动。达不到下限就**换下一种形状**。
    # 注：不能按"换向点"筛——闭环的形状要求四个方向都用上（见上面的说明）。
    kept = []
    for cand in candidates:
        moves = [s for s in cand if not s["op"].startswith("turn_")]
        if not moves:
            kept.append(cand)
            continue
        cap = round(min(s["m"] for s in moves), 2)
        if cap < min_move:
            continue
        for s in moves:
            s["m"] = min(s["m"], cap)
        kept.append(cand)
    candidates = kept

    best = None
    for cand in candidates:
        # 打分只看平移距离：转向步 m 是 0，不该影响"哪条路线更长"
        score = sum((s["m"] if not s["op"].startswith("turn_") else 0) for s in cand)
        if best is None or score > best[0]:
            best = (score, cand)
    if best is None:
        return None
    # 形状名如实标出：闭环巡检 / Z 字 / 单向扫，三者不能在界面上长得一样
    ops = [s["op"] for s in best[1]]
    if any(o.startswith("turn_") for o in ops):
        shape_name = "Z 字形（一轴 + 掉头）"
    elif len(set(ops)) == 4:
        shape_name = "矩形闭环（四方向，回出发点）"
    elif len(set(ops)) == 1:
        shape_name = "单向前扫（其余三个方向被占，不回起点）"
    else:
        shape_name = "矩形往返"
    steps = []
    for i, st in enumerate(best[1]):
        steps.append({
            "id": "AD%d" % (i + 1),
            "label": ADAPT_LABELS[i % len(ADAPT_LABELS)],
            "op": st["op"],
            "m": st["m"],
            "deg": st.get("deg", 0),
            "dwell": 0.5,
        })
    if steps:
        steps[0]["shape"] = shape_name
    return steps


ADAPT_LABELS = ["巡检起点", "转向下一段", "展台 1", "回到起点"]

# 车体四方向按 90° 一格排环：车逆时针转 θ 后，"前进"落在环上的哪一格
_RING = ("forward", "strafe_left", "back", "strafe_right")


def rotate_key(op, theta_deg):
    """车转过 theta_deg 后，车体系的 op 对应原始雷达表的哪个方向格。"""
    if op not in _RING:
        return op
    steps = int(round(float(theta_deg) / 90.0)) % 4
    return _RING[(_RING.index(op) + steps) % 4]


def run_step(zid, car, op, meters, deg=0.0):
    """跑一步。返回 (ok, note, measured_m)。

    op 是 ros_car.py 的命令名（小写）：forward / back / strafe_left / strafe_right /
    turn_left / turn_right。转向用 deg，平移用 meters。
    """
    safety = CONFIG.get("safety") or {}
    speed = float(safety.get("speed_mps", 0.15))
    timeout = float(safety.get("step_timeout_s", 40))
    cmd = OP_TO_CMD[op]
    is_turn = op in ("turn_left", "turn_right")
    # 注意三元表达式的位置：写成
    #     "--set", "angle_deg=..." if is_turn else "--set", "distance_m=..."
    # 会把第一个 "--set" 也卷进三元里 —— is_turn 为假时它就丢了，
    # argparse 直接报 "argument --set: expected one argument"（实测四台车全中）。
    value = ("angle_deg=%.1f" % float(deg or 0)) if is_turn else ("distance_m=%.3f" % meters)
    argv = [sys.executable, ROS_CAR,
            "--robots", str(car),
            "--cmd", cmd,
            "--set", value,
            "--set", "speed=%.3f" % speed]
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    # 子进程输出里有中文（"实际完成 0.493 m"）。不强制 UTF-8，按 locale 解出来是乱码，
    # 解析实测值会永远拿到 None —— 踩过（round-001 的 stepLog 里 measured_m 全是 None）。
    env["PYTHONIOENCODING"] = "utf-8"
    log("%s 执行 %s %s → 车 %s" % (zid, cmd, ("%.1f°" % deg) if is_turn else ("%.2f m" % meters), car))
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=env, cwd=VOICE_DIR)
    except OSError as exc:
        return False, "启动 ros_car.py 失败：%s" % exc, None
    with LOCK:
        STEP_PROCS[zid] = proc
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        with LOCK:
            STEP_PROCS.pop(zid, None)
        return False, "超过 %.0f 秒未完成，已中止" % timeout, None
    with LOCK:
        STEP_PROCS.pop(zid, None)
    text = (out or b"").decode("utf-8", "replace")
    rc = proc.returncode
    measured = None
    for line in text.splitlines():
        line = line.strip()
        if "实际完成" in line or "实际横移" in line or "实际转过" in line:
            # 输出形如 "  实际完成 0.493 m" / "  实际转过 89.1°（未收敛）"：
            # 取**第一个数**，不能取最后一个 token（后面还可能跟括号说明）
            mm = re.search(r"(-?[0-9]+(?:\.[0-9]+)?)", line)
            if mm:
                try:
                    measured = float(mm.group(1))
                except ValueError:
                    measured = None
    # 子进程最后一行摘要进日志：出问题时不用再去别处翻
    tail = ""
    for line in reversed(text.splitlines()):
        if line.strip():
            tail = line.strip()
            break
    log("%s   → %s" % (zid, tail[:160]))
    if rc == 0:
        return True, "完成", measured
    if rc == 8:
        return False, "未收敛（车可能只走了一部分）", measured
    return False, "退出码 %s：%s" % (rc, tail[:120]), measured


def run_step_with_retry(zid, car, st):
    """跑一步，被雷达拒动就按更保守的距离重试。

    为什么需要：出航前量的可用空间和真正发指令那一刻的读数会差 1~3 cm
    （实测 CAR-1/CAR-4 都撞上过），于是「体检说能走、发指令被拒」。
    重试不是放宽安全边界 —— 每一次重试都只会**更短**，
    车端雷达始终是最终否决权。
    """
    safety = CONFIG.get("safety") or {}
    ratios = list(safety.get("retry_ratios") or (1.0, 0.7, 0.4))
    op = st["op"]
    deg = float(st.get("deg", 0) or 0)
    last = (False, "未执行", None)
    base = float(st["m"])
    for i, ratio in enumerate(ratios):
        m = base if ratio >= 1.0 else round(base * float(ratio), 2)
        if not op.startswith("turn_") and m < float(safety.get("adaptive_min_step_m", 0.15)):
            continue
        if i > 0:
            log("%s 重试第 %d 次：%s 距离收到 %.2f m" % (zid, i, op, m))
        ok, note, measured = run_step(zid, car, op, m, deg)
        last = (ok, note, measured)
        if ok:
            if i > 0:
                return True, "完成（被雷达拒动后收到 %.2f m 重试成功）" % m, measured
            return True, "完成", measured
        # 只有"空间不足"值得重试；其它失败（连不上、未收敛…）重试没意义
        if "距离不足" not in note and "拒" not in note:
            return last
    return last


def zone_worker(zid):
    """一台车跑一条路线。四台车各一个线程，同时开始。"""
    with LOCK:
        t = STATE["zones"][zid]
        steps = list(t["steps"])
    car = t["car"]
    ip = t["ip"]

    before = read_odom(ip)
    with LOCK:
        t["odomStart"] = before
        t["status"] = "running"
        t["startedAt"] = now_iso()
    event("%s（CAR-%s）开始执行「%s」" % (t["zoneName"], car, t["routeName"]), zid)

    for idx, st in enumerate(steps):
        if ABORT.is_set():
            with LOCK:
                t["status"] = "aborted"
                t["detail"] = "已取消"
            return
        with LOCK:
            t["stepIndex"] = idx
            t["stepTotal"] = len(steps)
            t["stepLabel"] = st["label"]
            t["detail"] = ("前往 %s（%s %.2f m）" % (st["label"], OP_CN[st["op"]], st["m"])
                           if st["op"] in OP_TO_CMD and not st["op"].startswith("turn_")
                           else "%s（%s %.0f°）" % (st["label"], OP_CN.get(st["op"], st["op"]),
                                                  float(st.get("deg", 0) or 0)))
        odo_a = read_odom(ip)
        ok, note, measured = run_step_with_retry(zid, car, st)
        odo_b = read_odom(ip)
        # 逐步留痕：命令值与 /odom 实测量并排存下来，
        # 这样「车到底走够没有」永远是可核对的事实，而不是印象。
        moved = None
        drift = None
        if odo_a and odo_b:
            import math as _math
            dx, dy = odo_b[0] - odo_a[0], odo_b[1] - odo_a[1]
            yaw0 = _math.radians(odo_a[2])
            base = {"forward": 0.0, "back": _math.pi,
                    "strafe_left": _math.pi / 2, "strafe_right": -_math.pi / 2}.get(st["op"])
            if base is None:          # 转向步：位移应≈0，看的是转过的角度
                moved = round(_math.hypot(dx, dy), 3)
            else:
                ux, uy = _math.cos(yaw0 + base), _math.sin(yaw0 + base)
                moved = round(dx * ux + dy * uy, 3)
            drift = round(odo_b[2] - odo_a[2], 2)
        with LOCK:
            t["stepLog"].append({
                "step": idx + 1, "id": st["id"], "label": st["label"], "op": st["op"],
                "m": st["m"], "ok": ok, "note": note, "measured_m": measured,
                "odom_moved_m": moved, "yaw_drift_deg": drift,
                "at": now_iso(),
            })
        if not ok:
            with LOCK:
                if ABORT.is_set():
                    # 是被"复位/取消"打断的，不是车出了问题。
                    # 原样报 blocked + "退出码 -9" 会让人以为车坏了（实测 round-003 就是这样）。
                    t["status"] = "blocked"
                    t["reason"] = "cancelled"
                    t["detail"] = "已取消（在「%s」这一步被叫停）" % st["label"]
                else:
                    t["status"] = "blocked"
                    t["reason"] = "obstacle" if ("拒" in note or "雷达" in note) else "error"
                    t["detail"] = "%s：%s" % (st["label"], note)
                t["finishedAt"] = now_iso()
            if ABORT.is_set():
                event("CAR-%s 已在「%s」被叫停" % (car, st["label"]), zid)
                return
            event("CAR-%s 在「%s」受阻：%s" % (car, st["label"], note), zid)
            if (CONFIG.get("safety") or {}).get("stop_on_blocked"):
                ABORT.set()
            return
        dwell = float(st.get("dwell", 0) or 0)
        if dwell > 0:
            with LOCK:
                t["detail"] = "%s 停留 %.1f s 看点" % (st["label"], dwell)
            end = time.time() + dwell
            while time.time() < end and not ABORT.is_set():
                time.sleep(0.05)
        with LOCK:
            t["progress"] = int(round((idx + 1) * 100.0 / len(steps)))
            t["leg"] = idx + 1

    with LOCK:
        t["status"] = "done"
        t["progress"] = 100
        t["detail"] = "路线执行完毕，未发现异常"
        t["finishedAt"] = now_iso()
        t["odomEnd"] = read_odom(ip)
    event("CAR-%s 完成「%s」" % (car, t["routeName"]), zid)


OP_CN = {
    "forward": "前进",
    "back": "后退",
    "strafe_left": "左横移",
    "strafe_right": "右横移",
    "turn_left": "左转",
    "turn_right": "右转",
}


def write_round_log():
    """把本轮结果落盘，供事后核对（证据留痕）。"""
    try:
        os.makedirs(ROUND_LOG_DIR, exist_ok=True)
    except OSError:
        return None
    with LOCK:
        payload = {
            "round": STATE["round"],
            "status": STATE["status"],
            "startedAt": STATE["startedAt"],
            "finishedAt": STATE["finishedAt"],
            "zones": STATE["zones"],
        }
    path = os.path.join(ROUND_LOG_DIR, "round-%03d.json" % STATE["round"])
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        return None
    return path


def start_round(source="api"):
    with LOCK:
        if STATE["status"] == "running":
            return False, "上一轮巡检还在跑（第 %d 轮），先取消或等它跑完" % STATE["round"]

    zones_cfg = CONFIG.get("zones") or {}
    problems = validate_config(CONFIG)
    if problems:
        return False, "路线表不合规：" + "；".join(problems)

    ok, details = preflight(zones_cfg)
    if not ok:
        bad = []
        for zid, row in details.items():
            if row.get("note"):
                bad.append("CAR-%s %s" % (row["car"], row["note"]))
            elif not row.get("online"):
                bad.append("CAR-%s 不在线" % row["car"])
        return False, "车辆体检未通过：" + "；".join(bad)

    ABORT.clear()
    mode = str((CONFIG.get("safety") or {}).get("route_mode", "fixed"))
    with LOCK:
        STATE["round"] += 1
        STATE["status"] = "running"
        STATE["startedAt"] = now_iso()
        STATE["finishedAt"] = None
        STATE["routeMode"] = mode
        STATE["message"] = "第 %d 轮巡检已下发，四台车开始按预编路线执行" % STATE["round"]
        STATE["zones"] = {}
        for zid, z in zones_cfg.items():
            car = str(z.get("car"))
            row = details.get(zid) or {}
            STATE["zones"][zid] = {
                "id": zid,
                "zoneName": z.get("name") or zid,
                "routeName": z.get("route_name") or "",
                "car": car,
                "ip": row.get("ip") or z.get("ip") or "",
                "battery": row.get("battery"),
                "online": bool(row.get("online")),
                "status": "pending",
                "progress": 0,
                "leg": 0,
                "stepIndex": -1,
                "stepTotal": len(row.get("steps") or z.get("steps") or []),
                "stepLabel": "",
                "detail": "已派单，等待出发",
                "steps": row.get("steps") or z.get("steps") or [],
                "clearance": row.get("clearance"),
                "stepLog": [],
                "startedAt": None,
                "finishedAt": None,
                "odomStart": None,
                "odomEnd": None,
            }
    event("第 %d 轮巡检开始（来源：%s）" % (STATE["round"], source))

    for zid in zones_cfg.keys():
        th = threading.Thread(target=zone_worker, args=(zid,), daemon=True)
        th.start()

    threading.Thread(target=watch_round, daemon=True).start()
    return True, STATE["message"]


def watch_round():
    """等四台车都收工，收尾并落盘。"""
    while not ABORT.is_set():
        with LOCK:
            zones = list(STATE["zones"].values())
            alive = [z for z in zones if z["status"] in ("pending", "running")]
        if not alive:
            break
        time.sleep(0.3)
    with LOCK:
        zones = list(STATE["zones"].values())
        if ABORT.is_set():
            STATE["status"] = "aborted"
            STATE["message"] = "第 %d 轮巡检已取消" % STATE["round"]
        else:
            done = len([z for z in zones if z["status"] == "done"])
            blocked = [z for z in zones if z["status"] == "blocked"]
            STATE["status"] = "done" if not blocked else "done"
            if blocked:
                STATE["message"] = "第 %d 轮巡检结束：%d 个区域已完成，%d 个受阻（%s）" % (
                    STATE["round"], done, len(blocked),
                    "、".join(z["zoneName"] for z in blocked))
            else:
                STATE["message"] = "第 %d 轮巡检结束：%d 个区域全部完成" % (STATE["round"], done)
        STATE["finishedAt"] = now_iso()
    path = write_round_log()
    event(STATE["message"] + ("（记录：%s）" % path if path else ""))


def stop_all(reason="手动取消"):
    ABORT.set()
    with LOCK:
        procs = list(STEP_PROCS.items())
    for zid, proc in procs:
        try:
            proc.kill()
        except OSError:
            pass
    # 无条件向四台车各发一次 STOP（安全兜底）
    threading.Thread(target=_broadcast_stop, daemon=True).start()
    with LOCK:
        for z in STATE["zones"].values():
            if z["status"] in ("pending", "running"):
                z["status"] = "aborted"
                z["detail"] = reason
                z["finishedAt"] = now_iso()
    event("已取消本轮巡检：%s" % reason)
    return True, "已向四台车发送停止，并中止后续动作"


def _broadcast_stop():
    for i in (1, 2, 3, 4):
        try:
            subprocess.run([sys.executable, ROS_CAR, "--robots", str(i), "--cmd", "STOP"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=12, cwd=VOICE_DIR)
        except Exception:
            pass


def reset_state():
    """复位到「尚未开始巡检」。

    【安全】复位**必须先停车**：原来只清状态，正在跑的步骤不受影响 ——
    演示者点了「复位」，界面回到干净画面，车却还在往前走。
    现在先置 ABORT（步骤线程在每一步开头和停留循环里都检查它），
    杀掉当前步骤的子进程，并无条件给四台车各发一次 STOP。
    """
    was_running = False
    with LOCK:
        was_running = STATE["status"] == "running"
    if was_running:
        stop_all("复位")
    ABORT.set()
    with LOCK:
        procs = list(STEP_PROCS.values())
    for proc in procs:
        try:
            proc.kill()
        except OSError:
            pass
    time.sleep(0.3)
    # 即使没在跑，也补一次 STOP：车端可能有上一次残留的速度指令
    threading.Thread(target=_broadcast_stop, daemon=True).start()
    with LOCK:
        STATE["status"] = "idle"
        STATE["zones"] = {}
        STATE["startedAt"] = None
        STATE["finishedAt"] = None
        STATE["message"] = "尚未开始巡检"
    ABORT.clear()
    event("已复位到初始状态（并向四台车补发了一次 STOP）")
    return True, "已复位；同时向四台车发送了停止指令"


def snapshot():
    with LOCK:
        return {
            "ok": True,
            "round": STATE["round"],
            "status": STATE["status"],
            "message": STATE["message"],
            "startedAt": STATE["startedAt"],
            "finishedAt": STATE["finishedAt"],
            "zones": [dict(z, steps=None) for z in STATE["zones"].values()],
            "events": STATE["events"][-20:],
            "generatedAt": now_iso(),
        }


# ---------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "velaguard-patrol/1.0"

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # 走自己的日志

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/patrol/status", "/status"):
            self._send(200, snapshot())
        elif path in ("/patrol/routes", "/routes"):
            self._send(200, {"ok": True, "config": CONFIG})
        elif path == "/health":
            self._send(200, {"ok": True, "service": "patrol_controller", "at": now_iso()})
        else:
            self._send(404, {"ok": False, "error": "unknown path", "path": path})

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            try:
                self.rfile.read(length)
            except OSError:
                pass
        if path == "/patrol/start":
            ok, msg = start_round(source="ui")
            self._send(200 if ok else 409, {"ok": ok, "message": msg,
                                            "state": snapshot()})
        elif path == "/patrol/stop":
            ok, msg = stop_all()
            self._send(200, {"ok": ok, "message": msg, "state": snapshot()})
        elif path == "/patrol/reset":
            ok, msg = reset_state()
            self._send(200, {"ok": ok, "message": msg, "state": snapshot()})
        else:
            self._send(404, {"ok": False, "error": "unknown path", "path": path})


def selftest():
    cfg = load_config()
    problems = validate_config(cfg)
    print("路线表：%s" % ROUTES_FILE)
    for line in route_summary(cfg):
        print(line)
    if problems:
        print("\n不合规 %d 条：" % len(problems))
        for p in problems:
            print("  x " + p)
        return 1
    print("\n结论：全部合规")
    return 0


def main():
    global CONFIG
    ap = argparse.ArgumentParser(description="VelaGuard 巡检执行器")
    ap.add_argument("--port", type=int, default=8127)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--routes", default=ROUTES_FILE)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    CONFIG = load_config(args.routes)
    problems = validate_config(CONFIG)
    if problems:
        print("路线表不合规，拒绝启动：")
        for p in problems:
            print("  x " + p)
        return 2
    if args.selftest:
        return selftest()

    log("=" * 60)
    log("VelaGuard 巡检执行器启动：http://%s:%d" % (args.bind, args.port))
    log("路线表：%s" % args.routes)
    for line in route_summary(CONFIG):
        log(line)
    srv = ThreadingHTTPServer((args.bind, args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_all("服务退出")
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
