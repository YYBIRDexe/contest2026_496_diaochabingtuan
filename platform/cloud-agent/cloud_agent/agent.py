"""OpenAI-compatible tool-calling loop with an explicit confirmation boundary."""

import json
import threading
import time

from .errors import AgentLoopError, CloudAgentError, ConfigurationError
from .util import new_id, truncate_text

SYSTEM_PROMPT = """你是 VelaGuard 的小米 AIoT 平台侧认知 Agent。你负责把自然语言巡检需求转成经过本地注册表校验的计划提案，并向操作者解释清楚。

硬性规则：
1. 事实必须来自工具结果。不要编造路线、检查项、车辆、在线状态、位置、电量或执行结果。工具结果中的 is_live=false 表示没有实时遥测。
2. 生成计划前必须先调用 validate_mission。若返回 clarification_required=true（例如 unknown_route、unknown_check、unknown_robot），必须向用户提出具体澄清问题，列出可用的已登记选项；不得猜测，不得继续调用 create_plan_proposal。
3. 只有 validate_mission 返回 ok=true 后，才能调用 create_plan_proposal。未登记路线、停用路线、非本路线检查项、停用车辆都不能提案成功。
4. 提案不是执行。create_plan_proposal 返回的 execution.state 固定为 not_executed；首版没有运动执行器。批准只代表人工确认计划，不代表车辆已收到、已启动或已完成。回答中必须明确这一点。
5. 不要提供或承诺坐标、速度、底层控制、绕过授权、自动执行或“确认后马上跑”的能力。遇到此类要求，说明首版没有执行器，并建议走后续设备适配器验收流程。
6. 车队快照只是本地登记表，不是在线遥测。不得把 status=registered 说成在线，也不得声称知道车辆位置或电量。
7. 参数不合法时，根据工具返回的错误修正一次；不要反复提交同样的非法参数。工具报错时如实说明，不要伪造成功。
8. 涉及时间时使用带时区的 ISO-8601；时区不明就先问清楚。
9. 用简体中文回答，简洁、具体。涉及事实时说明数据来源和“未接实时遥测/未执行”的状态。
10. 若 get_capabilities 的 calibration 显示 uncalibrated 或 unregistered，明确说明当前没有已核验的标定路线/登记车辆，需要维护者现场标定或登记后才能生成计划；不要用示例、历史候选或猜测补足。
11. 对普通用户不要罗列环境变量名、HTTP 状态码、密钥路径、部署脚本等技术细节；需要排障时只说明“请联系维护者查看技术详情”，技术信息放在折叠区域或交给维护者。

可用工具：get_capabilities、get_fleet_snapshot、validate_mission、create_plan_proposal。"""


class Conversation(object):
    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()
        self.updated = time.monotonic()


class ConversationStore(object):
    def __init__(self, ttl_seconds=1800, max_conversations=200):
        self.ttl_seconds = ttl_seconds
        self.max_conversations = max_conversations
        self._lock = threading.Lock()
        self._items = {}

    def get_or_create(self, conversation_id):
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            if conversation_id:
                existing = self._items.get(conversation_id)
                if existing is not None:
                    existing.updated = now
                    return conversation_id, existing
            new_id_value = new_id("conv")
            conversation = Conversation()
            conversation.updated = now
            self._items[new_id_value] = conversation
            self._prune_locked(now)
            return new_id_value, conversation

    def _prune_locked(self, now):
        expired = [
            key
            for key, value in self._items.items()
            if now - value.updated > self.ttl_seconds
        ]
        for key in expired:
            self._items.pop(key, None)
        if len(self._items) <= self.max_conversations:
            return
        ordered = sorted(self._items.items(), key=lambda item: item[1].updated)
        for key, _ in ordered[: len(self._items) - self.max_conversations]:
            self._items.pop(key, None)


class AgentService(object):
    def __init__(self, config, toolbox, llm, conversations=None):
        self.config = config
        self.toolbox = toolbox
        self.llm = llm
        self.conversations = conversations or ConversationStore()
        self.max_message_chars = 2000

    def chat(self, message, conversation_id=None):
        if not self.config.configured:
            raise ConfigurationError(
                details={
                    "missing": self.config.missing_fields,
                    "config_errors": self.config.config_errors,
                }
            )
        if not isinstance(message, str) or not message.strip():
            raise CloudAgentError(
                "message 必须是非空字符串。",
                code="invalid_message",
                http_status=400,
            )
        message = message.strip()
        if len(message) > self.max_message_chars:
            raise CloudAgentError(
                "message 过长，最多 %d 个字符。" % self.max_message_chars,
                code="message_too_long",
                http_status=400,
            )

        conversation_id, conversation = self.conversations.get_or_create(conversation_id)
        with conversation.lock:
            turn_messages = [{"role": "user", "content": message}]
            messages = (
                [{"role": "system", "content": SYSTEM_PROMPT}]
                + list(conversation.messages)
                + turn_messages
            )
            events = []
            proposals = []
            usage = {}
            final_text = ""
            finish_reason = None
            iterations = 0

            for iteration in range(self.config.max_tool_iterations):
                iterations = iteration + 1
                response = self.llm.complete(messages, self.toolbox.definitions())
                assistant = self._normalize_assistant(response.get("message") or {})
                self._merge_usage(usage, response.get("usage") or {})
                if not assistant.get("content") and not assistant.get("tool_calls"):
                    raise CloudAgentError(
                        "模型返回了空消息。",
                        code="llm_empty_message",
                        http_status=502,
                    )

                tool_calls = assistant.get("tool_calls") or []
                if not tool_calls:
                    messages.append(assistant)
                    final_text = assistant.get("content") or ""
                    finish_reason = response.get("finish_reason")
                    break

                tool_calls = self._normalize_tool_calls(tool_calls)
                assistant["tool_calls"] = tool_calls
                messages.append(assistant)

                for call in tool_calls:
                    function = call.get("function") or {}
                    name = function.get("name")
                    arguments = function.get("arguments", "{}")
                    started = time.monotonic()
                    result = self.toolbox.call(name, arguments, source="agent")
                    duration_ms = int((time.monotonic() - started) * 1000)
                    event = {
                        "tool_call_id": call.get("id"),
                        "name": name if isinstance(name, str) else "",
                        "arguments": self._preview_arguments(arguments),
                        "ok": bool(result.get("ok")),
                        "error_code": (
                            (result.get("error") or {}).get("code")
                            if not result.get("ok")
                            else None
                        ),
                        "clarification_required": bool(result.get("clarification_required")),
                        "duration_ms": duration_ms,
                    }
                    if result.get("proposal_id"):
                        event["proposal_id"] = result["proposal_id"]
                        proposals.append(result["proposal_id"])
                    events.append(event)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "name": name if isinstance(name, str) else "unknown",
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
            else:
                raise AgentLoopError(
                    "模型连续调用工具达到上限，未生成最终答复。",
                    details={
                        "iterations": iterations,
                        "tool_events": events,
                        "note": "未执行任何车辆动作。",
                    },
                )

            conversation.messages.extend(turn_messages)
            conversation.messages.append({"role": "assistant", "content": final_text})
            if len(conversation.messages) > 24:
                conversation.messages = conversation.messages[-24:]
                while conversation.messages and conversation.messages[0].get("role") != "user":
                    conversation.messages.pop(0)
            conversation.updated = time.monotonic()

            if not final_text.strip():
                final_text = "模型没有返回文本答复。本轮工具调用已完成，请查看工具记录。"

            return {
                "ok": True,
                "conversation_id": conversation_id,
                "reply": final_text,
                "tool_events": events,
                "proposals": list(dict.fromkeys(proposals)),
                "iterations": iterations,
                "finish_reason": finish_reason,
                "usage": usage,
                "execution": {
                    "state": "not_executed",
                    "executor_available": False,
                    "note": "本轮只读工具或创建待确认计划；没有下发任何车辆动作。",
                },
            }

    @staticmethod
    def _normalize_assistant(message):
        if not isinstance(message, dict):
            return {"role": "assistant", "content": ""}
        normalized = {
            "role": "assistant",
            "content": message.get("content") if isinstance(message.get("content"), str) else "",
        }
        if message.get("tool_calls"):
            normalized["tool_calls"] = message.get("tool_calls")
        return normalized

    @staticmethod
    def _normalize_tool_calls(tool_calls):
        normalized = []
        for call in tool_calls:
            if not isinstance(call, dict):
                call = {
                    "id": new_id("call"),
                    "type": "function",
                    "function": {"name": "__malformed__", "arguments": "{}"},
                }
            if not isinstance(call.get("id"), str) or not call.get("id"):
                call["id"] = new_id("call")
            if not isinstance(call.get("type"), str):
                call["type"] = "function"
            function = call.get("function")
            if not isinstance(function, dict):
                function = {"name": "__malformed__", "arguments": "{}"}
                call["function"] = function
            arguments = function.get("arguments")
            if isinstance(arguments, (dict, list)):
                try:
                    function["arguments"] = json.dumps(arguments, ensure_ascii=False)
                except (TypeError, ValueError):
                    function["arguments"] = "{}"
            elif arguments is None:
                function["arguments"] = "{}"
            elif not isinstance(arguments, str):
                function["arguments"] = str(arguments)
            normalized.append(call)
        return normalized

    @staticmethod
    def _preview_arguments(arguments):
        if isinstance(arguments, dict):
            try:
                return json.loads(json.dumps(arguments, ensure_ascii=False))
            except (TypeError, ValueError):
                return {"_unserializable": True}
        if isinstance(arguments, str):
            text = arguments.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except ValueError:
                pass
            return {"_raw": truncate_text(text, 500)}
        return {"_type": type(arguments).__name__}

    @staticmethod
    def _merge_usage(total, usage):
        if not isinstance(usage, dict):
            return
        for key, value in usage.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                total[key] = total.get(key, 0) + value
