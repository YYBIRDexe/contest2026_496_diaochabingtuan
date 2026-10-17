import math

import pytest

from mentorpi_formation_bringup.orbit_math import (
    orbit_command,
    orbits_completed,
    tracked_obstacle,
    unwrap_yaw_step,
)


def test_tracked_obstacle_takes_nearest_valid_return_inside_the_sector():
    increment = math.radians(10.0)
    ranges = [float("inf"), 1.4, 0.9, 1.1, float("nan"), 0.5, 0.4]
    contact = tracked_obstacle(ranges, 0.0, increment, 0.1, 10.0, 0.0, math.radians(30.0))
    assert contact is not None
    assert contact[0] == pytest.approx(0.9)
    assert contact[1] == pytest.approx(math.radians(20.0))


def test_tracked_obstacle_respects_the_declared_range_window():
    increment = math.radians(10.0)
    ranges = [0.05, 12.0, 0.7]
    contact = tracked_obstacle(ranges, 0.0, increment, 0.1, 10.0, 0.0, math.radians(30.0))
    assert contact is not None
    assert contact[0] == pytest.approx(0.7)


def test_tracked_obstacle_returns_none_for_an_empty_sector():
    contact = tracked_obstacle(
        [1.0], 0.0, math.radians(10.0), 0.1, 10.0, math.pi, math.radians(30.0)
    )
    assert contact is None


def test_association_ignores_a_nearer_intruder_in_the_same_sector():
    increment = math.radians(10.0)
    ranges = [1.05, 0.35, 1.02]
    contact = tracked_obstacle(
        ranges,
        0.0,
        increment,
        0.1,
        10.0,
        0.0,
        math.radians(30.0),
        reference_range_m=1.0,
        association_window_m=0.3,
    )
    assert contact is not None
    assert contact[0] == pytest.approx(1.02)
    assert contact[1] == pytest.approx(math.radians(20.0))


def test_association_reports_a_lost_contact():
    contact = tracked_obstacle(
        [0.35],
        0.0,
        math.radians(10.0),
        0.1,
        10.0,
        0.0,
        math.radians(30.0),
        reference_range_m=1.0,
        association_window_m=0.3,
    )
    assert contact is None


def tangential_command(bearing_deg, heading_error=0.0, measured_range=0.7):
    return orbit_command(
        measured_range,
        math.radians(bearing_deg),
        0.7,
        0.0,
        0.08,
        0.05,
        0.4,
        mode="tangential",
        heading_error_rad=heading_error,
    )


@pytest.mark.parametrize(
    ("bearing_deg", "expected"),
    [
        (90.0, (0.08, 0.0)),
        (0.0, (0.0, -0.08)),
        (180.0, (0.0, 0.08)),
        (-90.0, (-0.08, 0.0)),
    ],
)
def test_tangential_mode_strafes_around_a_fixed_heading(bearing_deg, expected):
    # Left contact: drive forward. Contact ahead: strafe right. Contact behind:
    # strafe left. Right contact: reverse. The heading never has to turn.
    vx, vy, wz = tangential_command(bearing_deg)
    assert vx == pytest.approx(expected[0], abs=1e-9)
    assert vy == pytest.approx(expected[1], abs=1e-9)
    assert wz == pytest.approx(0.0)


def test_tangential_mode_keeps_the_speed_vector_tangential_all_the_way_round():
    for bearing_deg in range(0, 360, 15):
        vx, vy, _ = tangential_command(bearing_deg)
        assert math.hypot(vx, vy) == pytest.approx(0.08)


def test_tangential_mode_holds_the_heading_and_respects_the_yaw_cap():
    assert tangential_command(90.0, heading_error=0.1)[2] == pytest.approx(-0.08)
    assert tangential_command(90.0, heading_error=-0.1)[2] == pytest.approx(0.08)
    assert tangential_command(90.0, heading_error=math.pi / 2)[2] == pytest.approx(-0.4)


def test_tangential_mode_still_corrects_the_range():
    vx, vy, _ = tangential_command(90.0, measured_range=1.1)
    assert vx > 0.0
    assert vy > 0.0
    assert math.hypot(vx, vy) == pytest.approx(0.08)


def test_orbit_command_holds_the_nominal_circle():
    vx, vy, wz = orbit_command(0.7, math.pi / 2, 0.7, math.pi / 2, 0.08, 0.05, 0.4)
    assert vx == pytest.approx(0.08)
    assert vy == pytest.approx(0.0)
    assert wz == pytest.approx(0.08 / 0.7)


def test_orbit_command_orbits_clockwise_around_a_contact_on_the_right():
    vx, vy, wz = orbit_command(0.7, -math.pi / 2, 0.7, -math.pi / 2, 0.08, 0.05, 0.4)
    assert vx == pytest.approx(0.08)
    assert vy == pytest.approx(0.0)
    assert wz == pytest.approx(-0.08 / 0.7)


def test_orbit_command_approaches_a_distant_contact_on_the_left():
    vx, vy, _ = orbit_command(1.1, math.pi / 2, 0.7, math.pi / 2, 0.08, 0.05, 0.4)
    assert vx > 0.0
    assert vy > 0.0
    assert math.hypot(vx, vy) == pytest.approx(0.08)


def test_orbit_command_caps_the_linear_speed_everywhere():
    for measured_range in (0.4, 0.7, 1.0, 1.4, 2.0):
        for bearing_deg in range(0, 181, 15):
            vx, vy, wz = orbit_command(
                measured_range,
                math.radians(bearing_deg),
                0.7,
                math.pi / 2,
                0.08,
                0.05,
                0.4,
            )
            assert math.hypot(vx, vy) <= 0.08 + 1e-12
            assert abs(wz) <= 0.4 + 1e-12
            assert vx >= 0.0


def test_orbit_command_backs_off_a_contact_that_is_too_close():
    vx, vy, _ = orbit_command(0.5, math.pi / 2, 0.7, math.pi / 2, 0.08, 0.05, 0.4)
    assert vy < 0.0
    assert vx > 0.0
    assert math.hypot(vx, vy) == pytest.approx(0.08)


def test_orbit_command_steers_back_towards_the_nominal_bearing():
    _, _, too_far_left = orbit_command(
        0.7, math.radians(120.0), 0.7, math.pi / 2, 0.08, 0.05, 0.4
    )
    _, _, too_far_right = orbit_command(
        0.7, math.radians(60.0), 0.7, math.pi / 2, 0.08, 0.05, 0.4
    )
    assert too_far_left == pytest.approx(0.4)
    assert too_far_right == pytest.approx(-0.4)


def test_orbit_command_never_asks_for_reverse():
    vx, _, _ = orbit_command(1.3, math.pi, 0.7, math.pi / 2, 0.05, 0.05, 0.4)
    assert vx == pytest.approx(0.0)


def test_unwrap_yaw_step_crosses_the_pi_wrap():
    turned = unwrap_yaw_step(0.0, math.radians(179.0), math.radians(-179.0))
    assert turned == pytest.approx(math.radians(2.0))


def test_unwrap_yaw_step_accumulates_a_full_turn():
    turned = 0.0
    previous = 0.0
    for _ in range(36):
        current = previous + math.radians(10.0)
        turned = unwrap_yaw_step(turned, math.atan2(math.sin(previous), math.cos(previous)),
                                 math.atan2(math.sin(current), math.cos(current)))
        previous = current
    assert orbits_completed(turned) == pytest.approx(1.0)


def test_orbits_completed_counts_half_a_revolution_either_way():
    assert orbits_completed(-math.pi) == pytest.approx(0.5)
    assert orbits_completed(2.0 * math.pi) == pytest.approx(1.0)


def test_orbital_angle_ignores_a_pure_re_orientation():
    yaw = 0.0
    bearing = math.radians(53.0)
    previous = yaw + bearing
    total = 0.0
    for _ in range(12):
        yaw -= math.radians(3.0)
        bearing += math.radians(3.0)
        angle = yaw + bearing
        total = unwrap_yaw_step(total, previous, angle)
        previous = angle
    assert orbits_completed(total) == pytest.approx(0.0)


def test_orbital_angle_counts_one_lap_of_a_held_contact():
    previous = math.radians(90.0)
    total = 0.0
    for _ in range(36):
        angle = previous + math.radians(10.0)
        total = unwrap_yaw_step(total, previous, angle)
        previous = angle
    assert orbits_completed(total) == pytest.approx(1.0)
