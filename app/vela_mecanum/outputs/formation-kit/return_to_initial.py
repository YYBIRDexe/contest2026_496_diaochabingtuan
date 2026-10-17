from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "payload" / "planner"))

import run_autonomous_formation as control
from formation_planner import FormationPlanner as BasePlanner
from formation_planner import Plan, PlanningError, Request, ROBOT_IDS
from scan_localizer import map_metadata
from formation_planner import OccupancyGrid


TARGETS = {
    "robot1": (-2.50, -0.95),
    "robot3": (-2.50, -0.50),
    "robot4": (-2.50, -0.05),
    "robot2": (-2.50, 0.40),
}
SLOTS = {"robot1": 0, "robot3": 1, "robot4": 2, "robot2": 3}


class InitialPosePlanner(BasePlanner):
    def plan(self, current, request: Request) -> Plan:
        if self.map is not None:
            self.map.clear_robot_footprints(current.values())
        self._validate(current, request)
        targets = {
            robot: ((pose.x, pose.y) if math.hypot(pose.x - TARGETS[robot][0], pose.y - TARGETS[robot][1]) < 0.02 else TARGETS[robot])
            for robot, pose in current.items()
        }
        for robot, point in targets.items():
            if not self._point_free(point):
                raise PlanningError(f"initial target is outside the safe map: {robot}")
        minimum = min(
            math.hypot(targets[first][0] - targets[second][0], targets[first][1] - targets[second][1])
            for index, first in enumerate(ROBOT_IDS) for second in ROBOT_IDS[index + 1:]
        )
        if minimum < self.separation:
            raise PlanningError("initial targets violate the separation limit")
        positions = {robot: (pose.x, pose.y) for robot, pose in current.items()}
        recovery = self._recover_close_pairs(positions)
        routed = self._route_to_targets(positions, targets)
        if routed is None:
            raise PlanningError("no collision free route to the initial positions")
        route, _ = routed
        plan = Plan(request, targets, SLOTS, (*recovery, *route), minimum)
        self.verify(current, plan)
        print(
            "INITIAL_ROUTE "
            + " ".join(f"{step.robot_id}:{len(step.waypoints)}" for step in plan.steps),
            flush=True,
        )
        return plan


class SingleRobotCorrectionPlanner(BasePlanner):
    moving_robot = "robot1"

    def plan(self, current, request: Request) -> Plan:
        if self.map is not None:
            self.map.clear_robot_footprints(current.values())
        self._validate(current, request)
        targets = {
            robot: (TARGETS[robot] if robot == self.moving_robot else (pose.x, pose.y))
            for robot, pose in current.items()
        }
        minimum = min(
            math.hypot(targets[first][0] - targets[second][0], targets[first][1] - targets[second][1])
            for index, first in enumerate(ROBOT_IDS) for second in ROBOT_IDS[index + 1:]
        )
        if minimum < self.separation:
            raise PlanningError(f"{self.moving_robot} correction would violate the separation limit")
        positions = {robot: (pose.x, pose.y) for robot, pose in current.items()}
        routed = self._route_to_targets(positions, targets)
        if routed is None:
            raise PlanningError(f"no collision free route for {self.moving_robot} correction")
        route, _ = routed
        if any(step.robot_id != self.moving_robot for step in route):
            raise PlanningError(f"{self.moving_robot} correction produced an unexpected moving robot")
        plan = Plan(request, targets, SLOTS, route, minimum)
        self.verify(current, plan)
        print(f"{self.moving_robot.upper()}_CORRECTION_ROUTE_CHECK_OK", flush=True)
        return plan


def plan_only() -> None:
    map_path = ROOT / "payload" / "evidence" / "current_map" / "classroom.pgm"
    map_sha = hashlib.sha256(map_path.read_bytes()).hexdigest()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda robot: control.check_car(robot, map_sha), ROBOT_IDS))
        localized = list(pool.map(control.localize_car, ROBOT_IDS))
    current = {
        robot: control.Pose(float(item["x"]), float(item["y"]), float(item["yaw"]))
        for robot, item in zip(ROBOT_IDS, localized)
    }
    resolution, origin = map_metadata(map_path)
    planner = InitialPosePlanner(
        arena=(-3.3, 3.3, -3.3, 3.3),
        map_grid=OccupancyGrid(map_path, resolution, origin),
    )
    plan = planner.plan(current, Request("line", 0.45, assignment="fixed"))
    planner.verify(current, plan)
    print("INITIAL_ROUTE_CHECK_OK", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--robot1-only", action="store_true")
    parser.add_argument("--robot4-only", action="store_true")
    args = parser.parse_args()
    if args.plan_only:
        plan_only()
        return
    if args.robot1_only or args.robot4_only:
        SingleRobotCorrectionPlanner.moving_robot = "robot1" if args.robot1_only else "robot4"
        control.FormationPlanner = SingleRobotCorrectionPlanner
    else:
        control.FormationPlanner = InitialPosePlanner
    sys.argv = [sys.argv[0], "line", "--spacing", "0.45", "--timeout", "240"]
    control.main()


if __name__ == "__main__":
    main()
