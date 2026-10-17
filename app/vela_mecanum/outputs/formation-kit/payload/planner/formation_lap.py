"""Generate reusable closed lap routes for a four-car formation."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from math import atan2, cos, hypot, sin

from formation_planner import FormationPlanner, PlanningError, ROBOT_IDS, _offsets


@dataclass(frozen=True)
class LapPlan:
    center_route: tuple[tuple[float, float], ...]
    robot_routes: dict[str, tuple[tuple[float, float], ...]]
    formation: str
    spacing_m: float
    laps: int
    bounds: tuple[float, float, float, float]


def _rotate(offset: tuple[float, float], heading: float) -> tuple[float, float]:
    x, y = offset
    return (cos(heading) * x - sin(heading) * y, sin(heading) * x + cos(heading) * y)


def _segment_length(start: tuple[float, float], end: tuple[float, float]) -> float:
    return hypot(end[0] - start[0], end[1] - start[1])


def build_lap_plan(
    planner: FormationPlanner,
    bounds: tuple[float, float, float, float],
    formation: str,
    spacing_m: float,
    laps: int = 1,
    margin_m: float = 0.35,
    start_center: tuple[float, float] | None = None,
    current: dict[str, tuple[float, float]] | None = None,
) -> LapPlan:
    if laps < 1:
        raise PlanningError("laps must be positive")
    if margin_m < planner.robot_radius:
        raise PlanningError("lap margin is smaller than robot radius")
    min_x, max_x, min_y, max_y = bounds
    if not (min_x < max_x and min_y < max_y):
        raise PlanningError("invalid lap bounds")
    offsets = _offsets(formation, spacing_m)
    inset = margin_m + max(hypot(x, y) for x, y in offsets)
    if max_x - min_x <= 2 * inset or max_y - min_y <= 2 * inset:
        raise PlanningError("lap bounds are too small for the requested formation")
    left, right = min_x + inset, max_x - inset
    bottom, top = min_y + inset, max_y - inset
    corners = ((left, bottom), (right, bottom), (right, top), (left, top))
    if start_center is not None:
        start_index = min(range(len(corners)), key=lambda index: _segment_length(corners[index], start_center))
        corners = corners[start_index:] + corners[:start_index]
    center_route = corners * laps + (corners[0],)
    if current is not None:
        current_center = (
            sum(current[robot][0] for robot in ROBOT_IDS) / len(ROBOT_IDS),
            sum(current[robot][1] for robot in ROBOT_IDS) / len(ROBOT_IDS),
        )
        center_route = (current_center, *center_route)
    heading = atan2(center_route[1][1] - center_route[0][1], center_route[1][0] - center_route[0][0])
    assignment = tuple(range(len(ROBOT_IDS)))
    if current is not None:
        if set(current) != set(ROBOT_IDS):
            raise PlanningError("current positions for all four robots are required")
        anchor = center_route[1]
        targets = tuple(
            (anchor[0] + _rotate(offset, heading)[0],
             anchor[1] + _rotate(offset, heading)[1])
            for offset in offsets
        )
        assignment = min(
            permutations(range(len(ROBOT_IDS))),
            key=lambda order: sum(
                _segment_length(current[robot], targets[order[index]])
                for index, robot in enumerate(ROBOT_IDS)
            ),
        )
    robot_routes: dict[str, tuple[tuple[float, float], ...]] = {}
    for index, robot in enumerate(ROBOT_IDS):
        offset = offsets[assignment[index]]
        fixed_offset = _rotate(offset, heading)
        route: list[tuple[float, float]] = []
        for corner_index, center in enumerate(center_route):
            point = (center[0] + fixed_offset[0], center[1] + fixed_offset[1])
            if planner._point_free(point):
                route.append(point)
            else:
                raise PlanningError(f"lap route leaves free map: {robot}")
        robot_routes[robot] = tuple(route)
    if current is not None:
        starts = dict(current)
        ends = {robot: robot_routes[robot][0] for robot in ROBOT_IDS}
        for robot in ROBOT_IDS:
            if not planner._segment_free(starts[robot], ends[robot], starts, robot):
                raise PlanningError(f"lap join route is unsafe: {robot}")
        if _synchronized_gap(starts, ends) < planner.separation:
            raise PlanningError("lap join route violates separation")
    for robot in ROBOT_IDS:
        points = robot_routes[robot]
        for start, end in zip(points, points[1:]):
            if not planner._segment_free(start, end, {}, robot):
                raise PlanningError(f"lap segment leaves free map: {robot}")
    for first_index, first in enumerate(ROBOT_IDS):
        for second in ROBOT_IDS[first_index + 1:]:
            for first_point, second_point in zip(robot_routes[first], robot_routes[second]):
                if hypot(first_point[0] - second_point[0], first_point[1] - second_point[1]) < planner.separation:
                    raise PlanningError(f"lap formation violates separation: {first}/{second}")
    return LapPlan(center_route, robot_routes, formation, spacing_m, laps, bounds)


def _synchronized_gap(
    starts: dict[str, tuple[float, float]],
    ends: dict[str, tuple[float, float]],
    samples: int = 20,
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
                minimum = min(
                    minimum,
                    hypot(first_point[0] - second_point[0], first_point[1] - second_point[1]),
                )
    return minimum
