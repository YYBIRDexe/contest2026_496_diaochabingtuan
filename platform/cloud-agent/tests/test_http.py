import json
import unittest

from tests.helpers import call_wsgi, make_app, temp_dir, text_response, tool_response


VALID_MISSION = {
    "route_id": "route-a",
    "checks": ["aisle_clear"],
    "robot_id": "mentorpi-01",
}


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self)

    def test_health_and_static_are_same_origin(self):
        parts = make_app(self.tmp, configured=False)
        health = call_wsgi(parts.app, "GET", "/api/health")
        self.assertEqual(health["status_code"], 200)
        self.assertEqual(health["json"]["status"], "unconfigured")
        self.assertFalse(health["json"]["llm"]["configured"])
        self.assertFalse(health["json"]["execution"]["available"])

        index = call_wsgi(parts.app, "GET", "/")
        self.assertEqual(index["status_code"], 200)
        self.assertIn(b"VelaGuard", index["body"])
        self.assertIn("default-src 'self'", index["header_map"]["content-security-policy"])

    def test_unconfigured_chat_returns_503_not_mock(self):
        parts = make_app(self.tmp, configured=False)
        response = call_wsgi(parts.app, "POST", "/api/chat", {"message": "你好"})
        self.assertEqual(response["status_code"], 503)
        self.assertEqual(response["json"]["error"]["code"], "llm_not_configured")
        self.assertIn("不会返回模拟结果", response["json"]["error"]["message"])
        self.assertEqual(parts.llm.calls, [])

    def test_configured_chat_uses_agent_loop(self):
        parts = make_app(
            self.tmp,
            responses=[
                tool_response([("get_fleet_snapshot", {})]),
                text_response("注册表已读取，未接实时遥测。"),
            ],
        )
        response = call_wsgi(parts.app, "POST", "/api/chat", {"message": "车队状态？"})
        self.assertEqual(response["status_code"], 200)
        self.assertEqual(response["json"]["reply"], "注册表已读取，未接实时遥测。")
        self.assertEqual(len(response["json"]["tool_events"]), 1)
        self.assertFalse(response["json"]["execution"]["executor_available"])

    def test_unknown_route_is_422_with_clarification_and_no_proposal(self):
        parts = make_app(self.tmp, configured=False)
        response = call_wsgi(
            parts.app,
            "POST",
            "/api/missions/validate",
            {"route_id": "route-z", "checks": ["aisle_clear"]},
        )
        self.assertEqual(response["status_code"], 422)
        self.assertEqual(response["json"]["error"]["code"], "unknown_route")
        self.assertTrue(response["json"]["clarification_required"])
        self.assertEqual(parts.store.list()["total"], 0)

    def test_proposal_approval_is_not_execution(self):
        parts = make_app(self.tmp, configured=False)
        created = call_wsgi(parts.app, "POST", "/api/proposals", VALID_MISSION)
        self.assertEqual(created["status_code"], 201)
        self.assertTrue(created["json"]["proposal_created"])
        proposal_id = created["json"]["proposal_id"]
        self.assertEqual(created["json"]["proposal"]["status"], "pending_confirmation")
        self.assertEqual(created["json"]["proposal"]["execution"]["state"], "not_executed")

        approved = call_wsgi(
            parts.app,
            "POST",
            "/api/proposals/%s/decision" % proposal_id,
            {"decision": "approve", "actor": "test"},
        )
        self.assertEqual(approved["status_code"], 200)
        self.assertEqual(approved["json"]["proposal"]["status"], "confirmed_not_executed")
        self.assertEqual(approved["json"]["proposal"]["execution"]["state"], "not_executed")
        self.assertFalse(approved["json"]["proposal"]["execution"]["executor_available"])

        duplicate = call_wsgi(
            parts.app,
            "POST",
            "/api/proposals/%s/decision" % proposal_id,
            {"decision": "reject"},
        )
        self.assertEqual(duplicate["status_code"], 409)

    def test_access_token_protects_data_endpoints_but_not_health(self):
        parts = make_app(self.tmp, configured=False, access_token="token-123")
        health = call_wsgi(parts.app, "GET", "/api/health")
        self.assertEqual(health["status_code"], 200)
        denied = call_wsgi(parts.app, "GET", "/api/proposals")
        self.assertEqual(denied["status_code"], 401)
        self.assertIn("www-authenticate", denied["header_map"])
        allowed = call_wsgi(
            parts.app,
            "GET",
            "/api/proposals",
            headers={"Authorization": "Bearer token-123"},
        )
        self.assertEqual(allowed["status_code"], 200)

    def test_static_traversal_is_rejected(self):
        parts = make_app(self.tmp, configured=False)
        response = call_wsgi(parts.app, "GET", "/static/../app.py")
        self.assertEqual(response["status_code"], 404)

    def test_static_directory_url_serves_its_index(self):
        parts = make_app(self.tmp, configured=False)
        response = call_wsgi(parts.app, "GET", "/static/scene-v2/")
        self.assertEqual(response["status_code"], 200)
        self.assertIn("text/html", response["header_map"]["content-type"])
        self.assertIn("选一处水岸", response["body"].decode("utf-8"))
        # The isolated scene page is also the only one allowed to ask for the microphone.
        self.assertIn("microphone=(self)", response["header_map"]["permissions-policy"])
        other = call_wsgi(parts.app, "GET", "/")
        self.assertIn("microphone=()", other["header_map"]["permissions-policy"])

    def test_directory_without_index_stays_404(self):
        parts = make_app(self.tmp, configured=False)
        response = call_wsgi(parts.app, "GET", "/static/scene-v2/assets/")
        self.assertEqual(response["status_code"], 404)

    def test_large_body_is_rejected(self):
        parts = make_app(self.tmp, configured=False)
        response = call_wsgi(parts.app, "POST", "/api/chat", b"x" * 70000)
        self.assertEqual(response["status_code"], 413)

    def test_unknown_api_is_404(self):
        parts = make_app(self.tmp, configured=False)
        response = call_wsgi(parts.app, "GET", "/api/nope")
        self.assertEqual(response["status_code"], 404)
        self.assertEqual(response["json"]["error"]["code"], "not_found")

    def test_head_static_has_no_body(self):
        parts = make_app(self.tmp, configured=False)
        response = call_wsgi(parts.app, "HEAD", "/")
        self.assertEqual(response["status_code"], 200)
        self.assertEqual(response["body"], b"")
        self.assertGreater(int(response["header_map"]["content-length"]), 0)

    def test_invalid_decision_is_400(self):
        parts = make_app(self.tmp, configured=False)
        created = call_wsgi(parts.app, "POST", "/api/proposals", VALID_MISSION)
        proposal_id = created["json"]["proposal_id"]
        response = call_wsgi(
            parts.app,
            "POST",
            "/api/proposals/%s/decision" % proposal_id,
            {"decision": "maybe"},
        )
        self.assertEqual(response["status_code"], 400)
        self.assertEqual(response["json"]["error"]["code"], "invalid_decision")


if __name__ == "__main__":
    unittest.main()
