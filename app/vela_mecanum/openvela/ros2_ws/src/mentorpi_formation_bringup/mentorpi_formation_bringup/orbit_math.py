"""Geometry and control laws for the lidar-hold orbit mission.

The mission follows a single lidar contact, holds that contact at a fixed range
and bearing and keeps driving forward, which traces a circle around it.  The
maths lives here, away from ROS, so the same laws can be unit tested on their
own.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def tracked_obstacle(
    ranges: Sequence[float],
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    preferred_bearing_rad: float,
    half_angle_rad: float,
    reference_range_m: float | None = None,
    association_window_m: float = 0.6,
) -> tuple[float, float] | None:
    """Return ``(range, bearing)`` of the contact this mission follows.

    Without ``reference_range_m`` the nearest valid return inside the sector
    wins, which is how the obstacle is acquired.  With a reference, only returns
    within ``association_window_m`` of the range already being followed compete,
    so a nearer wall sliding into the same sector cannot silently take over the
    orbit; when nothing matches the contact counts as lost.
    """
    best: tuple[float, float] | None = None
    best_key: float | None = None
    for index, raw_range in enumerate(ranges):
        distance = float(raw_range)
        if not math.isfinite(distance) or distance < range_min or distance > range_max:
            continue
        bearing = angle_min + index * angle_increment
        if abs(normalize_angle(bearing - preferred_bearing_rad)) > half_angle_rad:
            continue
        if reference_range_m is None:
            key = distance
        else:
            key = abs(distance - reference_range_m)
            if key > association_window_m:
                continue
        if best_key is None or key < best_key:
            best_key = key
            best = (distance, normalize_angle(bearing))
    return best


def orbit_command(
    measured_range_m: float,
    measured_bearing_rad: float,
    target_range_m: float,
    target_bearing_rad: float,
    speed_mps: float,
    max_lateral_mps: float,
    max_yaw_rate_radps: float,
    range_gain: float = 0.5,
    bearing_gain: float = 1.2,
    mode: str = "rotating",
    heading_error_rad: float = 0.0,
    heading_gain: float = 0.8,
) -> tuple[float, float, float]:
    """Body velocity ``(x, y, yaw)`` that holds the contact at range and bearing.

    The radial term corrects the radius along the line of sight in both modes.
    ``rotating`` holds the contact on its nominal side and turns the heading, so
    the forward term traces the circle.  ``tangential`` keeps the heading put
    and traces the circle with the translation alone, which is what the mecanum
    chassis is for: the velocity is purely tangential, ``speed * (sin, -cos)``
    of the contact bearing, so the contact sweeps the whole scan while the car
    never turns.  ``heading_error_rad`` is the yaw drift to correct in that mode.

    ``max_lateral_mps`` bounds the radial correction only.  In tangential mode
    the lateral component carries the orbit itself and is therefore bounded by
    ``speed_mps`` instead.
    """
    range_error = measured_range_m - target_range_m
    radial_speed = max(-max_lateral_mps, min(max_lateral_mps, range_gain * range_error))
    if mode == "tangential":
        forward = speed_mps * math.sin(measured_bearing_rad)
        lateral = -speed_mps * math.cos(measured_bearing_rad)
    elif mode == "rotating":
        forward = speed_mps
        lateral = 0.0
    else:
        raise ValueError(f"unsupported orbit mode: {mode}")
    forward += radial_speed * math.cos(measured_bearing_rad)
    lateral += radial_speed * math.sin(measured_bearing_rad)
    # The radial term adds to the forward term, so the cap has to apply to the
    # linear velocity as a whole: the chassis must never exceed the commanded
    # speed no matter where the contact sits.
    linear = math.hypot(forward, lateral)
    if linear > speed_mps:
        forward *= speed_mps / linear
        lateral *= speed_mps / linear
    if mode == "tangential":
        yaw = -heading_gain * normalize_angle(heading_error_rad)
    else:
        # Which way the circle turns is set by the side the contact is held on: a
        # contact held on the left turns the heading counter-clockwise. Taking
        # the sign from the target keeps it fixed for a whole run.
        side = math.copysign(1.0, math.sin(target_bearing_rad))
        feed_forward = side * speed_mps / max(measured_range_m, 1e-3)
        yaw = feed_forward + bearing_gain * normalize_angle(
            measured_bearing_rad - target_bearing_rad
        )
    return (
        max(0.0, forward) if mode == "rotating" else forward,
        max(-speed_mps, min(speed_mps, lateral)),
        max(-max_yaw_rate_radps, min(max_yaw_rate_radps, yaw)),
    )


def unwrap_yaw_step(accumulated_rad: float, previous_yaw_rad: float, yaw_rad: float) -> float:
    """Accumulate the signed turn between two wrapped yaw readings."""
    return accumulated_rad + normalize_angle(yaw_rad - previous_yaw_rad)


def orbits_completed(accumulated_rad: float) -> float:
    """Turns swept so far, where one full orbit is one revolution of heading."""
    return abs(accumulated_rad) / (2.0 * math.pi)
