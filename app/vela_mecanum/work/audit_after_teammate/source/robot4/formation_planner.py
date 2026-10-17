"""Offline, collision checked four robot formation transition planner.

This module never opens a network socket or publishes motor commands. A live
executor must recheck every segment against fresh localization and lidar data.
"""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import permutations
from math import atan2, cos, hypot, isfinite, pi, sin, sqrt
from pathlib import Path
from typing import Iterable


ROBOT_IDS = ("robot1", "robot2", "robot3", "robot4")
FORMATIONS = ("square", "line", "circle", "diamond")


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    yaw: float = 0.0


@dataclass(frozen=True)
class Request:
    formation: str
    spacing_m: float
    center: tuple[float, float] | None = None
    heading_rad: float | None = None
    assignment: str = "auto"  # "auto" or "fixed"


@dataclass(frozen=True)
class Step:
    robot_id: str
    waypoints: tuple[tuple[float, float], ...]
    purpose: str


@dataclass(frozen=True)
class Plan:
    request: Request
    targets: dict[str, tuple[float, float]]
    slots: dict[str, int]
    steps: tuple[Step, ...]
    final_separation_m: float


class PlanningError(RuntimeError):
    pass


class OccupancyGrid:
    """ROS PGM map with a fixed collision radius around occupied pixels."""

    def __init__(self, path: str | Path, resolution: float, origin: tuple[float, float], min_component_pixels: int = 8):
        data = Path(path).read_bytes()
        offset = 0

        def token() -> bytes:
            nonlocal offset
            while offset < len(data):
                if data[offset] == 35:  # PGM comment
                    offset = data.find(b"\n", offset) + 1
                elif data[offset] in b" \t\r\n":
                    offset += 1
                else:
                    break
            start = offset
            while offset < len(data) and data[offset] not in b" \t\r\n":
                offset += 1
            return data[start:offset]

        if token() != b"P5":
            raise ValueError("only binary P5 PGM maps are supported")
        self.width, self.height = int(token()), int(token())
        if int(token()) != 255:
            raise ValueError("expected 8 bit PGM")
        offset += 1
        self.pixels = data[offset : offset + self.width * self.height]
        if len(self.pixels) != self.width * self.height:
            raise ValueError("truncated PGM")
        self.resolution = resolution
        self.origin = origin
        self.occupied = self._large_components(min_component_pixels)
        self._free_cache: dict[tuple[int, int, int], bool] = {}
        self._cleared_centers: tuple[tuple[float, float, float], ...] = ()

    def clear_robot_footprints(self, poses: Iterable[Pose], radius: float = 0.18) -> None:
        """Remove map marks underneath robots confirmed present by live sensors."""
        self._cleared_centers = tuple((pose.x, pose.y, radius) for pose in poses)
        self._free_cache.clear()

    def _large_components(self, minimum: int) -> set[int]:
        occupied = {index for index, pixel in enumerate(self.pixels) if pixel < 128}
        if minimum <= 1:
            return occupied
        kept: set[int] = set()
        unseen = set(occupied)
        while unseen:
            seed = unseen.pop()
            component = {seed}
            frontier = [seed]
            while frontier:
                current = frontier.pop()
                x, y = current % self.width, current // self.width
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == dy == 0:
                            continue
                        nx, ny = x + dx, y + dy
                        if not (0 <= nx < self.width and 0 <= ny < self.height):
                            continue
                        neighbor = ny * self.width + nx
                        if neighbor in unseen:
                            unseen.remove(neighbor)
                            component.add(neighbor)
                            frontier.append(neighbor)
            if len(component) >= minimum:
                kept.update(component)
        return kept

    def is_free(self, x: float, y: float, radius: float) -> bool:
        px = round((x - self.origin[0]) / self.resolution)
        py = self.height - 1 - round((y - self.origin[1]) / self.resolution)
        reach = round(radius / self.resolution)
        key = px, py, reach
        cached = self._free_cache.get(key)
        if cached is not None:
            return cached
        free = True
        for dy in range(-reach, reach + 1):
            for dx in range(-reach, reach + 1):
                if dx * dx + dy * dy > reach * reach:
                    continue
                ix, iy = px + dx, py + dy
                if not (0 <= ix < self.width and 0 <= iy < self.height):
                    free = False
                    break
                pixel_x = self.origin[0] + ix * self.resolution
                pixel_y = self.origin[1] + (self.height - 1 - iy) * self.resolution
                cleared = any(hypot(pixel_x - cx, pixel_y - cy) <= cr for cx, cy, cr in self._cleared_centers)
                if iy * self.width + ix in self.occupied and not cleared:
                    free = False
                    break
            if not free:
                break
        self._free_cache[key] = free
        return free


class FormationPlanner:
    def __init__(
        self,
        arena: tuple[float, float, float, float] = (-3.0, 3.0, -3.0, 3.0),
        map_grid: OccupancyGrid | None = None,
        robot_radius_m: float = 0.12,
        separation_m: float = 0.35,
        grid_step_m: float = 0.10,
    ):
        self.arena = arena
        self.map = map_grid
        self.robot_radius = robot_radius_m
        self.separation = separation_m
        self.grid_step = grid_step_m

    def plan(self, current: dict[str, Pose], request: Request) -> Plan:
        if self.map is not None:
            self.map.clear_robot_footprints(current.values())
        self._validate(current, request)
        positions = {robot: (pose.x, pose.y) for robot, pose in current.items()}
        recovery = self._recover_close_pairs(positions)
        choices = self._target_choices(current, request)
        best: Plan | None = None
        best_cost = float("inf")
        for targets, slots, estimate in choices[:12]:
            if estimate >= best_cost:
                continue
            result = self._route_to_targets(positions, targets)
            if result is None:
                continue
            route, travel = result
            total = estimate + travel + 0.2 * len(route)
            if total < best_cost:
                steps = (*recovery, *route)
                best = Plan(request, targets, slots, steps, _minimum_separation(targets))
                best_cost = total
        if best is None:
            raise PlanningError("no collision free sequential route to the requested formation")
        self.verify(current, best)
        return best

    def verify(self, current: dict[str, Pose], plan: Plan) -> None:
        positions = {robot: (pose.x, pose.y) for robot, pose in current.items()}
        for step in plan.steps:
            for waypoint in step.waypoints:
                if not self._segment_free(positions[step.robot_id], waypoint, positions, step.robot_id, step.purpose == "separate"):
                    raise PlanningError(f"plan segment is unsafe: {step.robot_id} -> {waypoint}")
                positions[step.robot_id] = waypoint
        for robot, target in plan.targets.items():
            if hypot(positions[robot][0] - target[0], positions[robot][1] - target[1]) > 0.001:
                raise PlanningError(f"robot did not reach its assigned slot: {robot}")
        if _minimum_separation(positions) < self.separation - 1e-6:
            raise PlanningError("target formation violates separation limit")

    def _validate(self, current: dict[str, Pose], request: Request) -> None:
        if set(current) != set(ROBOT_IDS):
            raise PlanningError("fresh poses from all four robots are required")
        if request.formation not in FORMATIONS:
            raise PlanningError("unsupported formation")
        if not 0.35 <= request.spacing_m <= 2.5:
            raise PlanningError("spacing must be between 0.35 and 2.5 m")
        if request.assignment not in ("auto", "fixed"):
            raise PlanningError("assignment must be auto or fixed")
        for robot, pose in current.items():
            if not all(isfinite(v) for v in (pose.x, pose.y, pose.yaw)):
                raise PlanningError(f"invalid pose: {robot}")
            if not self._point_free((pose.x, pose.y)):
                raise PlanningError(f"robot is outside the safe map: {robot}")

    def _point_free(self, point: tuple[float, float]) -> bool:
        x, y = point
        x0, x1, y0, y1 = self.arena
        if not (x0 + self.robot_radius <= x <= x1 - self.robot_radius and y0 + self.robot_radius <= y <= y1 - self.robot_radius):
            return False
        return self.map is None or self.map.is_free(x, y, self.robot_radius)

    def _segment_free(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        positions: dict[str, tuple[float, float]],
        moving: str,
        recovery: bool = False,
    ) -> bool:
        distance = hypot(end[0] - start[0], end[1] - start[1])
        for index in range(max(1, int(distance / 0.025)) + 1):
            t = index / max(1, int(distance / 0.025))
            point = (start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1]))
            if not self._point_free(point):
                return False
        for robot, peer in positions.items():
            if robot == moving:
                continue
            initial = hypot(start[0] - peer[0], start[1] - peer[1])
            minimum = _point_segment_distance(peer, start, end)
            final = hypot(end[0] - peer[0], end[1] - peer[1])
            if recovery and initial < self.separation:
                if minimum < initial - 0.005 or final < initial + 0.005:
                    return False
            elif minimum < self.separation - 1e-6:
                return False
        return True

    def _recover_close_pairs(self, positions: dict[str, tuple[float, float]]) -> tuple[Step, ...]:
        steps = []
        for _ in range(12):
            pair = min(
                ((hypot(positions[a][0] - positions[b][0], positions[a][1] - positions[b][1]), a, b)
                 for i, a in enumerate(ROBOT_IDS) for b in ROBOT_IDS[i + 1 :]),
            )
            if pair[0] >= self.separation:
                return tuple(steps)
            _, first, second = pair
            candidates = []
            for robot in (first, second):
                start = positions[robot]
                for k in range(24):
                    angle = 2 * pi * k / 24
                    for distance in (0.10, 0.20, 0.30, 0.40, 0.50):
                        end = (start[0] + distance * cos(angle), start[1] + distance * sin(angle))
                        if not self._segment_free(start, end, positions, robot, recovery=True):
                            continue
                        other = second if robot == first else first
                        gained = hypot(end[0] - positions[other][0], end[1] - positions[other][1]) - pair[0]
                        if gained > 0.04:
                            candidates.append((min(gained, self.separation - pair[0]), -distance, robot, end))
            if not candidates:
                raise PlanningError(f"cannot safely separate {first} and {second}")
            _, _, robot, end = max(candidates)
            steps.append(Step(robot, (end,), "separate"))
            positions[robot] = end
        raise PlanningError("separation recovery did not converge")

    def _target_choices(self, current: dict[str, Pose], request: Request):
        positions = {robot: (pose.x, pose.y) for robot, pose in current.items()}
        center = request.center or (
            sum(p[0] for p in positions.values()) / 4,
            sum(p[1] for p in positions.values()) / 4,
        )
        headings = [request.heading_rad] if request.heading_rad is not None else _candidate_headings(current, request.formation)
        offsets = _offsets(request.formation, request.spacing_m)
        choices = []
        for heading in headings:
            for shift_x, shift_y in ((0, 0), (0.2, 0), (-0.2, 0), (0, 0.2), (0, -0.2), (0.4, 0), (-0.4, 0)):
                cx, cy = center[0] + shift_x, center[1] + shift_y
                slot_points = tuple((cx + cos(heading) * dx - sin(heading) * dy,
                                     cy + sin(heading) * dx + cos(heading) * dy) for dx, dy in offsets)
                if any(not self._point_free(point) for point in slot_points):
                    continue
                if _minimum_separation({str(i): p for i, p in enumerate(slot_points)}) < self.separation:
                    continue
                assignments = (tuple(range(4)),) if request.assignment == "fixed" else permutations(range(4))
                for slot_order in assignments:
                    targets = {robot: slot_points[slot_order[i]] for i, robot in enumerate(ROBOT_IDS)}
                    estimate = sum(hypot(positions[robot][0] - target[0], positions[robot][1] - target[1]) for robot, target in targets.items())
                    choices.append((targets, {robot: slot_order[i] for i, robot in enumerate(ROBOT_IDS)}, estimate))
        choices.sort(key=lambda item: item[2])
        if not choices:
            raise PlanningError("requested formation does not fit in the safe arena")
        return choices

    def _route_to_targets(self, start_positions: dict[str, tuple[float, float]], targets: dict[str, tuple[float, float]]):
        for order in permutations(ROBOT_IDS):
            positions = dict(start_positions)
            steps = []
            total = 0.0
            for robot in order:
                start, goal = positions[robot], targets[robot]
                if hypot(goal[0] - start[0], goal[1] - start[1]) < 0.02:
                    positions[robot] = goal
                    continue
                route = self._astar(start, goal, positions, robot)
                if route is None:
                    break
                steps.append(Step(robot, tuple(route), "reconfigure"))
                total += sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip((start, *route), route))
                positions[robot] = goal
            else:
                return tuple(steps), total
        return None

    def _astar(self, start: tuple[float, float], goal: tuple[float, float], positions: dict[str, tuple[float, float]], moving: str):
        if self._segment_free(start, goal, positions, moving):
            return [goal]
        x0, x1, y0, y1 = self.arena
        step = self.grid_step

        def snap(point):
            return (round((point[0] - x0) / step), round((point[1] - y0) / step))

        def world(cell):
            return (x0 + cell[0] * step, y0 + cell[1] * step)

        start_cell, goal_cell = snap(start), snap(goal)
        if not self._segment_free(start, world(start_cell), positions, moving):
            return None
        frontier = [(0.0, start_cell)]
        cost = {start_cell: 0.0}
        previous: dict[tuple[int, int], tuple[int, int]] = {}
        directions = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
        visited = 0
        while frontier and visited < 6000:
            _, cell = heappop(frontier)
            visited += 1
            if self._segment_free(world(cell), goal, positions, moving):
                path = [goal]
                while cell != start_cell:
                    path.append(world(cell))
                    cell = previous[cell]
                path.reverse()
                return _shortcut(start, path, positions, moving, self._segment_free)
            for dx, dy in directions:
                neighbor = (cell[0] + dx, cell[1] + dy)
                if not self._segment_free(world(cell), world(neighbor), positions, moving):
                    continue
                new_cost = cost[cell] + hypot(dx, dy) * step
                if new_cost >= cost.get(neighbor, float("inf")):
                    continue
                cost[neighbor] = new_cost
                previous[neighbor] = cell
                heuristic = hypot(world(neighbor)[0] - goal[0], world(neighbor)[1] - goal[1])
                heappush(frontier, (new_cost + heuristic, neighbor))
        return None


def _shortcut(start, path, positions, moving, segment_free):
    result = []
    index = 0
    current = start
    while index < len(path):
        farthest = index
        for candidate in range(len(path) - 1, index - 1, -1):
            if segment_free(current, path[candidate], positions, moving):
                farthest = candidate
                break
        result.append(path[farthest])
        current = path[farthest]
        index = farthest + 1
    return result


def _point_segment_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    t = 0.0 if length_squared == 0 else max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared))
    return hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy)


def _minimum_separation(points: dict[str, tuple[float, float]]) -> float:
    values = list(points.values())
    return min(hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(values) for b in values[i + 1 :])


def _offsets(formation: str, spacing: float) -> tuple[tuple[float, float], ...]:
    half, radius = spacing / 2, spacing / sqrt(2)
    return {
        "square": ((-half, -half), (-half, half), (half, half), (half, -half)),
        "line": ((-1.5 * spacing, 0), (-0.5 * spacing, 0), (0.5 * spacing, 0), (1.5 * spacing, 0)),
        "circle": ((-radius, 0), (0, radius), (radius, 0), (0, -radius)),
        "diamond": ((0, -radius), (-radius, 0), (0, radius), (radius, 0)),
    }[formation]


def _candidate_headings(current: dict[str, Pose], formation: str) -> list[float]:
    mean = atan2(sum(sin(p.yaw) for p in current.values()), sum(cos(p.yaw) for p in current.values()))
    if formation == "line":
        # A lateral starting row can be retained without requiring a 90 degree turn.
        return [mean, mean + pi / 2, mean - pi / 2, mean + pi]
    return [mean, mean + pi / 2, mean - pi / 2, mean + pi]
