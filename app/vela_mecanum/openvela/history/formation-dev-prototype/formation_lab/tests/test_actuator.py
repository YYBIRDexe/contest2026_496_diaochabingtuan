import math
import unittest

from formation_lab.agent import AgentCommand, AgentObservation
from formation_lab.mentorpi_agent import actuator_twist, world_to_body
from formation_lab.second_order import SecondOrderCommand


def second_order(accel_x=0.0, accel_y=0.0, angular_accel=0.0, safe=True, reason="tracking"):
    return SecondOrderCommand(accel_x, accel_y, angular_accel, 0.0, 0.0, 0.0, safe, reason)


class ActuatorTwistTests(unittest.TestCase):
    """The velocity-level chassis contract, including the safety returns."""

    def test_unsafe_second_order_command_stops_instead_of_coasting(self):
        own = AgentObservation("Robot01", 0.0, 0.0, 0.0, vx=0.4, vy=-0.2, wz=0.3)
        command = second_order(safe=False, reason="emergency_stop")
        self.assertEqual(actuator_twist(command, own, 0.05, 0.65, 1.5), (0.0, 0.0, 0.0))

    def test_every_unsafe_reason_stops(self):
        own = AgentObservation("Robot01", 0.0, 0.0, 0.0, vx=0.4, vy=-0.2, wz=0.3)
        for reason in (
            "emergency_stop",
            "no_mission",
            "peer_state_invalid",
            "local_separation_violation",
            "local_boundary_violation",
        ):
            with self.subTest(reason=reason):
                command = second_order(safe=False, reason=reason)
                self.assertEqual(actuator_twist(command, own, 0.05, 0.65, 1.5), (0.0, 0.0, 0.0))

    def test_unsafe_first_order_command_is_zero(self):
        own = AgentObservation("Robot01", 0.0, 0.0, 0.5, vx=1.0, vy=1.0)
        command = AgentCommand(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False, "peer_state_invalid")
        self.assertEqual(actuator_twist(command, own, 0.05, 0.65, 1.5), (0.0, 0.0, 0.0))

    def test_second_order_safe_command_integrates_acceleration(self):
        own = AgentObservation("Robot01", 0.0, 0.0, 0.0, vx=0.2, vy=0.0, wz=0.0)
        body_vx, body_vy, wz = actuator_twist(second_order(accel_x=1.0), own, 0.05, 0.65, 1.5)
        self.assertAlmostEqual(body_vx, 0.25, places=9)
        self.assertAlmostEqual(body_vy, 0.0, places=9)
        self.assertAlmostEqual(wz, 0.0, places=9)

    def test_speed_limit_is_respected(self):
        own = AgentObservation("Robot01", 0.0, 0.0, 0.0, vx=0.6, vy=0.0)
        body_vx, body_vy, _ = actuator_twist(second_order(accel_x=10.0), own, 0.05, 0.65, 1.5)
        self.assertLessEqual(math.hypot(body_vx, body_vy), 0.65 + 1e-9)
        self.assertGreater(body_vx, 0.0)

    def test_angular_acceleration_is_integrated_and_clamped(self):
        own = AgentObservation("Robot01", 0.0, 0.0, 0.0, wz=0.1)
        _, _, wz = actuator_twist(second_order(angular_accel=100.0), own, 0.05, 0.65, 1.5)
        self.assertAlmostEqual(wz, 1.5, places=9)

    def test_body_frame_rotation_matches_the_shared_convention(self):
        yaw = math.radians(35.0)
        own = AgentObservation("Robot01", 0.0, 0.0, yaw, vx=0.3, vy=0.1)
        world_vx = 0.3 + 0.2 * 0.05
        world_vy = 0.1 - 0.1 * 0.05
        expected = world_to_body(world_vx, world_vy, yaw)
        body_vx, body_vy, _ = actuator_twist(second_order(accel_x=0.2, accel_y=-0.1), own, 0.05, 0.65, 1.5)
        self.assertAlmostEqual(body_vx, expected[0], places=9)
        self.assertAlmostEqual(body_vy, expected[1], places=9)


if __name__ == "__main__":
    unittest.main()
