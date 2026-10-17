"""Deterministic digital twin using the live map, scans, planner and session."""

from pathlib import Path
from math import hypot

from formation_planner import FormationPlanner, OccupancyGrid, Pose, Request
from reconfiguration_session import ReconfigurationSession, Telemetry
from scan_localizer import ScanMatcher, map_metadata, parse_scan_echo


def run(data_dir: Path, formation: str = "square", spacing: float = 0.5) -> dict:
    pgm = data_dir / "classroom.pgm"
    matcher = ScanMatcher(pgm)
    positions = {}
    for index in range(1, 5):
        estimate = matcher.estimate(*parse_scan_echo(data_dir / f"robot{index}_scan_raw.txt"))
        positions[f"robot{index}"] = Pose(estimate.x, estimate.y, estimate.yaw)
    resolution, origin = map_metadata(pgm)
    planner = FormationPlanner(arena=(-3.3, 3.3, -3.3, 3.3), map_grid=OccupancyGrid(pgm, resolution, origin))
    session = ReconfigurationSession(planner, Request(formation, spacing))
    seconds = 0.0
    offline_stops = 0
    replan_count = 0
    previous_plan = None
    minimum_gap = float("inf")
    while seconds < 240:
        offline = 6.0 <= seconds < 8.5
        readings = {robot: Telemetry(pose, seconds, not (offline and robot == "robot4"))
                    for robot, pose in positions.items()}
        decision = session.tick(seconds, readings)
        if session.plan is not None and session.plan is not previous_plan:
            replan_count += 1
            previous_plan = session.plan
        if decision.state == "COMPLETE":
            break
        if decision.state in ("BLOCKED", "ABORTED"):
            raise RuntimeError(f"simulation stopped: {decision.state}: {decision.reason}")
        if offline:
            if not decision.stop_all:
                raise AssertionError("motion allowed while a car is offline")
            offline_stops += 1
        if not decision.stop_all:
            robot = decision.robot_id
            pose = positions[robot]
            target_x, target_y = decision.waypoint
            distance = hypot(target_x - pose.x, target_y - pose.y)
            travel = min(distance, min(0.12, 0.6 * distance) * 0.1)
            if distance > 0:
                positions[robot] = Pose(pose.x + travel * (target_x - pose.x) / distance,
                                        pose.y + travel * (target_y - pose.y) / distance, pose.yaw)
        values = list(positions.values())
        minimum_gap = min(minimum_gap, *(hypot(a.x - b.x, a.y - b.y)
                                           for i, a in enumerate(values) for b in values[i + 1:]))
        if minimum_gap < 0.30:
            raise AssertionError(f"cars too close: {minimum_gap:.3f}")
        seconds = round(seconds + 0.1, 3)
    if session.state != "COMPLETE":
        raise RuntimeError(f"simulation timed out: {session.state}: {session.reason}")
    return {"formation": formation, "spacing_m": spacing, "virtual_seconds": seconds, "replans": replan_count,
            "offline_stop_ticks": offline_stops, "minimum_gap_m": round(minimum_gap, 3),
            "final_positions": {robot: (round(pose.x, 3), round(pose.y, 3)) for robot, pose in positions.items()}}


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--formation", default="square", choices=("square", "line", "circle", "diamond"))
    parser.add_argument("--spacing", type=float, default=0.5)
    args = parser.parse_args()
    print(json.dumps(run(args.data_dir, args.formation, args.spacing), indent=2))
