"""Fail closed mission state for a future ROS executor.

The session emits target waypoints or STOP decisions. It does not publish ROS
messages, arm a bridge, or control real hardware.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from math import hypot, isfinite
from pathlib import Path

from formation_planner import FormationPlanner, Plan, PlanningError, Pose, Request, ROBOT_IDS


@dataclass(frozen=True)
class Telemetry:
    pose: Pose | None
    stamp_s: float
    connected: bool
    xy_variance_m2: float = 0.0
    yaw_variance_rad2: float = 0.0
    lidar_fresh: bool = True
    path_clear: bool = True


@dataclass(frozen=True)
class Decision:
    state: str
    stop_all: bool
    robot_id: str | None = None
    waypoint: tuple[float, float] | None = None
    reason: str = ""


class ReconfigurationSession:
    def __init__(
        self,
        planner: FormationPlanner,
        request: Request,
        stable_reconnect_s: float = 2.0,
        telemetry_timeout_s: float = 0.7,
    ):
        self.planner = planner
        self.request = request
        self.stable_reconnect_s = stable_reconnect_s
        self.telemetry_timeout_s = telemetry_timeout_s
        self.state = "WAITING"
        self.reason = "awaiting four fresh robot states"
        self.plan: Plan | None = None
        self.step_index = 0
        self.waypoint_index = 0
        self.ready_since: float | None = None
        self.expected: dict[str, tuple[float, float]] = {}
        self.last_pair_distances: dict[tuple[str, str], float] = {}

    def tick(self, now_s: float, readings: dict[str, Telemetry]) -> Decision:
        if self.state == "ABORTED":
            return Decision(self.state, True, reason=self.reason)
        if self.state == "COMPLETE":
            return Decision(self.state, True, reason=self.reason)
        issue = self._telemetry_issue(now_s, readings)
        if issue:
            self._pause(issue)
            return Decision(self.state, True, reason=self.reason)
        if self.ready_since is None:
            self.ready_since = now_s
        if now_s - self.ready_since < self.stable_reconnect_s:
            self.state = "WAITING"
            self.reason = "waiting for stable localization after connection"
            return Decision(self.state, True, reason=self.reason)
        poses = {robot: readings[robot].pose for robot in ROBOT_IDS}
        assert all(pose is not None for pose in poses.values())
        pairs = {
            (first, second): hypot(poses[first].x - poses[second].x, poses[first].y - poses[second].y)
            for i, first in enumerate(ROBOT_IDS) for second in ROBOT_IDS[i + 1 :]
        }
        for pair, distance in pairs.items():
            if distance < 0.22:
                self._pause(f"{pair[0]}/{pair[1]} too close")
                return Decision(self.state, True, reason=self.reason)
            previous = self.last_pair_distances.get(pair)
            if previous is not None and distance < self.planner.separation and distance < previous - 0.02:
                self._pause(f"{pair[0]}/{pair[1]} closing while below separation limit")
                return Decision(self.state, True, reason=self.reason)
        self.last_pair_distances = pairs
        if self.plan is None:
            try:
                self.plan = self.planner.plan(poses, self.request)  # type: ignore[arg-type]
            except PlanningError as exc:
                self.state = "BLOCKED"
                self.reason = str(exc)
                return Decision(self.state, True, reason=self.reason)
            self.step_index = self.waypoint_index = 0
            self.expected = {robot: (pose.x, pose.y) for robot, pose in poses.items() if pose is not None}
            self.state = "READY"
            self.reason = "new route checked from current positions"
        if self.step_index >= len(self.plan.steps):
            self.state = "COMPLETE"
            self.reason = "all robots reached assigned formation slots"
            return Decision(self.state, True, reason=self.reason)
        step = self.plan.steps[self.step_index]
        for robot in ROBOT_IDS:
            if robot == step.robot_id:
                continue
            pose = poses[robot]
            assert pose is not None
            anchor = self.expected[robot]
            if hypot(pose.x - anchor[0], pose.y - anchor[1]) > 0.10:
                self._pause(f"stationary {robot} moved; replan required")
                return Decision(self.state, True, reason=self.reason)
        waypoint = step.waypoints[self.waypoint_index]
        moving_pose = poses[step.robot_id]
        assert moving_pose is not None
        start = self.expected[step.robot_id]
        from formation_planner import _point_segment_distance
        if _point_segment_distance((moving_pose.x, moving_pose.y), start, waypoint) > 0.10:
            self._pause(f"{step.robot_id} left the planned corridor")
            return Decision(self.state, True, reason=self.reason)
        if hypot(moving_pose.x - waypoint[0], moving_pose.y - waypoint[1]) <= 0.035:
            self.expected[step.robot_id] = waypoint
            self.waypoint_index += 1
            if self.waypoint_index >= len(step.waypoints):
                self.step_index += 1
                self.waypoint_index = 0
            return Decision("READY", True, reason="waypoint reached; checking next stage")
        self.state = "RUNNING"
        self.reason = f"{step.robot_id} {step.purpose}"
        return Decision(self.state, False, step.robot_id, waypoint, self.reason)

    def abort(self, reason: str = "operator_stop") -> Decision:
        self.plan = None
        self.state = "ABORTED"
        self.reason = reason
        return Decision(self.state, True, reason=reason)

    def _pause(self, reason: str) -> None:
        self.plan = None
        self.ready_since = None
        self.expected = {}
        self.last_pair_distances = {}
        self.state = "PAUSED"
        self.reason = reason

    def _telemetry_issue(self, now_s: float, readings: dict[str, Telemetry]) -> str | None:
        for robot in ROBOT_IDS:
            item = readings.get(robot)
            if item is None or not item.connected:
                return f"{robot} offline"
            if item.pose is None or now_s - item.stamp_s > self.telemetry_timeout_s or item.stamp_s > now_s + 0.2:
                return f"{robot} pose missing or stale"
            if not all(isfinite(v) for v in (item.pose.x, item.pose.y, item.pose.yaw, item.xy_variance_m2, item.yaw_variance_rad2)):
                return f"{robot} telemetry invalid"
            if item.xy_variance_m2 < 0 or item.yaw_variance_rad2 < 0:
                return f"{robot} covariance invalid"
            if item.xy_variance_m2 > 0.25 or item.yaw_variance_rad2 > 0.25:
                return f"{robot} localization uncertain"
            if not item.lidar_fresh:
                return f"{robot} lidar stale"
            if not item.path_clear:
                return f"{robot} path blocked by lidar"
        return None

    def checkpoint(self, path: str | Path) -> None:
        """Persist intent only; a restarted process must replan from fresh data."""
        destination = Path(path)
        payload = {"request": asdict(self.request), "last_state": self.state, "last_reason": self.reason}
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(destination)

    @classmethod
    def from_checkpoint(cls, planner: FormationPlanner, path: str | Path) -> "ReconfigurationSession":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        request = payload["request"]
        if request.get("center") is not None:
            request["center"] = tuple(request["center"])
        return cls(planner, Request(**request))
