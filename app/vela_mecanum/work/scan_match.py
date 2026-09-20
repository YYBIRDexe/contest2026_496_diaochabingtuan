from pathlib import Path
import math
import re

import numpy as np
from PIL import Image, ImageFilter, ImageDraw


ROOT = Path(__file__).resolve().parent / "robot_data"
resolution = 0.05
origin_x, origin_y = -10.2, -5.04
image = Image.open(ROOT / "classroom.pgm").convert("L")
width, height = image.size
occ = image.point(lambda p: 255 if p < 100 else 0)
field = np.asarray(occ.filter(ImageFilter.GaussianBlur(radius=2.5)), dtype=np.float32) / 255.0
overlay = image.convert("RGB").resize((width * 3, height * 3))
draw = ImageDraw.Draw(overlay)
colors = ("#d62828", "#0055dd", "#23a220", "#a02db3")


def scan(index):
    text = (ROOT / f"robot{index}_scan_raw.txt").read_text()
    angle_min = float(re.search(r"^angle_min: ([^\n]+)", text, re.M).group(1))
    step = float(re.search(r"^angle_increment: ([^\n]+)", text, re.M).group(1))
    block = text.split("ranges:\n", 1)[1].split("intensities:", 1)[0]
    ranges = np.array([float(v.replace(".nan", "nan")) for v in re.findall(r"^- ([^\n]+)$", block, re.M)])
    angles = angle_min + np.arange(len(ranges)) * step
    mask = np.isfinite(ranges) & (ranges > 0.38) & (ranges < 8.0)
    # Subsample evenly to keep the grid search quick.
    mask &= (np.arange(len(ranges)) % 2 == 0)
    return ranges[mask] * np.cos(angles[mask]), ranges[mask] * np.sin(angles[mask])


def score_grid(local_x, local_y, xs, ys, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    ray_x = c * local_x - s * local_y - 0.012 * c
    ray_y = s * local_x + c * local_y - 0.012 * s
    gx, gy = np.meshgrid(xs, ys, indexing="xy")
    px = np.rint((gx[..., None] + ray_x - origin_x) / resolution).astype(np.int32)
    py = np.rint(height - 1 - (gy[..., None] + ray_y - origin_y) / resolution).astype(np.int32)
    valid = (px >= 0) & (px < width) & (py >= 0) & (py < height)
    result = np.zeros(px.shape, dtype=np.float32)
    result[valid] = field[py[valid], px[valid]]
    return result.mean(axis=-1)


for index in range(1, 5):
    local_x, local_y = scan(index)
    xs = np.arange(-3.0, 3.001, 0.20)
    ys = np.arange(-3.0, 3.001, 0.20)
    candidates = []
    for yaw in np.arange(-math.pi, math.pi, math.radians(10)):
        scores = score_grid(local_x, local_y, xs, ys, yaw)
        for flat_index in np.argpartition(scores.ravel(), -3)[-3:]:
            iy, ix = np.unravel_index(flat_index, scores.shape)
            candidates.append((float(scores[iy, ix]), xs[ix], ys[iy], yaw))
    candidates.sort(reverse=True)
    fine = []
    for _, x, y, yaw in candidates[:10]:
        for fine_yaw in np.arange(yaw - math.radians(8), yaw + math.radians(8.1), math.radians(2)):
            fine_xs = np.arange(x - 0.15, x + 0.151, 0.05)
            fine_ys = np.arange(y - 0.15, y + 0.151, 0.05)
            scores = score_grid(local_x, local_y, fine_xs, fine_ys, fine_yaw)
            iy, ix = np.unravel_index(np.argmax(scores), scores.shape)
            fine.append((float(scores[iy, ix]), fine_xs[ix], fine_ys[iy], fine_yaw))
    fine.sort(reverse=True)
    raw_pose = (ROOT / f"robot{index}_amcl_pose.txt").read_text().split("  covariance:")[0]
    position, orientation = raw_pose.split("    orientation:")
    pv = dict(re.findall(r"^      ([xyzw]): ([^\n]+)$", position, re.M))
    ov = dict(re.findall(r"^      ([xyzw]): ([^\n]+)$", orientation, re.M))
    amcl_x, amcl_y = float(pv["x"]), float(pv["y"])
    amcl_yaw = 2 * math.atan2(float(ov["z"]), float(ov["w"]))
    amcl_score = score_grid(local_x, local_y, np.array([amcl_x]), np.array([amcl_y]), amcl_yaw)[0, 0]
    print(f"robot{index} rays={len(local_x)}")
    print(f"  amcl score={amcl_score:.3f} x={amcl_x:.2f} y={amcl_y:.2f} yaw={amcl_yaw:.2f}")
    for candidate in fine[:1]:
        print("  score=%.3f x=%.2f y=%.2f yaw=%.2f" % candidate)
    _, x, y, yaw = fine[0]
    c, s = math.cos(yaw), math.sin(yaw)
    ex = x + c * local_x - s * local_y - 0.012 * c
    ey = y + s * local_x + c * local_y - 0.012 * s
    for px, py in zip(ex, ey):
        ix = round(3 * (px - origin_x) / resolution)
        iy = round(3 * (height - 1 - (py - origin_y) / resolution))
        if 0 <= ix < width * 3 and 0 <= iy < height * 3:
            draw.ellipse((ix-1, iy-1, ix+1, iy+1), fill=colors[index-1])
    ix = round(3 * (x - origin_x) / resolution)
    iy = round(3 * (height - 1 - (y - origin_y) / resolution))
    draw.ellipse((ix-6, iy-6, ix+6, iy+6), outline=colors[index-1], width=2)
    draw.text((ix+7, iy+7), str(index), fill=colors[index-1])

overlay.save(ROOT / "scan_overlay.png")
