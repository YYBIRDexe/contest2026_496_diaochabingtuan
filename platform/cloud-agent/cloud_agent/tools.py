"""The four real tools exposed to the model and to the HTTP API.

Every tool validates its own arguments, returns a JSON-serializable result and
never performs a side effect beyond creating a pending plan.  There is no
motion, shell, filesystem or network tool.
"""

import json
import logging

from . import SERVICE_NAME
from .schema import error_summary, validate
from .util import truncate_text

LOG = logging.getLogger("cloud_agent.tools")

MISSION_INPUT_PROPERTIES = {
    "route_id": {
        "type": "string",
        "minLength": 1,
        "maxLength": 64,
        "description": "已登记且经维护者核验的路线 id；不要使用示例或猜测的 id。",
    },
    "checks": {
        "type": "array",
        "minItems": 1,
        "maxItems": 8,
        "items": {"type": "string", "minLength": 1, "maxLength": 64},
        "description": "该路线登记的检查项 id 列表；不要编造检查项。",
    },
    "robot_id": {
        "type": "string",
        "minLength": 1,
        "maxLength": 64,
        "description": "可选。已登记车辆 id；省略表示暂不分配车辆。",
    },
    "scheduled_for": {
        "type": "string",
        "minLength": 1,
        "maxLength": 40,
        "description": "可选。带时区的 ISO-8601 时间，例如 2026-10-18T09:00:00+08:00。",
    },
}

CAPABILITIES_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

FLEET_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

VALIDATE_MISSION_SCHEMA = {
    "type": "object",
    "properties": MISSION_INPUT_PROPERTIES,
    "required": ["route_id", "checks"],
    "additionalProperties": False,
}

CREATE_PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": dict(
        MISSION_INPUT_PROPERTIES,
        rationale={
            "type": "string",
            "maxLength": 500,
            "description": "可选。向审批人说明为什么安排这次巡检。",
        },
    ),
    "required": ["route_id", "checks"],
    "additionalProperties": False,
}


class ToolBox(object):
    def __init__(self, config, registry, store):
        self.config = config
        self.registry = registry
        self.store = store
        self._specs = [
            {
                "name": "get_capabilities",
                "description": (
                    "读取服务能力、calibration（是否已有已核验标定路线/车辆）、已登记路线/检查项/车辆、"
                    "数据来源和执行器状态。任何关于“能做什么、有哪些路线、有没有执行器”的回答都应先调用本工具。"
                    "calibration 显示 uncalibrated/unregistered 时，要明确告诉用户需要维护者先完成标定和登记。"
                ),
                "parameters": CAPABILITIES_SCHEMA,
                "handler": self._get_capabilities,
            },
            {
                "name": "get_fleet_snapshot",
                "description": (
                    "读取本地车队注册表快照。返回 is_live=false，表示没有实时遥测；"
                    "不得把登记状态说成车辆在线、位置已知或电量已知。"
                ),
                "parameters": FLEET_SCHEMA,
                "handler": self._get_fleet_snapshot,
            },
            {
                "name": "validate_mission",
                "description": (
                    "用本地注册表校验巡检任务：路线必须已登记且启用，检查项必须属于该路线，"
                    "车辆必须已登记且启用。未知路线会返回 clarification_required=true，"
                    "此时必须向用户澄清，不能猜测路线或继续提案。本工具不创建计划、不执行。"
                ),
                "parameters": VALIDATE_MISSION_SCHEMA,
                "handler": self._validate_mission,
            },
            {
                "name": "create_plan_proposal",
                "description": (
                    "在校验通过后创建一个待人工确认的计划提案。提案的 execution.state 固定为 "
                    "not_executed；首版没有运动执行器。批准只代表确认计划，不代表已执行。"
                    "未知路线或未知检查项会失败，不会创建提案。"
                ),
                "parameters": CREATE_PROPOSAL_SCHEMA,
                "handler": self._create_plan_proposal,
            },
        ]
        self._by_name = {spec["name"]: spec for spec in self._specs}

    def names(self):
        return [spec["name"] for spec in self._specs]

    def definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": spec["parameters"],
                },
            }
            for spec in self._specs
        ]

    def call(self, name, arguments, source="agent"):
        if not isinstance(name, str) or name not in self._by_name:
            return {
                "ok": False,
                "error": {
                    "code": "unknown_tool",
                    "message": "工具 %r 不存在。可用工具：%s。"
                    % (name, ", ".join(self.names())),
                },
            }

        if arguments is None:
            arguments = {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError as exc:
                return {
                    "ok": False,
                    "error": {
                        "code": "invalid_arguments_json",
                        "message": "工具参数不是合法 JSON：%s" % truncate_text(exc, 200),
                    },
                }
        if not isinstance(arguments, dict):
            return {
                "ok": False,
                "error": {
                    "code": "invalid_arguments_type",
                    "message": "工具参数必须是 JSON 对象。",
                },
            }

        spec = self._by_name[name]
        errors = validate(arguments, spec["parameters"])
        if errors:
            return {
                "ok": False,
                "error": {
                    "code": "invalid_arguments",
                    "message": "工具参数校验失败：%s" % error_summary(errors),
                    "details": {"validation_errors": errors},
                },
            }

        try:
            result = spec["handler"](arguments, source)
        except Exception as exc:  # never leak a traceback to the model
            LOG.exception("tool %s failed", name)
            return {
                "ok": False,
                "error": {
                    "code": "tool_internal_error",
                    "message": "工具 %s 执行失败：%s" % (name, truncate_text(exc, 200)),
                },
            }
        if not isinstance(result, dict):
            return {
                "ok": False,
                "error": {"code": "tool_invalid_result", "message": "工具返回了非对象结果。"},
            }
        return result

    def _get_capabilities(self, arguments, source):
        return self.registry.capabilities(
            tool_names=self.names(),
            limits={
                "max_plan_checks": 8,
                "max_tool_iterations": self.config.max_tool_iterations,
                "llm_timeout_seconds": self.config.timeout_seconds,
            },
            llm_configured=self.config.configured,
        )

    def _get_fleet_snapshot(self, arguments, source):
        return self.registry.fleet_snapshot()

    def _validate_mission(self, arguments, source):
        return self.registry.validate_mission(arguments)

    def _create_plan_proposal(self, arguments, source):
        validation = self.registry.validate_mission(arguments)
        if not validation.get("ok"):
            validation["proposal_created"] = False
            return validation
        result = self.store.create_from_validation(
            validation,
            source="agent_tool" if source == "agent" else "api",
            rationale=arguments.get("rationale"),
        )
        result["proposal_created"] = True
        result["execution"] = {
            "state": "not_executed",
            "executor_available": False,
            "message": "提案已创建，等待人工确认；首版没有运动执行器，确认也不会下发车辆。",
        }
        return result

    def service_descriptor(self):
        return {
            "service": SERVICE_NAME,
            "tools": self.definitions(),
            "execution": {
                "available": False,
                "executor": "none_v1",
                "message": "首版没有运动执行器；没有速度、坐标或底层控制工具。",
            },
        }
