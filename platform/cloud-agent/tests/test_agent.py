import json
import unittest

from cloud_agent.errors import AgentLoopError, ConfigurationError

from tests.helpers import (
    make_agent,
    temp_dir,
    text_response,
    tool_response,
)


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self)

    def test_tool_call_round_trip_feeds_result_back_to_model(self):
        parts = make_agent(
            self.tmp,
            [
                tool_response([("get_fleet_snapshot", {})]),
                text_response("车队注册表已读取；没有实时遥测。"),
            ],
        )
        result = parts.agent.chat("车队现在怎么样？")
        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], "车队注册表已读取；没有实时遥测。")
        self.assertEqual(len(result["tool_events"]), 1)
        event = result["tool_events"][0]
        self.assertEqual(event["name"], "get_fleet_snapshot")
        self.assertTrue(event["ok"])
        self.assertFalse(event["clarification_required"])

        self.assertEqual(len(parts.llm.calls), 2)
        first_tools = [item["function"]["name"] for item in parts.llm.calls[0]["tools"]]
        self.assertEqual(
            first_tools,
            [
                "get_capabilities",
                "get_fleet_snapshot",
                "validate_mission",
                "create_plan_proposal",
            ],
        )
        second_messages = parts.llm.calls[1]["messages"]
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertEqual(second_messages[-1]["tool_call_id"], "call_test_0")
        tool_payload = json.loads(second_messages[-1]["content"])
        self.assertTrue(tool_payload["ok"])
        self.assertFalse(tool_payload["snapshot"]["is_live"])
        self.assertEqual(result["execution"]["state"], "not_executed")
        self.assertFalse(result["execution"]["executor_available"])

    def test_unknown_route_requires_clarification_and_no_proposal(self):
        parts = make_agent(
            self.tmp,
            [
                tool_response(
                    [("validate_mission", {"route_id": "route-z", "checks": ["aisle_clear"]})]
                ),
                text_response("没有找到 route-z。请确认要使用哪条已登记路线。"),
            ],
        )
        result = parts.agent.chat("给 route-z 做巡检。")
        event = result["tool_events"][0]
        self.assertEqual(event["name"], "validate_mission")
        self.assertFalse(event["ok"])
        self.assertTrue(event["clarification_required"])
        self.assertEqual(event["error_code"], "unknown_route")
        self.assertEqual(parts.store.list()["total"], 0)

        tool_message = parts.llm.calls[1]["messages"][-1]
        payload = json.loads(tool_message["content"])
        self.assertEqual(payload["error"]["code"], "unknown_route")
        self.assertTrue(payload["clarification_required"])

    def test_direct_create_with_unknown_route_is_refused(self):
        parts = make_agent(
            self.tmp,
            [
                tool_response(
                    [("create_plan_proposal", {"route_id": "route-z", "checks": ["aisle_clear"]})]
                ),
                text_response("未创建计划；请先确认已登记路线。"),
            ],
        )
        result = parts.agent.chat("直接给 route-z 创建计划。")
        self.assertEqual(result["proposals"], [])
        self.assertEqual(parts.store.list()["total"], 0)
        self.assertFalse(result["tool_events"][0]["ok"])
        self.assertEqual(result["tool_events"][0]["error_code"], "unknown_route")

    def test_invalid_arguments_are_reported_to_model_and_loop_continues(self):
        parts = make_agent(
            self.tmp,
            [
                tool_response(
                    [
                        (
                            "validate_mission",
                            {"route_id": "route-a", "checks": [], "unexpected": True},
                        )
                    ]
                ),
                text_response("参数不合法，需要至少一个检查项。"),
            ],
        )
        result = parts.agent.chat("测试参数校验。")
        event = result["tool_events"][0]
        self.assertFalse(event["ok"])
        self.assertEqual(event["error_code"], "invalid_arguments")
        payload = json.loads(parts.llm.calls[1]["messages"][-1]["content"])
        self.assertEqual(payload["error"]["code"], "invalid_arguments")
        self.assertEqual(parts.store.list()["total"], 0)

    def test_invalid_json_arguments_are_reported_without_execution(self):
        parts = make_agent(
            self.tmp,
            [
                tool_response([("validate_mission", "{not-json")]),
                text_response("工具参数 JSON 不合法。"),
            ],
        )
        result = parts.agent.chat("测试坏 JSON。")
        event = result["tool_events"][0]
        self.assertFalse(event["ok"])
        self.assertEqual(event["error_code"], "invalid_arguments_json")
        self.assertEqual(parts.store.list()["total"], 0)

    def test_plan_proposal_and_confirmation_are_not_execution(self):
        parts = make_agent(
            self.tmp,
            [
                tool_response(
                    [
                        (
                            "create_plan_proposal",
                            {
                                "route_id": "route-a",
                                "checks": ["aisle_clear"],
                                "robot_id": "mentorpi-01",
                            },
                        )
                    ]
                ),
                text_response("计划已创建，等待人工确认；首版没有执行器，仍未执行。"),
            ],
        )
        result = parts.agent.chat("为 route-a 创建计划。")
        self.assertEqual(len(result["proposals"]), 1)
        proposal_id = result["proposals"][0]
        proposal = parts.store.get(proposal_id)["proposal"]
        self.assertEqual(proposal["status"], "pending_confirmation")
        self.assertEqual(proposal["execution"]["state"], "not_executed")

        decided = parts.store.decide(proposal_id, "approve", "test")
        self.assertEqual(decided["proposal"]["status"], "confirmed_not_executed")
        self.assertEqual(decided["proposal"]["execution"]["state"], "not_executed")

    def test_loop_limit_raises_without_claiming_success(self):
        parts = make_agent(
            self.tmp,
            [tool_response([("get_capabilities", {})]), tool_response([("get_capabilities", {})])],
            max_tool_iterations=2,
        )
        with self.assertRaises(AgentLoopError) as context:
            parts.agent.chat("一直调用工具。")
        self.assertEqual(context.exception.code, "tool_loop_limit")
        self.assertEqual(len(context.exception.details["tool_events"]), 2)
        self.assertEqual(parts.store.list()["total"], 0)

    def test_unconfigured_service_refuses_chat(self):
        parts = make_agent(self.tmp, [], configured=False)
        with self.assertRaises(ConfigurationError) as context:
            parts.agent.chat("你好")
        self.assertEqual(context.exception.code, "llm_not_configured")
        self.assertIn("不会返回模拟结果", context.exception.message)
        self.assertEqual(len(parts.llm.calls), 0)

    def test_conversation_history_is_reused(self):
        parts = make_agent(
            self.tmp,
            [text_response("第一次答复。"), text_response("第二次答复。")],
        )
        first = parts.agent.chat("第一问")
        second = parts.agent.chat("第二问", first["conversation_id"])
        self.assertEqual(second["conversation_id"], first["conversation_id"])
        messages = parts.llm.calls[1]["messages"]
        contents = [item["content"] for item in messages if item["role"] in ("user", "assistant")]
        self.assertIn("第一问", contents)
        self.assertIn("第一次答复。", contents)
        self.assertEqual(contents[-1], "第二问")


if __name__ == "__main__":
    unittest.main()
