import math

import pytest

from mentorpi_formation_bringup.lidar_guard import clearance_speed_scale, directional_clearance


def test_directional_clearance_ignores_invalid_and_out_of_sector_values():
    ranges = [float("inf"), 0.7, 0.4, 1.2, float("nan")]
    nearest = directional_clearance(
        ranges,
        angle_min=-math.pi / 2,
        angle_increment=math.pi / 4,
        range_min=0.1,
        range_max=10.0,
        direction_rad=0.0,
        half_angle_rad=math.pi / 4,
    )
    assert nearest == pytest.approx(0.4)


@pytest.mark.parametrize(
    ("clearance", "expected"),
    [(0.3, 0.0), (0.4, 0.0), (0.6, 0.5), (0.8, 1.0), (1.5, 1.0)],
)
def test_clearance_speed_scale(clearance, expected):
    assert clearance_speed_scale(clearance, 0.4, 0.8) == pytest.approx(expected)
