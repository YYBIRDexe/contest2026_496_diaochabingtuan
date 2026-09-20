"""Run one synchronized closed lap for four omnidirectional robots."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "payload" / "planner"))
import run_autonomous_formation as control  # noqa: E402
from formation_lap import build_lap_plan  # noqa: E402
from formation_planner import FormationPlanner, OccupancyGrid, Pose, ROBOT_IDS  # noqa: E402
from lap_session import SynchronizedLapSession  # noqa: E402
from reconfiguration_session import Telemetry  # noqa: E402
from scan_localizer import map_metadata  # noqa: E402


def _readings(endpoints, now):
    readings = {}
    fleet = {}
    snapshots = {}
    for robot, endpoint in endpoints.items():
        data, received = endpoint.snapshot()
        snapshots[robot] = data
        connected = data is not None and now - received <= 0.7 and data.get("agent") is not None and data.get("bridge") is not None
        pose_data = data.get("pose") if connected else None
        valid = bool(pose_data and pose_data.get("valid") and data.get("pose_age_s", 1e9) + now - received <= 0.7)
        pose = Pose(float(pose_data["x"]), float(pose_data["y"]), float(pose_data["yaw"])) if valid else None
        agent = data.get("agent") if connected else None
        path_clear = agent is None or agent.get("reason") not in ("lidar_path_blocked", "outside_arena")
        readings[robot] = Telemetry(
            pose,
            received,
            connected,
            float(pose_data["xy_variance_m2"]) if valid else 1.0,
            float(pose_data["yaw_variance_rad2"]) if valid else 1.0,
            bool(connected and data.get("lidar_fresh")),
            path_clear,
        )
        fleet[robot] = {
            "x": pose.x if pose else 0.0,
            "y": pose.y if pose else 0.0,
            "yaw": pose.yaw if pose else 0.0,
            "valid": valid,
        }
    return readings, fleet, snapshots


def _trajectory_commands(lap_plan, mission_id: str, speed_mps: float):
    return {
        robot: {
            "stop_all": False,
            "robot_id": robot,
            "trajectory": [list(point) for point in lap_plan.robot_routes[robot]],
            "trajectory_id": mission_id,
            "speed_mps": speed_mps,
            "mission_id": mission_id,
        }
        for robot in ROBOT_IDS
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formation", choices=("square", "line", "circle", "diamond", "triangle"), default="triangle")
    parser.add_argument("--spacing", type=float, default=0.5)
    parser.add_argument("--laps", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--bounds", type=float, nargs=4, default=(-2.6, 2.6, -1.8, 2.6), metavar=("MIN_X", "MAX_X", "MIN_Y", "MAX_Y"))
    args = parser.parse_args()
    map_path = ROOT / "payload" / "evidence" / "current_map" / "classroom.pgm"
    map_sha = hashlib.sha256(map_path.read_bytes()).hexdigest()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda robot: control.check_car(robot, map_sha), ROBOT_IDS))
    if args.check_only:
        print("LAP_PREFLIGHT_OK", flush=True)
        return
    with ThreadPoolExecutor(max_workers=4) as pool:
        localized = list(pool.map(control.localize_car, ROBOT_IDS))
    current = {
        robot: Pose(float(item["x"]), float(item["y"]), float(item["yaw"]))
        for robot, item in zip(ROBOT_IDS, localized)
    }
    center = (
        sum(pose.x for pose in current.values()) / len(ROBOT_IDS),
        sum(pose.y for pose in current.values()) / len(ROBOT_IDS),
    )
    resolution, origin = map_metadata(map_path)
    planner = FormationPlanner(arena=(-3.3, 3.3, -3.3, 3.3), map_grid=OccupancyGrid(map_path, resolution, origin))
    lap_plan = build_lap_plan(
        planner,
        tuple(args.bounds),
        args.formation,
        args.spacing,
        args.laps,
        start_center=center,
        current={robot: (pose.x, pose.y) for robot, pose in current.items()},
    )
    endpoints = {robot: control.Endpoint(robot) for robot in ROBOT_IDS}
    keeper = control.LeaseKeeper()
    for endpoint in endpoints.values():
        endpoint.start()
    keeper.start()
    deadline = time.monotonic() + args.timeout
    last_route_send = -math.inf
    last_fleet_send = -math.inf
    route_heartbeat_period = 0.8
    fleet_state_period = 0.2
    try:
        session = SynchronizedLapSession(planner, lap_plan)
        route_commands = _trajectory_commands(lap_plan, keeper.identifier, session.max_speed_mps)
        while time.monotonic() < deadline:
            now = time.monotonic()
            readings, fleet, snapshots = _readings(endpoints, now)
            decision = session.tick(now, readings)
            motion_requested = decision.state == "RUNNING" and bool(decision.velocities)
            keeper.armed.set() if motion_requested else keeper.armed.clear()
            if keeper.error:
                raise RuntimeError(f"lease renewal failed: {keeper.error}")
            snapshots = {robot: snapshots[robot] or {} for robot in ROBOT_IDS}
            armed = all(bool((snapshots[robot].get("bridge") or {}).get("armed")) for robot in ROBOT_IDS)
            commands = {robot: {"stop_all": True} for robot in ROBOT_IDS}
            route_command_due = motion_requested and armed and now - last_route_send >= route_heartbeat_period
            if route_command_due:
                commands = route_commands
                last_route_send = now
            for robot, endpoint in endpoints.items():
                if now - last_fleet_send >= fleet_state_period:
                    endpoint.send("fleet", {"poses": fleet})
                if route_command_due or not motion_requested:
                    endpoint.send("command", commands[robot])
            if now - last_fleet_send >= fleet_state_period:
                last_fleet_send = now
            print(f"{decision.state}: {decision.reason}", flush=True)
            if decision.state == "COMPLETE":
                return
            if decision.state == "PAUSED":
                raise RuntimeError(decision.reason)
            time.sleep(0.1)
        raise RuntimeError("lap mission timeout; all cars commanded to stop")
    finally:
        keeper.armed.clear()
        for _ in range(5):
            for endpoint in endpoints.values():
                endpoint.send("command", {"stop_all": True})
            time.sleep(0.1)
        keeper.stop()
        for endpoint in endpoints.values():
            endpoint.stop()


if __name__ == "__main__":
    main()
