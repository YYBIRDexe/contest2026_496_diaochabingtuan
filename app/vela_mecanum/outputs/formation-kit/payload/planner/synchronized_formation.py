from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations, product
from math import atan2, cos, hypot, isfinite, pi, sin

from formation_planner import FormationPlanner, MIN_SEPARATION_M, PlanningError, Pose, Request, ROBOT_IDS, _minimum_separation
from reconfiguration_session import Telemetry


@dataclass(frozen=True)
class SynchronizedPlan:
    request: Request
    routes: dict[str, tuple[tuple[float, float], ...]]
    targets: dict[str, tuple[float, float]]
    final_separation_m: float
    phase: str = "formation"


@dataclass(frozen=True)
class SynchronizedDecision:
    state: str
    stop_all: bool
    commands: dict[str, tuple[float, float]]
    reason: str = ""
    velocities: dict[str, tuple[float, float]] | None = None
    headings: dict[str, float] | None = None


def _route_points(start: Pose, route: list[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    return ((start.x, start.y), *tuple(route))


def _point_on_route(route: tuple[tuple[float, float], ...], progress: float) -> tuple[float, float]:
    if progress <= 0.0:
        return route[0]
    if progress >= 1.0:
        return route[-1]
    lengths = [hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(route, route[1:])]
    total = sum(lengths)
    if total <= 1e-9:
        return route[-1]
    distance = total * progress
    for index, length in enumerate(lengths):
        if distance <= length:
            ratio = distance / length if length > 1e-9 else 1.0
            start, end = route[index], route[index + 1]
            return (start[0] + ratio * (end[0] - start[0]), start[1] + ratio * (end[1] - start[1]))
        distance -= length
    return route[-1]


def _route_length(route: tuple[tuple[float, float], ...]) -> float:
    return sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(route, route[1:]))


def _point_segment_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return hypot(point[0] - start[0], point[1] - start[1])
    ratio = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    ratio = max(0.0, min(1.0, ratio))
    closest = (start[0] + ratio * dx, start[1] + ratio * dy)
    return hypot(point[0] - closest[0], point[1] - closest[1])


def _synchronized_gap(
    starts: dict[str, tuple[float, float]],
    ends: dict[str, tuple[float, float]],
    samples: int = 12,
) -> float:
    minimum = float("inf")
    for index, first in enumerate(ROBOT_IDS):
        for second in ROBOT_IDS[index + 1:]:
            for sample in range(samples + 1):
                ratio = sample / samples
                first_point = (
                    starts[first][0] + ratio * (ends[first][0] - starts[first][0]),
                    starts[first][1] + ratio * (ends[first][1] - starts[first][1]),
                )
                second_point = (
                    starts[second][0] + ratio * (ends[second][0] - starts[second][0]),
                    starts[second][1] + ratio * (ends[second][1] - starts[second][1]),
                )
                minimum = min(minimum, hypot(first_point[0] - second_point[0], first_point[1] - second_point[1]))
    return minimum


def _minimum_synchronized_gap(routes: dict[str, tuple[tuple[float, float], ...]], samples: int = 40) -> float:
    lengths = {robot: _route_length(route) for robot, route in routes.items()}
    minimum = float("inf")
    progress = [sample / samples for sample in range(samples + 1)]
    for index, first in enumerate(ROBOT_IDS):
        for second in ROBOT_IDS[index + 1 :]:
            for first_progress in progress:
                first_point = _point_on_route(routes[first], first_progress if lengths[first] > 1e-9 else 1.0)
                for second_progress in progress:
                    second_point = _point_on_route(routes[second], second_progress if lengths[second] > 1e-9 else 1.0)
                    minimum = min(minimum, hypot(first_point[0] - second_point[0], first_point[1] - second_point[1]))
    return minimum


def build_synchronized_plan(planner: FormationPlanner, current: dict[str, Pose], request: Request) -> SynchronizedPlan:
    if planner.map is not None:
        planner.map.clear_robot_footprints(current.values())
    choices = planner._target_choices(current, request)
    positions = {robot: (pose.x, pose.y) for robot, pose in current.items()}
    map_positions: dict[str, tuple[float, float]] = {}
    for targets, _slots, _estimate in choices:
        routes: dict[str, tuple[tuple[float, float], ...]] = {}
        for robot in ROBOT_IDS:
            route = planner._astar(positions[robot], targets[robot], map_positions, robot)
            if route is None:
                break
            routes[robot] = _route_points(current[robot], route)
        if len(routes) != len(ROBOT_IDS):
            continue
        minimum_gap = _minimum_synchronized_gap(routes)
        if _minimum_separation(targets) < planner.separation:
            continue
        plan = SynchronizedPlan(request, routes, targets, _minimum_separation(targets), "formation")
        try:
            for robot, route in routes.items():
                for start, end in zip(route, route[1:]):
                    if not planner._segment_free(start, end, map_positions, robot):
                        raise PlanningError(f"synchronized route is unsafe: {robot}")
        except PlanningError:
            continue
        return plan
    raise PlanningError("no collision free synchronized route to the requested formation")


def build_spread_plan(planner: FormationPlanner, current: dict[str, Pose], request: Request) -> SynchronizedPlan:
    if planner.map is not None:
        planner.map.clear_robot_footprints(current.values())
    center = (
        sum(pose.x for pose in current.values()) / len(ROBOT_IDS),
        sum(pose.y for pose in current.values()) / len(ROBOT_IDS),
    )
    spacing = max(request.spacing_m, planner.separation + 0.12)
    spread_request = Request("circle", spacing, center=center, assignment="auto")
    starts = {robot: (current[robot].x, current[robot].y) for robot in ROBOT_IDS}
    for targets, _slots, _estimate in planner._target_choices(current, spread_request):
        if _minimum_separation(targets) < planner.separation:
            continue
        routes: dict[str, tuple[tuple[float, float], ...]] = {}
        for robot in ROBOT_IDS:
            route = planner._astar(starts[robot], targets[robot], {}, robot)
            if route is None:
                break
            routes[robot] = _route_points(current[robot], route)
        if len(routes) != len(ROBOT_IDS):
            continue
        if _synchronized_gap(starts, targets) < planner.separation:
            continue
        try:
            for robot, route in routes.items():
                for start, end in zip(route, route[1:]):
                    if not planner._segment_free(start, end, {}, robot):
                        raise PlanningError(f"spread route is unsafe: {robot}")
        except PlanningError:
            continue
        return SynchronizedPlan(spread_request, routes, targets, _minimum_separation(targets), "spread")
    raise PlanningError("no collision free synchronized spread route")


class SynchronizedFormationSession:
    def __init__(self, planner: FormationPlanner, request: Request, stable_reconnect_s: float = 2.0, telemetry_timeout_s: float = 0.7):
        self.planner = planner
        self.request = request
        self.stable_reconnect_s = stable_reconnect_s
        self.telemetry_timeout_s = telemetry_timeout_s
        self.state = "WAITING"
        self.reason = "awaiting four fresh robot states"
        self.plan: SynchronizedPlan | None = None
        self.phase = "auto"
        self.route_indices = {robot: 1 for robot in ROBOT_IDS}
        self.ready_since: float | None = None

    def tick(self, now_s: float, readings: dict[str, Telemetry]) -> SynchronizedDecision:
        issue = self._telemetry_issue(now_s, readings)
        if issue:
            self.ready_since = None
            self.state = "PAUSED"
            self.reason = issue
            return SynchronizedDecision(self.state, True, {}, self.reason)
        if self.ready_since is None:
            self.ready_since = now_s
        if now_s - self.ready_since < self.stable_reconnect_s:
            self.state = "WAITING"
            self.reason = "waiting for stable localization after connection"
            return SynchronizedDecision(self.state, True, {}, self.reason)
        poses = {robot: readings[robot].pose for robot in ROBOT_IDS}
        assert all(pose is not None for pose in poses.values())
        for index, first in enumerate(ROBOT_IDS):
            for second in ROBOT_IDS[index + 1 :]:
                gap = hypot(poses[first].x - poses[second].x, poses[first].y - poses[second].y)
                if gap < self.planner.separation:
                    self.ready_since = None
                    self.state = "PAUSED"
                    self.reason = f"{first}/{second} too close"
                    return SynchronizedDecision(self.state, True, {}, self.reason)
        if self.plan is None:
            minimum_current_gap = min(
                hypot(poses[first].x - poses[second].x, poses[first].y - poses[second].y)
                for index, first in enumerate(ROBOT_IDS)
                for second in ROBOT_IDS[index + 1:]
            )
            if self.phase == "auto":
                self.phase = "spread" if minimum_current_gap < self.planner.separation else "formation"
            try:
                self.plan = (build_spread_plan(self.planner, poses, self.request)
                             if self.phase == "spread"
                             else build_synchronized_plan(self.planner, poses, self.request))
            except PlanningError as exc:
                if self.phase == "formation":
                    self.phase = "spread"
                    try:
                        self.plan = build_spread_plan(self.planner, poses, self.request)
                    except PlanningError:
                        self.state = "BLOCKED"
                        self.reason = str(exc)
                        return SynchronizedDecision(self.state, True, {}, self.reason)
                else:
                    self.state = "BLOCKED"
                    self.reason = str(exc)
                    return SynchronizedDecision(self.state, True, {}, self.reason)
            self.route_indices = {robot: 1 for robot in ROBOT_IDS}
            self.state = "READY"
            self.reason = f"synchronized {self.plan.phase} route checked from current positions"
        starts = {robot: (poses[robot].x, poses[robot].y) for robot in ROBOT_IDS}
        commands = {}
        complete = True
        for robot in ROBOT_IDS:
            route = self.plan.routes[robot]
            index = min(self.route_indices[robot], len(route) - 1)
            waypoint = route[index]
            pose = poses[robot]
            if hypot(pose.x - waypoint[0], pose.y - waypoint[1]) <= 0.035:
                if index < len(route) - 1:
                    self.route_indices[robot] = index + 1
                    waypoint = route[index + 1]
                else:
                    waypoint = (pose.x, pose.y)
            if self.route_indices[robot] < len(route) - 1 or hypot(pose.x - route[-1][0], pose.y - route[-1][1]) > 0.035:
                complete = False
            dx = waypoint[0] - pose.x
            dy = waypoint[1] - pose.y
            distance = hypot(dx, dy)
            if distance > 0.18:
                waypoint = (pose.x + 0.18 * dx / distance, pose.y + 0.18 * dy / distance)
            commands[robot] = waypoint
            segment_start = route[max(0, self.route_indices[robot] - 1)]
            corridor_distance = _point_segment_distance((pose.x, pose.y), segment_start, waypoint)
            if corridor_distance > 0.18 and hypot(pose.x - waypoint[0], pose.y - waypoint[1]) > 0.035:
                self.state = "PAUSED"
                self.reason = f"{robot} left the synchronized route corridor"
                return SynchronizedDecision(self.state, True, {}, self.reason)
        candidates = {
            robot: [
                (
                    scale,
                    (
                        starts[robot][0] + scale * (commands[robot][0] - starts[robot][0]),
                        starts[robot][1] + scale * (commands[robot][1] - starts[robot][1]),
                    ),
                )
                for scale in (1.0, 0.75, 0.5, 0.25, 0.1, 0.0)
            ]
            for robot in ROBOT_IDS
        }
        selected: tuple[float, dict[str, tuple[float, float]]] | None = None
        for choices in product(*(candidates[robot] for robot in ROBOT_IDS)):
            scales = [item[0] for item in choices]
            trial = {robot: item[1] for robot, item in zip(ROBOT_IDS, choices)}
            required_gap = self.planner.separation
            if _synchronized_gap(starts, trial) < required_gap:
                continue
            progress = sum(scale * hypot(commands[robot][0] - starts[robot][0],
                                        commands[robot][1] - starts[robot][1])
                           for robot, scale in zip(ROBOT_IDS, scales))
            if selected is None or progress > selected[0]:
                selected = (progress, trial)
        if selected is None or selected[0] <= 1e-4:
            self.plan = None
            self.state = "WAITING"
            self.reason = "replanning synchronized step around a collision risk"
            return SynchronizedDecision(self.state, True, {}, self.reason)
        commands = selected[1]
        if complete and self.plan.phase == "spread":
            self.phase = "formation"
            self.plan = None
            self.route_indices = {robot: 1 for robot in ROBOT_IDS}
            self.state = "WAITING"
            self.reason = "spread phase complete; replanning target formation"
            return SynchronizedDecision(self.state, True, {}, self.reason)
        if complete:
            self.state = "COMPLETE"
            self.reason = "all robots reached assigned formation slots"
            return SynchronizedDecision(self.state, True, commands, self.reason)
        self.state = "RUNNING"
        self.reason = "all four robots moving toward synchronized waypoints"
        velocities = {}
        for robot in ROBOT_IDS:
            dx = commands[robot][0] - starts[robot][0]
            dy = commands[robot][1] - starts[robot][1]
            length = hypot(dx, dy)
            if length <= 1e-9:
                velocities[robot] = (0.0, 0.0)
            else:
                speed = min(0.875, max(0.10, length * 3.0))
                velocities[robot] = (speed * dx / length, speed * dy / length)
        return SynchronizedDecision(self.state, False, commands, self.reason, velocities)

    def _telemetry_issue(self, now_s: float, readings: dict[str, Telemetry]) -> str | None:
        for robot in ROBOT_IDS:
            item = readings.get(robot)
            if item is None or not item.connected:
                return f"{robot} offline"
            if item.pose is None or now_s - item.stamp_s > self.telemetry_timeout_s or item.stamp_s > now_s + 0.2:
                return f"{robot} pose missing or stale"
            if not all(isfinite(value) for value in (item.pose.x, item.pose.y, item.pose.yaw, item.xy_variance_m2, item.yaw_variance_rad2)):
                return f"{robot} telemetry invalid"
            if item.xy_variance_m2 > 0.25 or item.yaw_variance_rad2 > 0.25:
                return f"{robot} localization uncertain"
            if not item.lidar_fresh:
                return f"{robot} lidar stale"
            if not item.path_clear:
                return f"{robot} path blocked by lidar"
        return None


@dataclass(frozen=True)
class MissionGeometry:
    center: tuple[float, float]
    heading_rad: float
    offsets: dict[str, tuple[float, float]]
    translate_targets: dict[str, tuple[float, float]]
    slots: dict[str, int]


class FormationTranslateSession:
    def __init__(
        self,
        planner: FormationPlanner,
        travel_m: float,
        cruise_speed_mps: float = 0.15,
        stable_reconnect_s: float = 1.5,
        telemetry_timeout_s: float = 0.7,
    ):
        if not 0.1 <= travel_m <= 2.0:
            raise PlanningError("travel distance must be between 0.1 and 2.0 m")
        if not 0.05 <= cruise_speed_mps <= 0.30:
            raise PlanningError("cruise speed must be between 0.05 and 0.30 m/s")
        self.planner = planner
        self.travel_m = travel_m
        self.cruise_speed_mps = cruise_speed_mps
        self.stable_reconnect_s = stable_reconnect_s
        self.telemetry_timeout_s = telemetry_timeout_s
        self.state = "WAITING"
        self.reason = "awaiting four fresh robot states"
        self.ready_since: float | None = None
        self.geometry: MissionGeometry | None = None
        self.motion_started_s: float | None = None
        self.motion_finished_s: float | None = None

    def tick(self, now_s: float, readings: dict[str, Telemetry]) -> SynchronizedDecision:
        issue = self._telemetry_issue(now_s, readings)
        if issue:
            self.ready_since = None
            self.state = "PAUSED"
            self.reason = issue
            return SynchronizedDecision(self.state, True, {}, self.reason)
        poses = {robot: readings[robot].pose for robot in ROBOT_IDS}
        assert all(pose is not None for pose in poses.values())
        if self.ready_since is None:
            self.ready_since = now_s
        if now_s - self.ready_since < self.stable_reconnect_s:
            self.state = "WAITING"
            self.reason = "waiting for stable localization"
            return SynchronizedDecision(self.state, True, {}, self.reason)
        for index, first in enumerate(ROBOT_IDS):
            for second in ROBOT_IDS[index + 1:]:
                if hypot(poses[first].x - poses[second].x, poses[first].y - poses[second].y) < self.planner.separation:
                    self.state = "PAUSED"
                    self.reason = f"{first}/{second} below minimum separation"
                    return SynchronizedDecision(self.state, True, {}, self.reason)
        if self.geometry is None:
            self.geometry = self._snapshot_geometry(poses)
            self.motion_started_s = now_s
        targets = self.geometry.translate_targets
        heading = self.geometry.heading_rad
        if all(
            hypot(poses[robot].x - targets[robot][0], poses[robot].y - targets[robot][1]) <= 0.05
            and abs((heading - poses[robot].yaw + pi) % (2 * pi) - pi) <= 0.08
            for robot in ROBOT_IDS
        ):
            self.motion_finished_s = now_s
            self.state = "COMPLETE"
            self.reason = "formation completed synchronized translation"
            return SynchronizedDecision(
                self.state, True, dict(targets), self.reason,
                {robot: (0.0, 0.0) for robot in ROBOT_IDS},
                {robot: heading for robot in ROBOT_IDS},
            )
        current_center = (
            sum(poses[robot].x for robot in ROBOT_IDS) / len(ROBOT_IDS),
            sum(poses[robot].y for robot in ROBOT_IDS) / len(ROBOT_IDS),
        )
        direction = (cos(heading), sin(heading))
        progress_m = max(0.0, min(
            self.travel_m,
            (current_center[0] - self.geometry.center[0]) * direction[0]
            + (current_center[1] - self.geometry.center[1]) * direction[1],
        ))
        command_progress = min(self.travel_m, progress_m + 0.18)
        desired_center = (
            self.geometry.center[0] + command_progress * direction[0],
            self.geometry.center[1] + command_progress * direction[1],
        )
        desired = {
            robot: (
                desired_center[0] + self.geometry.offsets[robot][0],
                desired_center[1] + self.geometry.offsets[robot][1],
            )
            for robot in ROBOT_IDS
        }
        preferred = {}
        for robot in ROBOT_IDS:
            dx = desired[robot][0] - poses[robot].x
            dy = desired[robot][1] - poses[robot].y
            distance = hypot(dx, dy)
            speed = min(self.cruise_speed_mps, 1.5 * distance)
            preferred[robot] = (0.0, 0.0) if distance <= 0.01 else (speed * dx / distance, speed * dy / distance)
        velocities = self._safe_velocities(poses, preferred)
        commands = {
            robot: (
                poses[robot].x + 0.2 * velocities[robot][0],
                poses[robot].y + 0.2 * velocities[robot][1],
            )
            for robot in ROBOT_IDS
        }
        self.state = "RUNNING"
        self.reason = "all four robots translating while preserving current formation"
        return SynchronizedDecision(
            self.state, False, commands, self.reason, velocities,
            {robot: heading for robot in ROBOT_IDS},
        )

    def _snapshot_geometry(self, poses: dict[str, Pose]) -> MissionGeometry:
        if self.planner.map is not None:
            self.planner.map.clear_robot_footprints(poses.values())
        center = (
            sum(poses[robot].x for robot in ROBOT_IDS) / len(ROBOT_IDS),
            sum(poses[robot].y for robot in ROBOT_IDS) / len(ROBOT_IDS),
        )
        heading = atan2(
            sum(sin(poses[robot].yaw) for robot in ROBOT_IDS),
            sum(cos(poses[robot].yaw) for robot in ROBOT_IDS),
        )
        offsets = {
            robot: (poses[robot].x - center[0], poses[robot].y - center[1])
            for robot in ROBOT_IDS
        }
        shift = (self.travel_m * cos(heading), self.travel_m * sin(heading))
        targets = {
            robot: (poses[robot].x + shift[0], poses[robot].y + shift[1])
            for robot in ROBOT_IDS
        }
        starts = {robot: (poses[robot].x, poses[robot].y) for robot in ROBOT_IDS}
        if _synchronized_gap(starts, targets) < self.planner.separation:
            raise PlanningError("translation violates minimum separation")
        for robot in ROBOT_IDS:
            if not self.planner._segment_free(starts[robot], targets[robot], {}, robot):
                raise PlanningError(f"translation path is unsafe: {robot}")
        return MissionGeometry(
            center, heading, offsets, targets,
            {robot: index for index, robot in enumerate(ROBOT_IDS)},
        )

    def _safe_velocities(
        self,
        poses: dict[str, Pose],
        preferred: dict[str, tuple[float, float]],
    ) -> dict[str, tuple[float, float]]:
        starts = {robot: (poses[robot].x, poses[robot].y) for robot in ROBOT_IDS}
        selected: tuple[float, dict[str, tuple[float, float]]] | None = None
        scales = (1.0, 0.75, 0.5, 0.25, 0.1, 0.0)
        for choice in product(scales, repeat=len(ROBOT_IDS)):
            ends = {
                robot: (
                    starts[robot][0] + 0.2 * preferred[robot][0] * scale,
                    starts[robot][1] + 0.2 * preferred[robot][1] * scale,
                )
                for robot, scale in zip(ROBOT_IDS, choice)
            }
            if _synchronized_gap(starts, ends) < self.planner.separation:
                continue
            if any(not self.planner._segment_free(starts[robot], ends[robot], {}, robot) for robot in ROBOT_IDS):
                continue
            progress = sum(hypot(*preferred[robot]) * scale for robot, scale in zip(ROBOT_IDS, choice))
            if selected is None or progress > selected[0]:
                selected = (
                    progress,
                    {
                        robot: (preferred[robot][0] * scale, preferred[robot][1] * scale)
                        for robot, scale in zip(ROBOT_IDS, choice)
                    },
                )
        if selected is None:
            return {robot: (0.0, 0.0) for robot in ROBOT_IDS}
        return selected[1]

    def _telemetry_issue(self, now_s: float, readings: dict[str, Telemetry]) -> str | None:
        for robot in ROBOT_IDS:
            item = readings.get(robot)
            if item is None or not item.connected:
                return f"{robot} offline"
            if item.pose is None or now_s - item.stamp_s > self.telemetry_timeout_s or item.stamp_s > now_s + 0.2:
                return f"{robot} pose missing or stale"
            if not all(isfinite(value) for value in (item.pose.x, item.pose.y, item.pose.yaw, item.xy_variance_m2, item.yaw_variance_rad2)):
                return f"{robot} telemetry invalid"
            if item.xy_variance_m2 > 0.25 or item.yaw_variance_rad2 > 0.25:
                return f"{robot} localization uncertain"
            if not item.lidar_fresh:
                return f"{robot} lidar stale"
            if not item.path_clear:
                return f"{robot} path blocked by lidar"
        return None


class TranslateThenLineSession:
    def __init__(
        self,
        planner: FormationPlanner,
        spacing_m: float,
        travel_m: float = 1.0,
        stable_reconnect_s: float = 1.5,
        telemetry_timeout_s: float = 0.7,
    ):
        if spacing_m < planner.separation:
            raise PlanningError(f"line spacing must be at least {planner.separation:.2f} m")
        if travel_m <= 0.0:
            raise PlanningError("travel distance must be positive")
        self.planner = planner
        self.spacing_m = spacing_m
        self.travel_m = travel_m
        self.stable_reconnect_s = stable_reconnect_s
        self.telemetry_timeout_s = telemetry_timeout_s
        self.state = "WAITING"
        self.reason = "awaiting four fresh robot states"
        self.stage = "TRANSLATE"
        self.geometry: MissionGeometry | None = None
        self.line_targets: dict[str, tuple[float, float]] | None = None
        self.line_slots: dict[str, int] | None = None
        self.anchor_pose: tuple[float, float] | None = None
        self.ready_since: float | None = None

    def tick(self, now_s: float, readings: dict[str, Telemetry]) -> SynchronizedDecision:
        issue = self._telemetry_issue(now_s, readings)
        if issue:
            self.ready_since = None
            self.state = "PAUSED"
            self.reason = issue
            return SynchronizedDecision(self.state, True, {}, self.reason)
        poses = {robot: readings[robot].pose for robot in ROBOT_IDS}
        assert all(pose is not None for pose in poses.values())
        if self.ready_since is None:
            self.ready_since = now_s
        if now_s - self.ready_since < self.stable_reconnect_s:
            self.state = "WAITING"
            self.reason = "waiting for stable localization"
            return SynchronizedDecision(self.state, True, {}, self.reason)
        for index, first in enumerate(ROBOT_IDS):
            for second in ROBOT_IDS[index + 1:]:
                gap = hypot(poses[first].x - poses[second].x, poses[first].y - poses[second].y)
                if gap < self.planner.separation:
                    self.state = "PAUSED"
                    self.reason = f"{first}/{second} below minimum separation"
                    return SynchronizedDecision(self.state, True, {}, self.reason)
        if self.geometry is None:
            self.geometry = self._snapshot_geometry(poses)
        if self.stage == "TRANSLATE":
            decision = self._track_translate(poses)
            if decision is not None:
                return decision
            self.anchor_pose = (poses["robot4"].x, poses["robot4"].y)
            self.line_targets, self.line_slots = self._build_line_targets(
                poses, self.anchor_pose, self.geometry.heading_rad
            )
            self.stage = "EXPAND_LINE"
        assert self.line_targets is not None
        return self._track_targets(poses, self.line_targets, "EXPAND_LINE")

    def _snapshot_geometry(self, poses: dict[str, Pose]) -> MissionGeometry:
        if self.planner.map is not None:
            self.planner.map.clear_robot_footprints(poses.values())
        center = (
            sum(poses[robot].x for robot in ROBOT_IDS) / len(ROBOT_IDS),
            sum(poses[robot].y for robot in ROBOT_IDS) / len(ROBOT_IDS),
        )
        heading = atan2(
            sum(sin(poses[robot].yaw) for robot in ROBOT_IDS),
            sum(cos(poses[robot].yaw) for robot in ROBOT_IDS),
        )
        offsets = {robot: (poses[robot].x - center[0], poses[robot].y - center[1]) for robot in ROBOT_IDS}
        shift = (self.travel_m * cos(heading), self.travel_m * sin(heading))
        targets = {robot: (poses[robot].x + shift[0], poses[robot].y + shift[1]) for robot in ROBOT_IDS}
        starts = {robot: (poses[robot].x, poses[robot].y) for robot in ROBOT_IDS}
        if _synchronized_gap(starts, targets) < self.planner.separation:
            raise PlanningError("translation violates minimum separation")
        for robot in ROBOT_IDS:
            if not self.planner._segment_free(starts[robot], targets[robot], {}, robot):
                raise PlanningError(f"translation path is unsafe: {robot}")
        return MissionGeometry(center, heading, offsets, targets, {robot: index for index, robot in enumerate(ROBOT_IDS)})

    def _track_translate(self, poses: dict[str, Pose]) -> SynchronizedDecision | None:
        assert self.geometry is not None
        targets = self.geometry.translate_targets
        if all(hypot(poses[robot].x - targets[robot][0], poses[robot].y - targets[robot][1]) <= 0.05 for robot in ROBOT_IDS):
            return None
        current_center = (
            sum(poses[robot].x for robot in ROBOT_IDS) / len(ROBOT_IDS),
            sum(poses[robot].y for robot in ROBOT_IDS) / len(ROBOT_IDS),
        )
        direction = (cos(self.geometry.heading_rad), sin(self.geometry.heading_rad))
        progress_m = max(0.0, min(self.travel_m,
            (current_center[0] - self.geometry.center[0]) * direction[0]
            + (current_center[1] - self.geometry.center[1]) * direction[1]))
        command_progress = min(self.travel_m, progress_m + 0.18)
        desired_center = (
            self.geometry.center[0] + command_progress * direction[0],
            self.geometry.center[1] + command_progress * direction[1],
        )
        desired = {
            robot: (desired_center[0] + self.geometry.offsets[robot][0],
                    desired_center[1] + self.geometry.offsets[robot][1])
            for robot in ROBOT_IDS
        }
        return self._track_targets(poses, desired, "TRANSLATE")

    def _build_line_targets(
        self,
        poses: dict[str, Pose],
        anchor: tuple[float, float],
        heading: float,
    ) -> tuple[dict[str, tuple[float, float]], dict[str, int]]:
        line_heading = heading + pi / 2
        peers = ("robot1", "robot2", "robot3")
        candidates = []
        for sign in (1.0, -1.0):
            slot_points = {
                slot: (
                    anchor[0] + sign * slot * self.spacing_m * cos(line_heading),
                    anchor[1] + sign * slot * self.spacing_m * sin(line_heading),
                )
                for slot in (-1, 0, 1, 2)
            }
            if any(not self.planner._point_free(point) for point in slot_points.values()):
                continue
            for peer_slots in permutations((-1, 1, 2)):
                slots = {"robot4": 0, **{robot: slot for robot, slot in zip(peers, peer_slots)}}
                targets = {robot: slot_points[slots[robot]] for robot in ROBOT_IDS}
                if _minimum_separation(targets) < self.planner.separation:
                    continue
                travel = sum(hypot(poses[robot].x - targets[robot][0], poses[robot].y - targets[robot][1]) for robot in ROBOT_IDS)
                candidates.append((travel, targets, slots))
        if candidates:
            _, targets, slots = min(candidates, key=lambda item: item[0])
            return targets, slots
        raise PlanningError("robot4 anchored line does not fit in the safe map")

    def _track_targets(
        self,
        poses: dict[str, Pose],
        targets: dict[str, tuple[float, float]],
        stage: str,
    ) -> SynchronizedDecision:
        if stage == "EXPAND_LINE" and all(
            hypot(poses[robot].x - targets[robot][0], poses[robot].y - targets[robot][1]) <= 0.05
            for robot in ROBOT_IDS
        ):
            self.state = "COMPLETE"
            self.reason = "four robots completed translate and robot4 anchored line"
            return SynchronizedDecision(self.state, True, dict(targets), self.reason,
                                        {robot: (0.0, 0.0) for robot in ROBOT_IDS})
        preferred = {}
        for robot in ROBOT_IDS:
            dx = targets[robot][0] - poses[robot].x
            dy = targets[robot][1] - poses[robot].y
            distance = hypot(dx, dy)
            if distance <= 0.02:
                preferred[robot] = (0.0, 0.0)
            else:
                speed = min(0.50, max(0.05, 1.5 * distance))
                preferred[robot] = (speed * dx / distance, speed * dy / distance)
        velocities = self._safe_velocities(poses, preferred)
        commands = {
            robot: (poses[robot].x + 0.2 * velocities[robot][0], poses[robot].y + 0.2 * velocities[robot][1])
            for robot in ROBOT_IDS
        }
        self.state = "RUNNING"
        self.reason = f"all four robots executing {stage}"
        return SynchronizedDecision(self.state, False, commands, self.reason, velocities)

    def _safe_velocities(
        self,
        poses: dict[str, Pose],
        preferred: dict[str, tuple[float, float]],
    ) -> dict[str, tuple[float, float]]:
        starts = {robot: (poses[robot].x, poses[robot].y) for robot in ROBOT_IDS}
        selected: tuple[float, dict[str, tuple[float, float]]] | None = None
        scales = (1.0, 0.75, 0.5, 0.25, 0.1, 0.0)
        for choice in product(scales, repeat=len(ROBOT_IDS)):
            ends = {
                robot: (starts[robot][0] + 0.2 * preferred[robot][0] * scale,
                        starts[robot][1] + 0.2 * preferred[robot][1] * scale)
                for robot, scale in zip(ROBOT_IDS, choice)
            }
            if _synchronized_gap(starts, ends) < self.planner.separation:
                continue
            if any(not self.planner._segment_free(starts[robot], ends[robot], {}, robot) for robot in ROBOT_IDS):
                continue
            progress = sum(hypot(*preferred[robot]) * scale for robot, scale in zip(ROBOT_IDS, choice))
            if selected is None or progress > selected[0]:
                selected = (progress, {
                    robot: (preferred[robot][0] * scale, preferred[robot][1] * scale)
                    for robot, scale in zip(ROBOT_IDS, choice)
                })
        if selected is None:
            return {robot: (0.0, 0.0) for robot in ROBOT_IDS}
        return selected[1]

    def _telemetry_issue(self, now_s: float, readings: dict[str, Telemetry]) -> str | None:
        for robot in ROBOT_IDS:
            item = readings.get(robot)
            if item is None or not item.connected:
                return f"{robot} offline"
            if item.pose is None or now_s - item.stamp_s > self.telemetry_timeout_s or item.stamp_s > now_s + 0.2:
                return f"{robot} pose missing or stale"
            if not all(isfinite(value) for value in (item.pose.x, item.pose.y, item.pose.yaw, item.xy_variance_m2, item.yaw_variance_rad2)):
                return f"{robot} telemetry invalid"
            if item.xy_variance_m2 > 0.25 or item.yaw_variance_rad2 > 0.25:
                return f"{robot} localization uncertain"
            if not item.lidar_fresh:
                return f"{robot} lidar stale"
            if not item.path_clear:
                return f"{robot} path blocked by lidar"
        return None


class SquareTurnSession(TranslateThenLineSession):
    def __init__(
        self,
        planner: FormationPlanner,
        spacing_m: float,
        straight_m: float = 0.6,
        turn_radius_m: float = 0.4,
        cruise_speed_mps: float = 0.15,
        turn_direction: str = "auto",
        stable_reconnect_s: float = 1.5,
        telemetry_timeout_s: float = 0.7,
    ):
        super().__init__(planner, spacing_m, 1.0, stable_reconnect_s, telemetry_timeout_s)
        if straight_m <= 0.0 or turn_radius_m <= 0.0:
            raise PlanningError("straight distance and turn radius must be positive")
        if not 0.05 <= cruise_speed_mps <= 0.30:
            raise PlanningError("cruise speed must be between 0.05 and 0.30 m/s")
        if turn_direction not in ("auto", "left", "right"):
            raise PlanningError("turn direction must be auto, left or right")
        self.straight_m = straight_m
        self.turn_radius_m = turn_radius_m
        self.cruise_speed_mps = cruise_speed_mps
        self.turn_direction = turn_direction
        self.stage = "FORM_SQUARE"
        self.square_targets: dict[str, tuple[float, float]] | None = None
        self.square_slots: dict[str, int] | None = None
        self.square_heading_rad: float | None = None
        self.square_offsets: dict[str, tuple[float, float]] | None = None
        self.center_path: tuple[tuple[float, float, float], ...] | None = None
        self.path_index = 0
        self.motion_started_s: float | None = None
        self.motion_finished_s: float | None = None

    def tick(self, now_s: float, readings: dict[str, Telemetry]) -> SynchronizedDecision:
        issue = self._telemetry_issue(now_s, readings)
        if issue:
            self.ready_since = None
            self.state = "PAUSED"
            self.reason = issue
            return SynchronizedDecision(self.state, True, {}, self.reason)
        poses = {robot: readings[robot].pose for robot in ROBOT_IDS}
        assert all(pose is not None for pose in poses.values())
        if self.ready_since is None:
            self.ready_since = now_s
        if now_s - self.ready_since < self.stable_reconnect_s:
            self.state = "WAITING"
            self.reason = "waiting for stable localization"
            return SynchronizedDecision(self.state, True, {}, self.reason)
        for index, first in enumerate(ROBOT_IDS):
            for second in ROBOT_IDS[index + 1:]:
                if hypot(poses[first].x - poses[second].x, poses[first].y - poses[second].y) < self.planner.separation:
                    self.state = "PAUSED"
                    self.reason = f"{first}/{second} below minimum separation"
                    return SynchronizedDecision(self.state, True, {}, self.reason)
        if self.square_targets is None:
            (self.square_targets, self.square_slots, self.square_heading_rad,
             self.square_offsets, self.center_path) = self._build_square_targets(poses)
        if self.stage == "FORM_SQUARE":
            if not self._targets_reached(poses, self.square_targets, self.square_heading_rad):
                return self._drive_targets(
                    poses, self.square_targets, "FORM_SQUARE", 0.30, self.square_heading_rad
                )
            self.path_index = 0
            self.motion_started_s = now_s
            self.stage = "FOLLOW_PATH"
        assert self.center_path is not None and self.square_offsets is not None
        center = (
            sum(poses[robot].x for robot in ROBOT_IDS) / len(ROBOT_IDS),
            sum(poses[robot].y for robot in ROBOT_IDS) / len(ROBOT_IDS),
        )
        while self.path_index < len(self.center_path) - 1:
            target_center = self.center_path[self.path_index]
            if hypot(center[0] - target_center[0], center[1] - target_center[1]) > 0.07:
                break
            self.path_index += 1
        target_center = self.center_path[self.path_index]
        targets = self._formation_targets(target_center)
        if self.path_index == len(self.center_path) - 1 and self._targets_reached(poses, targets, target_center[2]):
            self.motion_finished_s = now_s
            self.state = "COMPLETE"
            self.reason = "square formation completed straight and ninety degree turn"
            return SynchronizedDecision(self.state, True, targets, self.reason,
                                        {robot: (0.0, 0.0) for robot in ROBOT_IDS},
                                        {robot: target_center[2] for robot in ROBOT_IDS})
        return self._drive_targets(
            poses, targets, "FOLLOW_PATH", self.cruise_speed_mps, target_center[2]
        )

    def _build_square_targets(self, poses: dict[str, Pose]):
        center = (
            sum(poses[robot].x for robot in ROBOT_IDS) / len(ROBOT_IDS),
            sum(poses[robot].y for robot in ROBOT_IDS) / len(ROBOT_IDS),
        )
        mean_heading = atan2(
            sum(sin(poses[robot].yaw) for robot in ROBOT_IDS),
            sum(cos(poses[robot].yaw) for robot in ROBOT_IDS),
        )
        candidates = []
        for heading in (mean_heading, mean_heading + pi / 2, mean_heading + pi, mean_heading - pi / 2):
            choices = self.planner._target_choices(
                poses, Request("square", self.spacing_m, center=center, heading_rad=heading, assignment="auto")
            )
            for targets, slots, estimate in choices[:12]:
                starts = {robot: (poses[robot].x, poses[robot].y) for robot in ROBOT_IDS}
                if any(not self.planner._segment_free(starts[robot], targets[robot], {}, robot) for robot in ROBOT_IDS):
                    continue
                self.square_heading_rad = heading
                self.square_offsets = self._square_body_offsets(targets)
                try:
                    path = self._build_center_path(targets)
                except PlanningError:
                    continue
                candidates.append((estimate, targets, slots, heading, dict(self.square_offsets), path))
        if not candidates:
            raise PlanningError("no complete square turn route fits in the safe map")
        _, targets, slots, heading, offsets, path = min(candidates, key=lambda item: item[0])
        return targets, slots, heading, offsets, path

    def _square_body_offsets(self, targets: dict[str, tuple[float, float]]):
        center = (
            sum(targets[robot][0] for robot in ROBOT_IDS) / len(ROBOT_IDS),
            sum(targets[robot][1] for robot in ROBOT_IDS) / len(ROBOT_IDS),
        )
        assert self.square_heading_rad is not None
        mission_heading = self.square_heading_rad
        return {
            robot: (
                cos(mission_heading) * (targets[robot][0] - center[0]) + sin(mission_heading) * (targets[robot][1] - center[1]),
                -sin(mission_heading) * (targets[robot][0] - center[0]) + cos(mission_heading) * (targets[robot][1] - center[1]),
            )
            for robot in ROBOT_IDS
        }

    def _build_center_path(self, targets: dict[str, tuple[float, float]]):
        center = (
            sum(targets[robot][0] for robot in ROBOT_IDS) / len(ROBOT_IDS),
            sum(targets[robot][1] for robot in ROBOT_IDS) / len(ROBOT_IDS),
        )
        assert self.square_heading_rad is not None
        heading = self.square_heading_rad
        directions = (1.0, -1.0) if self.turn_direction == "auto" else ((1.0,) if self.turn_direction == "left" else (-1.0,))
        for direction in directions:
            path = []
            step_m = max(0.025, self.cruise_speed_mps * 0.2)
            straight_samples = max(1, int(self.straight_m / step_m))
            for index in range(straight_samples + 1):
                distance = self.straight_m * index / straight_samples
                path.append((center[0] + distance * cos(heading), center[1] + distance * sin(heading), heading))
            first_end = path[-1]
            arc_samples = max(4, int((pi * self.turn_radius_m / 2) / step_m))
            for index in range(1, arc_samples + 1):
                angle = pi * index / (2 * arc_samples)
                arc_heading = heading + direction * angle
                x = first_end[0] + direction * self.turn_radius_m * (sin(arc_heading) - sin(heading))
                y = first_end[1] - direction * self.turn_radius_m * (cos(arc_heading) - cos(heading))
                path.append((x, y, arc_heading))
            final_heading = heading + direction * pi / 2
            arc_end = path[-1]
            for index in range(1, straight_samples + 1):
                distance = self.straight_m * index / straight_samples
                path.append((arc_end[0] + distance * cos(final_heading), arc_end[1] + distance * sin(final_heading), final_heading))
            if self._path_is_safe(tuple(path)):
                return tuple(path)
        raise PlanningError("square turn path does not fit in the safe map")

    def _path_is_safe(self, path: tuple[tuple[float, float, float], ...]) -> bool:
        clearance_m = 0.25
        x0, x1, y0, y1 = self.planner.arena
        for center in path:
            targets = self._formation_targets(center)
            if _minimum_separation(targets) < self.planner.separation:
                return False
            for target in targets.values():
                if not (x0 + clearance_m <= target[0] <= x1 - clearance_m
                        and y0 + clearance_m <= target[1] <= y1 - clearance_m):
                    return False
                if self.planner.map is not None and not self.planner.map.is_free(target[0], target[1], clearance_m):
                    return False
        return True

    def _formation_targets(self, center: tuple[float, float, float]):
        assert self.square_offsets is not None
        return {
            robot: (
                center[0] + cos(center[2]) * self.square_offsets[robot][0] - sin(center[2]) * self.square_offsets[robot][1],
                center[1] + sin(center[2]) * self.square_offsets[robot][0] + cos(center[2]) * self.square_offsets[robot][1],
            )
            for robot in ROBOT_IDS
        }

    def _targets_reached(
        self,
        poses: dict[str, Pose],
        targets: dict[str, tuple[float, float]],
        heading: float | None = None,
    ) -> bool:
        return all(
            hypot(poses[robot].x - targets[robot][0], poses[robot].y - targets[robot][1]) <= 0.05
            and (heading is None or abs((heading - poses[robot].yaw + pi) % (2 * pi) - pi) <= 0.08)
            for robot in ROBOT_IDS
        )

    def _drive_targets(self, poses, targets, stage, speed_limit, desired_heading):
        preferred = {}
        for robot in ROBOT_IDS:
            dx = targets[robot][0] - poses[robot].x
            dy = targets[robot][1] - poses[robot].y
            distance = hypot(dx, dy)
            speed = min(speed_limit, 1.5 * distance)
            preferred[robot] = (0.0, 0.0) if distance <= 0.01 else (speed * dx / distance, speed * dy / distance)
        velocities = self._safe_velocities(poses, preferred)
        commands = {robot: (poses[robot].x + 0.2 * velocities[robot][0], poses[robot].y + 0.2 * velocities[robot][1]) for robot in ROBOT_IDS}
        self.state = "RUNNING"
        self.reason = f"all four robots executing {stage}"
        return SynchronizedDecision(
            self.state, False, commands, self.reason, velocities,
            {robot: desired_heading for robot in ROBOT_IDS},
        )
