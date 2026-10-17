"""Print a formation route from a saved JSON pose snapshot; no robot I/O."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from formation_planner import FORMATIONS, FormationPlanner, OccupancyGrid, Pose, Request


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("formation", choices=FORMATIONS)
    parser.add_argument("--spacing", type=float, default=0.5, help="metres")
    parser.add_argument("--state", type=Path, default=Path(__file__).with_name("example_state.json"))
    parser.add_argument("--output", type=Path, help="optional JSON plan file")
    args = parser.parse_args()
    poses = {robot: Pose(**data) for robot, data in json.loads(args.state.read_text(encoding="utf-8")).items()}
    grid = OccupancyGrid(ROOT / "evidence" / "classroom.pgm", 0.05, (-10.2, -5.04))
    plan = FormationPlanner(map_grid=grid).plan(poses, Request(args.formation, args.spacing, assignment="auto"))
    result = json.dumps(asdict(plan), indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()
