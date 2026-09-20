import math

import pytest

from mentorpi_formation_bringup.scan_symmetric import half_turn_scan

# The sclidar driver on the car publishes these bounds, measured on /scan_raw.
COUNT = 400
ANGLE_INCREMENT = 0.9 * math.pi / 180.0
ANGLE_MIN = 0.0
ANGLE_MAX = (COUNT - 1) * ANGLE_INCREMENT


def declared_angles(angle_min, angle_increment, count):
    return [angle_min + index * angle_increment for index in range(count)]


def rf2o_assumed_angles(angle_min, angle_max, count):
    """Beam azimuths as CLaserOdometry2D computes them, which never reads angle_min."""
    fovh = abs(angle_max - angle_min)
    return [-0.5 * fovh + index * fovh / (count - 1) for index in range(count)]


def angular_error(first, second):
    return abs(math.atan2(math.sin(first - second), math.cos(first - second)))


def beam_set(angles, ranges):
    # Wrap into [0, 2*pi): wrapping into (-pi, pi] makes the beam at exactly
    # half a turn land on +pi or -pi depending on the sign of its sine.
    wrapped = [angle % (2.0 * math.pi) for angle in angles]
    return sorted((round(angle, 9), value) for angle, value in zip(wrapped, ranges))


def sample_ranges():
    return [float((index * 7) % 41) + 0.5 for index in range(COUNT)]


def test_published_scan_violates_the_range_flow_geometry():
    declared = declared_angles(ANGLE_MIN, ANGLE_INCREMENT, COUNT)
    assumed = rf2o_assumed_angles(ANGLE_MIN, ANGLE_MAX, COUNT)
    errors = [angular_error(a, b) for a, b in zip(assumed, declared)]
    # Every beam is about half a turn away from where rf2o looks for it, which
    # is what negated its linear velocity.
    assert min(errors) > 3.0


def test_half_turn_keeps_the_measured_points():
    ranges = sample_ranges()
    rotated, _, angle_min, angle_max = half_turn_scan(ranges, [], ANGLE_MIN, ANGLE_MAX)
    assert rotated == ranges[COUNT // 2 :] + ranges[: COUNT // 2]
    assert angle_max - angle_min == pytest.approx(ANGLE_MAX - ANGLE_MIN)
    assert beam_set(declared_angles(ANGLE_MIN, ANGLE_INCREMENT, COUNT), ranges) == beam_set(
        declared_angles(angle_min, ANGLE_INCREMENT, COUNT), rotated
    )


def test_half_turn_restores_the_range_flow_geometry():
    _, _, angle_min, angle_max = half_turn_scan(sample_ranges(), [], ANGLE_MIN, ANGLE_MAX)
    assert angle_min == pytest.approx(-math.pi)
    assumed = rf2o_assumed_angles(angle_min, angle_max, COUNT)
    declared = declared_angles(angle_min, ANGLE_INCREMENT, COUNT)
    errors = [angular_error(a, b) for a, b in zip(assumed, declared)]
    # The 0.45 deg residual is rf2o placing beam 0 at -fovh/2 instead of -pi.
    assert max(errors) < math.radians(0.5)


def test_intensities_follow_the_beams():
    intensities = [float(index) for index in range(COUNT)]
    rotated_ranges, rotated_intensities, _, _ = half_turn_scan(
        sample_ranges(), intensities, ANGLE_MIN, ANGLE_MAX
    )
    assert rotated_intensities == intensities[COUNT // 2 :] + intensities[: COUNT // 2]
    assert len(rotated_ranges) == len(rotated_intensities) == COUNT


@pytest.mark.parametrize("count", [1, 3, 399])
def test_odd_or_tiny_scans_are_rejected(count):
    with pytest.raises(ValueError):
        half_turn_scan([1.0] * count, [], ANGLE_MIN, ANGLE_MAX)
