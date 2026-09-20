from __future__ import annotations

import math
from collections.abc import Sequence


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def directional_clearance(
    ranges: Sequence[float],
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    direction_rad: float,
    half_angle_rad: float,
) -> float | None:
    """Return the nearest valid lidar range in a body-relative sector."""
    nearest: float | None = None
    for index, raw_range in enumerate(ranges):
        distance = float(raw_range)
        if not math.isfinite(distance) or distance < range_min or distance > range_max:
            continue
        ray_angle = angle_min + index * angle_increment
        if abs(normalize_angle(ray_angle - direction_rad)) > half_angle_rad:
            continue
        nearest = distance if nearest is None else min(nearest, distance)
    return nearest


def clearance_speed_scale(clearance_m: float, stop_m: float, slow_m: float) -> float:
    if stop_m <= 0.0 or slow_m <= stop_m:
        raise ValueError("require 0 < stop_m < slow_m")
    if clearance_m <= stop_m:
        return 0.0
    if clearance_m >= slow_m:
        return 1.0
    return (clearance_m - stop_m) / (slow_m - stop_m)
