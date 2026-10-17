from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "outputs" / "formation-kit" / "payload" / "planner"
sys.path.insert(0, str(PLANNER))

from formation_planner import FormationPlanner, OccupancyGrid, Pose, Request
from scan_localizer import map_metadata
from synchronized_formation import build_synchronized_plan


initial = {
    "robot1": Pose(-2.33, -0.73, 0.0),
    "robot2": Pose(-2.60, 0.11, 0.0),
    "robot3": Pose(-2.75, -0.46, 0.0),
    "robot4": Pose(-2.28, -0.18, 0.0),
}
map_path = ROOT / "outputs" / "formation-kit" / "payload" / "evidence" / "current_map" / "classroom.pgm"
resolution, origin = map_metadata(map_path)
planner = FormationPlanner(
    arena=(-3.3, 3.3, -3.3, 3.3),
    map_grid=OccupancyGrid(map_path, resolution, origin),
)
plan = build_synchronized_plan(planner, initial, Request("line", 0.5))
print("phase", plan.phase)
for robot, target in plan.targets.items():
    print(robot, f"{target[0]:.6f}", f"{target[1]:.6f}")
print("minimum_target_gap", f"{plan.final_separation_m:.6f}")
