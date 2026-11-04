import unittest

from cloud_agent.registry import Registry

from tests.helpers import ROOT, fixed_now, make_registry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = make_registry()

    def test_valid_mission_has_registry_provenance(self):
        result = self.registry.validate_mission(
            {"route_id": "route-a", "checks": ["aisle_clear", "extinguisher_present"]}
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["clarification_required"])
        self.assertEqual(result["route"]["id"], "route-a")
        self.assertEqual(len(result["checks"]), 2)
        self.assertFalse(result["registry"]["is_live"])
        self.assertEqual(result["registry"]["routes_source"], "test_fixture")

    def test_unknown_route_requires_clarification(self):
        result = self.registry.validate_mission(
            {"route_id": "route-z", "checks": ["aisle_clear"]}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "unknown_route")
        self.assertTrue(result["clarification_required"])
        self.assertIn("route-a", result["clarification"])
        self.assertIn("known_routes", result["error"]["details"])

    def test_unknown_check_is_rejected(self):
        result = self.registry.validate_mission(
            {"route_id": "route-a", "checks": ["not_a_check"]}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "unknown_check")
        self.assertTrue(result["clarification_required"])
        self.assertIn("allowed_checks", result["error"]["details"])

    def test_disabled_route_is_rejected(self):
        result = self.registry.validate_mission(
            {"route_id": "route-d", "checks": ["barrier_intact"]}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "route_disabled")

    def test_disabled_robot_is_rejected(self):
        result = self.registry.validate_mission(
            {
                "route_id": "route-a",
                "checks": ["aisle_clear"],
                "robot_id": "mentorpi-04",
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "robot_unavailable")

    def test_robot_without_inspection_capability_is_rejected(self):
        for robot in self.registry.robots:
            if robot["id"] == "mentorpi-03":
                robot["capabilities"] = ["camera"]
        result = self.registry.validate_mission(
            {
                "route_id": "route-a",
                "checks": ["aisle_clear"],
                "robot_id": "mentorpi-03",
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "robot_capability_missing")

    def test_robot_without_navigation_capability_is_rejected(self):
        result = self.registry.validate_mission(
            {
                "route_id": "route-a",
                "checks": ["aisle_clear"],
                "robot_id": "mentorpi-03",
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "robot_capability_missing")
        self.assertIn("navigation", result["error"]["details"]["missing_capabilities"])

    def test_scheduled_in_past_is_rejected(self):
        result = self.registry.validate_mission(
            {
                "route_id": "route-a",
                "checks": ["aisle_clear"],
                "scheduled_for": "2020-01-01T00:00:00Z",
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "scheduled_in_past")

    def test_naive_scheduled_time_is_rejected(self):
        result = self.registry.validate_mission(
            {
                "route_id": "route-a",
                "checks": ["aisle_clear"],
                "scheduled_for": "2026-10-18T09:00:00",
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_scheduled_for")

    def test_fleet_snapshot_is_not_live(self):
        result = self.registry.fleet_snapshot()
        self.assertTrue(result["ok"])
        snapshot = result["snapshot"]
        self.assertFalse(snapshot["is_live"])
        self.assertEqual(snapshot["telemetry"], "not_connected")
        self.assertEqual(snapshot["counts"]["total"], 4)
        self.assertEqual(snapshot["counts"]["enabled"], 3)
        self.assertNotIn("online", snapshot["counts"])
        for robot in snapshot["robots"]:
            self.assertEqual(robot["telemetry"], "not_connected")
            self.assertIsNone(robot["last_seen"])

    def test_capabilities_declare_no_executor(self):
        result = self.registry.capabilities(
            tool_names=["get_capabilities"],
            limits={"max_plan_checks": 8},
            llm_configured=False,
        )
        capabilities = result["capabilities"]
        self.assertFalse(capabilities["execution"]["available"])
        self.assertEqual(capabilities["execution"]["executor"], "none_v1")
        self.assertEqual(capabilities["tools"], ["get_capabilities"])
        self.assertFalse(capabilities["data_sources"]["routes"]["is_live"])

    def test_production_registry_is_empty_and_reports_uncalibrated(self):
        production = Registry(ROOT / "data", now_fn=fixed_now)
        self.assertEqual(production.routes, [])
        self.assertEqual(production.robots, [])
        capabilities = production.capabilities(
            tool_names=["get_capabilities"],
            llm_configured=False,
        )["capabilities"]
        self.assertEqual(capabilities["calibration"]["routes"]["status"], "uncalibrated")
        self.assertEqual(capabilities["calibration"]["fleet"]["status"], "unregistered")
        message = production.validate_mission(
            {"route_id": "route-a", "checks": ["aisle_clear"]}
        )
        self.assertFalse(message["ok"])
        self.assertEqual(message["error"]["code"], "unknown_route")
        self.assertIn("维护者", message["clarification"])


if __name__ == "__main__":
    unittest.main()
