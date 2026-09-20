from pathlib import Path
import math
import re

root = Path(__file__).resolve().parent / "robot_data"
poses = {}
for index in range(1, 5):
    raw = (root / f"robot{index}_amcl_pose.txt").read_text()
    prefix = raw.split("  covariance:")[0]
    position, orientation = prefix.split("    orientation:")
    position_values = dict(re.findall(r"^      ([xyzw]): ([^\n]+)$", position, re.M))
    orientation_values = dict(re.findall(r"^      ([xyzw]): ([^\n]+)$", orientation, re.M))
    x, y = float(position_values["x"]), float(position_values["y"])
    yaw = 2 * math.atan2(float(orientation_values["z"]), float(orientation_values["w"]))
    cov = [float(v) for v in re.findall(r"^  - ([^\n]+)$", raw, re.M)]
    poses[index] = x, y, yaw
    print(f"robot{index}: x={x:.3f} y={y:.3f} yaw={yaw:.3f} covariance xyz/yaw={[cov[j] for j in (0, 7, 35)]}")

for i in range(1, 5):
    for j in range(i + 1, 5):
        a, b = poses[i], poses[j]
        print(f"distance robot{i}/robot{j}: {math.hypot(a[0]-b[0], a[1]-b[1]):.3f} m")
