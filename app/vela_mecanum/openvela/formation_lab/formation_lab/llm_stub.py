from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any


def _completion(message: dict[str, Any], finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "id": f"chatcmpl-local-{uuid.uuid4().hex[:10]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "formation-local-stub",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _tool_call(arguments: dict[str, Any]) -> dict[str, Any]:
    return _completion(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {"name": "formation_control", "arguments": json.dumps(arguments, ensure_ascii=False)},
                }
            ],
        },
        "tool_calls",
    )


def _summarize_tool(content: str) -> str:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return f"实验服务返回：{content[:300]}"
    if not data.get("ok"):
        return f"操作未成功：{data.get('error', data)}"
    if "capabilities" in data:
        formations = "、".join(data["capabilities"].get("formations", []))
        modes = "、".join(data["capabilities"].get("control_modes", {}).keys())
        return f"本机编队服务可用，支持队形：{formations}；控制模式：{modes}。"
    exp = data.get("experiment") or {}
    state = exp.get("state", "UNKNOWN")
    exp_id = exp.get("experiment_id") or "当前实验"
    if state == "FORMING":
        return f"已启动实验 {exp_id}，四辆车正在形成 {exp.get('formation')} 编队。"
    if state == "HOLDING":
        return f"实验 {exp_id} 已到达编队，正在保持，最大误差 {exp.get('max_error_m')} 米。"
    if state == "FINISHED":
        return f"实验 {exp_id} 已完成，最终最大误差 {exp.get('max_error_m')} 米。"
    if state in ("FAILED", "ABORTED"):
        return f"实验 {exp_id} 已停止：{exp.get('message')}（{exp.get('error_code')}）。"
    return f"实验 {exp_id} 当前状态为 {state}，最大误差 {exp.get('max_error_m')} 米。"


def create_chat_completion(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages") or []
    if not isinstance(messages, list):
        return _completion({"role": "assistant", "content": "消息格式无效。"})
    last = messages[-1] if messages else {}
    if last.get("role") == "tool":
        return _completion({"role": "assistant", "content": _summarize_tool(str(last.get("content", "")))})

    user_text = ""
    for item in reversed(messages):
        if item.get("role") == "user":
            user_text = str(item.get("content", ""))
            break
    normalized = user_text.lower()
    if any(word in normalized for word in ("急停", "停止", "停下", "stop", "abort")):
        return _tool_call({"action": "stop", "reason": "natural_language_operator_stop"})
    if any(word in normalized for word in ("状态", "进度", "怎么样", "status")):
        return _tool_call({"action": "status"})
    if any(word in normalized for word in ("支持", "能力", "队形", "capabilities")) and not any(word in normalized for word in ("开始", "运行", "启动")):
        return _tool_call({"action": "capabilities"})

    control_mode = "anchored"
    if any(word in normalized for word in ("二阶", "双积分", "second-order", "second order", "double integrator")):
        control_mode = "second_order"
    elif any(word in normalized for word in ("拉普拉斯", "laplacian", "经典一致性", "标准一致性")):
        control_mode = "laplacian"
    formation = "square"
    for word, value in (("直线", "line"), ("一字", "line"), ("圆形", "circle"), ("圆", "circle"), ("菱形", "diamond"), ("正方形", "square"), ("方形", "square")):
        if word in normalized:
            formation = value
            break
    spacing_match = re.search(r"(?:间距|spacing)[^0-9]{0,6}([0-9]+(?:\.[0-9]+)?)", normalized)
    duration_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:秒|s(?:ec(?:ond)?s?)?)", normalized)
    spacing = float(spacing_match.group(1)) if spacing_match else 0.8
    duration = float(duration_match.group(1)) if duration_match else 30.0
    if any(word in normalized for word in ("开始", "运行", "启动", "编队", "formation")):
        return _tool_call(
            {
                "action": "start",
                "experiment_id": f"exp-{time.strftime('%Y%m%d-%H%M%S')}",
                "formation": formation,
                "spacing_m": spacing,
                "duration_s": duration,
                "control_mode": control_mode,
            }
        )
    return _completion({"role": "assistant", "content": "请告诉我要启动、查询还是停止编队实验，例如：让四辆车按正方形编队，间距0.8米，运行30秒。"})
