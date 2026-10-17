"""Simulate one closed formation lap on the saved occupancy map."""

from __future__ import annotations

import argparse
import json
from math import hypot
from pathlib import Path

from formation_lap import build_lap_plan
from formation_planner import FormationPlanner, OccupancyGrid, ROBOT_IDS
from scan_localizer import map_metadata


def _advance(route, state, distance):
    index, progress = state
    while index < len(route) - 1:
        start, end = route[index], route[index + 1]
        length = hypot(end[0] - start[0], end[1] - start[1])
        remaining = length * (1.0 - progress)
        if distance < remaining:
            return index, progress + distance / length
        distance -= remaining
        index += 1
        progress = 0.0
    return index, 1.0


def _point(route, state):
    index, progress = state
    if index >= len(route) - 1:
        return route[-1]
    start, end = route[index], route[index + 1]
    return (start[0] + progress * (end[0] - start[0]), start[1] + progress * (end[1] - start[1]))


def run(data_dir: Path, formation: str, spacing: float, bounds: tuple[float, float, float, float], speed: float):
    map_path = data_dir / "classroom.pgm"
    resolution, origin = map_metadata(map_path)
    grid = OccupancyGrid(map_path, resolution, origin)
    planner = FormationPlanner(arena=(-3.3, 3.3, -3.3, 3.3), map_grid=grid)
    plan = build_lap_plan(planner, bounds, formation, spacing)
    states = {robot: (0, 0.0) for robot in ROBOT_IDS}
    elapsed = 0.0
    minimum_gap = float("inf")
    dt = 0.02
    while elapsed < 300.0:
        points = {robot: _point(plan.robot_routes[robot], states[robot]) for robot in ROBOT_IDS}
        for index, first in enumerate(ROBOT_IDS):
            for second in ROBOT_IDS[index + 1:]:
                minimum_gap = min(minimum_gap, hypot(points[first][0] - points[second][0], points[first][1] - points[second][1]))
        if all(index >= len(plan.robot_routes[robot]) - 1 for robot, (index, _progress) in states.items()):
            break
        for robot in ROBOT_IDS:
            states[robot] = _advance(plan.robot_routes[robot], states[robot], speed * dt)
        elapsed += dt
    else:
        raise RuntimeError("lap simulation exceeded 300 seconds")
    return {
        "formation": formation,
        "spacing_m": spacing,
        "bounds": bounds,
        "speed_mps": speed,
        "elapsed_s": round(elapsed, 3),
        "distance_m": round(sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(plan.center_route, plan.center_route[1:])), 3),
        "minimum_gap_m": round(minimum_gap, 3),
        "route_points": {robot: len(plan.robot_routes[robot]) for robot in ROBOT_IDS},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--formation", choices=("square", "line", "circle", "diamond", "triangle"), default="triangle")
    parser.add_argument("--spacing", type=float, default=0.5)
    parser.add_argument("--speed", type=float, default=0.875)
    parser.add_argument("--bounds", type=float, nargs=4, default=(-2.6, 2.6, -1.8, 2.6), metavar=("MIN_X", "MAX_X", "MIN_Y", "MAX_Y"))
    args = parser.parse_args()
    data_dir = Path(__file__).resolve().parents[1] / "evidence" / "current_map"
    print(json.dumps(run(data_dir, args.formation, args.spacing, tuple(args.bounds), args.speed), indent=2))


if __name__ == "__main__":
    main()
