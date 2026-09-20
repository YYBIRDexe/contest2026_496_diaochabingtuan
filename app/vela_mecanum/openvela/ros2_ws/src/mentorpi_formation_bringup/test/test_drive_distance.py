import math

import pytest

from mentorpi_formation_bringup.motion_math import line_errors, normalize_angle, validate_motion


def test_line_errors_axis_aligned():
    progress, lateral = line_errors(1.0, 2.0, 0.0, 4.0, 2.2)
    assert math.isclose(progress, 3.0)
    assert math.isclose(lateral, 0.2)


def test_line_errors_rotated():
    progress, lateral = line_errors(0.0, 0.0, math.pi / 2.0, 0.1, 3.0)
    assert math.isclose(progress, 3.0, abs_tol=1e-9)
    assert math.isclose(lateral, -0.1, abs_tol=1e-9)


def test_normalize_angle_wraps():
    assert math.isclose(normalize_angle(3.0 * math.pi), math.pi, abs_tol=1e-9)


def test_measured_and_map_agree():
    assert validate_motion((0, 0, 0), (1, 2, 0), (0.3, 0.01, 0.01), (1.32, 2.0, 0.01))[0] == 0.3


def test_fake_command_progress_is_refused():
    with pytest.raises(ValueError, match="disagree"):
        validate_motion((0, 0, 0), (0, 0, 0), (0.0, 0.0, 0.0), (0.50, 0.0, 0.0))


def test_sixty_degree_rotation_is_refused():
    with pytest.raises(ValueError, match="heading"):
        validate_motion((0, 0, 0), (0, 0, 0), (0.0, 0.0, math.pi / 3), (0.0, 0.0, 0.0))
