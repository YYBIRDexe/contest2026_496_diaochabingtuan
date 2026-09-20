from __future__ import annotations

import math


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def line_errors(
    start_x: float, start_y: float, start_yaw: float, x: float, y: float
) -> tuple[float, float]:
    dx, dy = x - start_x, y - start_y
    return (
        math.cos(start_yaw) * dx + math.sin(start_yaw) * dy,
        -math.sin(start_yaw) * dx + math.cos(start_yaw) * dy,
    )


def quaternion_yaw(z: float, w: float) -> float:
    return math.atan2(2.0 * w * z, 1.0 - 2.0 * z * z)


def validate_motion(
    start_rf: tuple[float, float, float],
    start_map: tuple[float, float, float],
    rf: tuple[float, float, float],
    mapped: tuple[float, float, float],
) -> tuple[float, float, float]:
    progress, lateral = line_errors(*start_rf, rf[0], rf[1])
    map_progress, map_lateral = line_errors(*start_map, mapped[0], mapped[1])
    if abs(normalize_angle(rf[2] - start_rf[2])) > 0.12:
        raise ValueError("RF2O heading deviated")
    if abs(normalize_angle(mapped[2] - start_map[2])) > 0.12:
        raise ValueError("SLAM heading deviated")
    if abs(progress - map_progress) > 0.12:
        raise ValueError(f"RF2O/SLAM progress disagree: {progress:.3f}/{map_progress:.3f} m")
    # A powered-off mecanum chassis slides a few centimetres while standing
    # still, so only a real wrong-way run is refused here.
    if progress < -0.15 or abs(lateral) > 0.15 or abs(map_lateral) > 0.15:
        raise ValueError(
            "reverse or lateral motion exceeded limit: "
            f"progress={progress:.3f} lateral={lateral:.3f} map_lateral={map_lateral:.3f}")
    return progress, map_progress, lateral
