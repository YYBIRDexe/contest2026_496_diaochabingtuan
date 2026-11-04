import unittest

from cloud_agent.errors import StoreError

from tests.helpers import make_config, make_registry, make_store, make_toolbox, temp_dir


VALID_MISSION = {
    "route_id": "route-a",
    "checks": ["aisle_clear", "extinguisher_present"],
    "robot_id": "mentorpi-01",
}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self)
        self.config = make_config(self.tmp)
        self.registry = make_registry()
        self.store = make_store(self.tmp)
        self.toolbox = make_toolbox(self.config, self.registry, self.store)

    def test_create_and_approve_never_executes(self):
        result = self.toolbox.call("create_plan_proposal", VALID_MISSION, source="api")
        self.assertTrue(result["ok"])
        self.assertTrue(result["proposal_created"])
        proposal = result["proposal"]
        self.assertEqual(proposal["status"], "pending_confirmation")
        self.assertEqual(proposal["approval"]["state"], "pending")
        self.assertEqual(proposal["execution"]["state"], "not_executed")
        self.assertFalse(proposal["execution"]["executor_available"])

        decided = self.store.decide(proposal["proposal_id"], "approve", "tester", "ok")
        updated = decided["proposal"]
        self.assertEqual(updated["status"], "confirmed_not_executed")
        self.assertEqual(updated["approval"]["state"], "approved")
        self.assertEqual(updated["execution"]["state"], "not_executed")
        self.assertFalse(updated["execution"]["executor_available"])
        self.assertIn("不会下发车辆", updated["execution"]["reason"])

    def test_reject_never_executes(self):
        result = self.toolbox.call("create_plan_proposal", VALID_MISSION, source="api")
        proposal_id = result["proposal_id"]
        decided = self.store.decide(proposal_id, "reject", "tester", "bad route")
        self.assertEqual(decided["proposal"]["status"], "rejected")
        self.assertEqual(decided["proposal"]["execution"]["state"], "not_executed")

    def test_duplicate_decision_is_rejected(self):
        result = self.toolbox.call("create_plan_proposal", VALID_MISSION, source="api")
        proposal_id = result["proposal_id"]
        self.store.decide(proposal_id, "approve")
        with self.assertRaises(StoreError) as context:
            self.store.decide(proposal_id, "reject")
        self.assertEqual(context.exception.code, "proposal_already_decided")
        self.assertEqual(context.exception.http_status, 409)

    def test_unknown_route_creates_no_proposal(self):
        result = self.toolbox.call(
            "create_plan_proposal",
            {"route_id": "route-z", "checks": ["aisle_clear"]},
            source="api",
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["proposal_created"])
        self.assertEqual(result["error"]["code"], "unknown_route")
        self.assertEqual(self.store.list()["total"], 0)

    def test_invalid_arguments_create_no_proposal(self):
        result = self.toolbox.call(
            "create_plan_proposal",
            {"route_id": "route-a", "checks": []},
            source="api",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_arguments")
        self.assertEqual(self.store.list()["total"], 0)

    def test_persistence_round_trip(self):
        result = self.toolbox.call("create_plan_proposal", VALID_MISSION, source="api")
        proposal_id = result["proposal_id"]
        self.store.decide(proposal_id, "approve", "tester")
        reloaded = make_store(self.tmp)
        self.assertEqual(reloaded.list()["total"], 1)
        self.assertEqual(reloaded.get(proposal_id)["proposal"]["status"], "confirmed_not_executed")


if __name__ == "__main__":
    unittest.main()
