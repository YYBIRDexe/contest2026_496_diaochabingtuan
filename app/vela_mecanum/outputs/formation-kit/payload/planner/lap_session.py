"""Synchronized velocity session for a reusable formation lap route."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite

from formation_lap import LapPlan, _synchronized_gap
from formation_planner import FormationPlanner, Pose, ROBOT_IDS
from reconfiguration_session import Telemetry


@dataclass(frozen=True)
class LapDecision:
    state: str
    stop_all: bool
    velocities: dict[str, tuple[float, float]]
    reason: str = ""


class SynchronizedLapSession:
    def __init__(
        self,
        planner: FormationPlanner,
        lap_plan: LapPlan,
        stable_reconnect_s: float = 2.0,
        telemetry_timeout_s: float = 0.7,
        max_speed_mps: float = 0.875,
    ):
        self.planner = planner
        self.lap_plan = lap_plan
        self.stable_reconnect_s = stable_reconnect_s
        self.telemetry_timeout_s = telemetry_timeout_s
        self.max_speed_mps = max_speed_mps
        self.state = "WAITING"
        self.reason = "awaiting four fresh robot states"
        self.ready_since: float | None = None
        self.routes: dict[str, tuple[tuple[float, float], ...]] | None = None
        self.route_indices = {robot: 1 for robot in ROBOT_IDS}

    def tick(self, now_s: float, readings: dict[str, Telemetry]) -> LapDecision:
        issue = self._telemetry_issue(now_s, readings)
        if issue:
            self.ready_since = None
            self.state = "PAUSED"
            self.reason = issue
            return LapDecision(self.state, True, {}, self.reason)
        if self.ready_since is None:
            self.ready_since = now_s
        if now_s - self.ready_since < self.stable_reconnect_s:
            return LapDecision("WAITING", True, {}, "waiting for stable localization")
        poses = {robot: readings[robot].pose for robot in ROBOT_IDS}
        assert all(pose is not None for pose in poses.values())
        if self.routes is None:
            self.routes = {
                robot: ((poses[robot].x, poses[robot].y), *self.lap_plan.robot_routes[robot])
                for robot in ROBOT_IDS
            }
            self.route_indices = {robot: 1 for robot in ROBOT_IDS}
        commands: dict[str, tuple[float, float]] = {}
        complete = True
        starts = {robot: (poses[robot].x, poses[robot].y) for robot in ROBOT_IDS}
        for robot in ROBOT_IDS:
            route = self.routes[robot]
            index = min(self.route_indices[robot], len(route) - 1)
            target = route[index]
            pose = poses[robot]
            distance = hypot(target[0] - pose.x, target[1] - pose.y)
            if distance <= 0.04 and index < len(route) - 1:
                index += 1
                self.route_indices[robot] = index
                target = route[index]
                distance = hypot(target[0] - pose.x, target[1] - pose.y)
            if index < len(route) - 1 or distance > 0.04:
                complete = False
            if distance > 0.32:
                scale = 0.32 / distance
                target = (pose.x + scale * (target[0] - pose.x), pose.y + scale * (target[1] - pose.y))
            commands[robot] = target
        if complete:
            self.state = "COMPLETE"
            self.reason = "formation completed one closed lap"
            return LapDecision(self.state, True, {}, self.reason)
        selected: tuple[float, dict[str, tuple[float, float]]] | None = None
        for scale in (1.0, 0.8, 0.6, 0.4, 0.2, 0.0):
            trial = {
                robot: (
                    starts[robot][0] + scale * (commands[robot][0] - starts[robot][0]),
                    starts[robot][1] + scale * (commands[robot][1] - starts[robot][1]),
                )
                for robot in ROBOT_IDS
            }
            if _synchronized_gap(starts, trial) >= self.planner.separation:
                selected = (scale, trial)
                break
        if selected is None or selected[0] <= 0.0:
            self.state = "PAUSED"
            self.reason = "formation route requires a synchronized safety pause"
            return LapDecision(self.state, True, {}, self.reason)
        velocities = {}
        for robot in ROBOT_IDS:
            dx = selected[1][robot][0] - starts[robot][0]
            dy = selected[1][robot][1] - starts[robot][1]
            distance = hypot(dx, dy)
            if distance <= 1e-9:
                velocities[robot] = (0.0, 0.0)
            else:
                speed = min(self.max_speed_mps, max(0.12, distance * 3.5))
                velocities[robot] = (speed * dx / distance, speed * dy / distance)
        self.state = "RUNNING"
        self.reason = "four robots tracking the closed lap at full allowed velocity"
        return LapDecision(self.state, False, velocities, self.reason)

    def _telemetry_issue(self, now_s: float, readings: dict[str, Telemetry]) -> str | None:
        for robot in ROBOT_IDS:
            item = readings.get(robot)
            if item is None or not item.connected:
                return f"{robot} offline"
            if item.pose is None or now_s - item.stamp_s > self.telemetry_timeout_s or item.stamp_s > now_s + 0.2:
                return f"{robot} pose missing or stale"
            if not all(isfinite(value) for value in (item.pose.x, item.pose.y, item.pose.yaw,
                                                     item.xy_variance_m2, item.yaw_variance_rad2)):
                return f"{robot} telemetry invalid"
            if item.xy_variance_m2 > 0.25 or item.yaw_variance_rad2 > 0.25:
                return f"{robot} localization uncertain"
            if not item.lidar_fresh:
                return f"{robot} lidar stale"
            if not item.path_clear:
                return f"{robot} path blocked by lidar"
        return None
