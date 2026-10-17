"""Global laser scan matching against the exact map used by map_server."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageFilter


@dataclass(frozen=True)
class LocalizationEstimate:
    x: float
    y: float
    yaw: float
    score: float
    runner_up_score: float
    rays: int

    @property
    def confidence_ratio(self) -> float:
        return self.score / max(self.runner_up_score, 1e-6)


def map_metadata(pgm_path: str | Path) -> tuple[float, tuple[float, float]]:
    yaml_path = Path(pgm_path).with_suffix(".yaml")
    if not yaml_path.is_file():
        raise ValueError(f"map YAML missing: {yaml_path}")
    body = yaml_path.read_text(encoding="utf-8")
    resolution_match = re.search(r"^resolution:\s*([0-9.eE+-]+)", body, re.M)
    origin_match = re.search(r"^origin:\s*\[([^\]]+)\]", body, re.M)
    if not resolution_match or not origin_match:
        raise ValueError("map YAML lacks resolution or origin")
    resolution = float(resolution_match.group(1))
    values = [float(v.strip()) for v in origin_match.group(1).split(",")]
    if len(values) < 2 or not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("invalid map metadata")
    return resolution, (values[0], values[1])


def parse_scan_echo(path: str | Path) -> tuple[list[float], float, float]:
    raw = Path(path).read_text(encoding="utf-8")
    angle_min = float(re.search(r"^angle_min: ([^\n]+)", raw, re.M).group(1))
    angle_step = float(re.search(r"^angle_increment: ([^\n]+)", raw, re.M).group(1))
    block = raw.split("ranges:\n", 1)[1].split("intensities:", 1)[0]
    ranges = [float(value.replace(".nan", "nan")) for value in re.findall(r"^- ([^\n]+)$", block, re.M)]
    return ranges, angle_min, angle_step


class ScanMatcher:
    def __init__(self, pgm_path: str | Path, bounds: tuple[float, float, float, float] = (-3.3, 3.3, -3.3, 3.3)):
        resolution, origin = map_metadata(pgm_path)
        image = Image.open(pgm_path).convert("L")
        self.width, self.height = image.size
        self.field = np.asarray(
            image.point(lambda pixel: 255 if pixel < 100 else 0).filter(ImageFilter.GaussianBlur(radius=2.5)),
            dtype=np.float32,
        ) / 255.0
        self.resolution = resolution
        self.origin_x, self.origin_y = origin
        self.bounds = bounds

    def _score_grid(self, local_x, local_y, xs, ys, yaw):
        cosine, sine = math.cos(yaw), math.sin(yaw)
        ray_x = cosine * local_x - sine * local_y - 0.012 * cosine
        ray_y = sine * local_x + cosine * local_y - 0.012 * sine
        gx, gy = np.meshgrid(xs, ys, indexing="xy")
        px = np.rint((gx[..., None] + ray_x - self.origin_x) / self.resolution).astype(np.int32)
        py = np.rint(self.height - 1 - (gy[..., None] + ray_y - self.origin_y) / self.resolution).astype(np.int32)
        valid = (px >= 0) & (px < self.width) & (py >= 0) & (py < self.height)
        values = np.zeros(px.shape, dtype=np.float32)
        values[valid] = self.field[py[valid], px[valid]]
        return values.mean(axis=-1)

    def estimate(self, ranges, angle_min: float, angle_step: float) -> LocalizationEstimate:
        measured = np.asarray(ranges, dtype=np.float64)
        angles = angle_min + np.arange(len(measured)) * angle_step
        valid = np.isfinite(measured) & (measured > 0.38) & (measured < 8.0) & (np.arange(len(measured)) % 2 == 0)
        if valid.sum() < 80:
            raise ValueError("too few valid laser rays")
        local_x = measured[valid] * np.cos(angles[valid])
        local_y = measured[valid] * np.sin(angles[valid])
        x0, x1, y0, y1 = self.bounds
        xs = np.arange(x0, x1 + 0.001, 0.20)
        ys = np.arange(y0, y1 + 0.001, 0.20)
        candidates = []
        for yaw in np.arange(-math.pi, math.pi, math.radians(10)):
            scores = self._score_grid(local_x, local_y, xs, ys, yaw)
            for flat in np.argpartition(scores.ravel(), -5)[-5:]:
                row, column = np.unravel_index(flat, scores.shape)
                candidates.append((float(scores[row, column]), float(xs[column]), float(ys[row]), float(yaw)))
        candidates.sort(reverse=True)
        refined = []
        for _, x, y, yaw in candidates[:20]:
            for fine_yaw in np.arange(yaw - math.radians(8), yaw + math.radians(8.1), math.radians(2)):
                fine_xs = np.arange(x - 0.15, x + 0.151, 0.05)
                fine_ys = np.arange(y - 0.15, y + 0.151, 0.05)
                scores = self._score_grid(local_x, local_y, fine_xs, fine_ys, fine_yaw)
                row, column = np.unravel_index(np.argmax(scores), scores.shape)
                refined.append((float(scores[row, column]), float(fine_xs[column]), float(fine_ys[row]), float(fine_yaw)))
        refined.sort(reverse=True)
        distinct = []
        for item in refined:
            _, x, y, yaw = item
            if any(math.hypot(x - other[1], y - other[2]) < 0.30 and
                   abs(math.atan2(math.sin(yaw - other[3]), math.cos(yaw - other[3]))) < 0.30
                   for other in distinct):
                continue
            distinct.append(item)
            if len(distinct) >= 2:
                break
        if len(distinct) < 2:
            raise ValueError("cannot assess localization ambiguity")
        best, second = distinct
        estimate = LocalizationEstimate(best[1], best[2], best[3], best[0], second[0], int(valid.sum()))
        if estimate.score < 0.30 or estimate.confidence_ratio < 1.18:
            raise ValueError(f"ambiguous scan match: score={estimate.score:.3f}, ratio={estimate.confidence_ratio:.2f}")
        return estimate
