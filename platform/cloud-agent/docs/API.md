# Cloud Agent HTTP API

Base URL: `http://<platform>:8130`（默认只监听 `127.0.0.1`；部署脚本按参数监听 `0.0.0.0`）。

> 本文中的 `route-a`、`mentorpi-01` 等仅来自 `tests/fixtures/` 的测试/演示注册表，
> 不是生产数据。生产 `data/routes.json` 与 `data/fleet.json` 默认为空；未标定/未登记的
> 路线和车辆会被拒绝，并返回需要维护者登记的澄清信息。

所有请求/响应均为 UTF-8 JSON。写接口要求 `Content-Type: application/json`。请求体上限 64 KiB。

如果设备配置了 `CLOUD_AGENT_ACCESS_TOKEN`，除 `GET /api/health` 外都需要：

```http
Authorization: Bearer <token>
```

也接受 `X-Cloud-Agent-Token: <token>`。错误统一返回：

```json
{
  "ok": false,
  "error": {
    "code": "unknown_route",
    "message": "路线 'route-z' 未登记，不能生成计划。",
    "details": {}
  }
}
```

## 健康与能力

### `GET /api/health`

无需访问口令。示例：

```json
{
  "ok": true,
  "service": "velaguard-cloud-agent",
  "version": "0.1.0",
  "status": "unconfigured",
  "time": "2026-10-17T12:00:00Z",
  "llm": {
    "configured": false,
    "api_style": "openai_chat_completions",
    "base_url": "",
    "model": "",
    "api_key_source": "none",
    "proxy_mode": "direct",
    "missing": [
      "CLOUD_AGENT_LLM_BASE_URL",
      "CLOUD_AGENT_LLM_MODEL",
      "CLOUD_AGENT_LLM_API_KEY"
    ],
    "config_errors": [],
    "config_warnings": [],
    "env_file": "",
    "access_token_required": false
  },
  "execution": {
    "available": false,
    "executor": "none_v1",
    "reason": "首版没有运动执行器；计划确认不等于执行。"
  },
  "store": {"proposals": 0, "persistent": true, "load_warning": ""},
  "data": {
    "routes_sha256": "...",
    "fleet_sha256": "...",
    "routes_source": "local_registry",
    "fleet_source": "local_registry"
  }
}
```

`status` 为 `ready` 或 `unconfigured`。不会返回 API key。

### `GET /api/tools`

返回四个 OpenAI 工具定义与执行器边界：

```json
{
  "service": "velaguard-cloud-agent",
  "tools": [...],
  "execution": {
    "available": false,
    "executor": "none_v1",
    "message": "首版没有运动执行器；没有速度、坐标或底层控制工具。"
  }
}
```

### `GET /api/routes` / `GET /api/fleet` / `GET /api/capabilities`

- `/api/routes`：路线 id、名称、区域、检查点、允许的检查项、启用状态、注册表哈希、`source=local_registry`、`calibration`（生产为空时 `status=uncalibrated`）。
- `/api/fleet`：`snapshot.is_live=false`、`telemetry=not_connected`、车辆登记项、`calibration`（生产为空时 `status=unregistered`）；不包含位置/电量。
- `/api/capabilities`：工具、路线、车辆、执行器、限制、数据来源、`calibration`。空注册表时应向用户说明需要维护者标定/登记。

## 对话

### `POST /api/chat`

请求：

```json
{
  "message": "为 route-a 生成巡检计划，检查通道无占用和灭火器在位。",
  "conversation_id": "conv_optional"
}
```

- `message`：1–2000 字符。
- `conversation_id`：可选；只允许 `[A-Za-z0-9_-]{1,80}`。不传则创建新会话。
- 每 IP 20 次/分钟；超过返回 429 + `Retry-After`。

成功 200：

```json
{
  "ok": true,
  "conversation_id": "conv_...",
  "reply": "已创建计划，等待人工确认；首版没有运动执行器，仍未执行。",
  "tool_events": [
    {
      "tool_call_id": "call_...",
      "name": "create_plan_proposal",
      "arguments": {"route_id": "route-a", "checks": ["aisle_clear"]},
      "ok": true,
      "error_code": null,
      "clarification_required": false,
      "duration_ms": 2,
      "proposal_id": "prop_..."
    }
  ],
  "proposals": ["prop_..."],
  "iterations": 2,
  "finish_reason": "stop",
  "usage": {"prompt_tokens": 100, "completion_tokens": 50},
  "execution": {
    "state": "not_executed",
    "executor_available": false,
    "note": "本轮只读工具或创建待确认计划；没有下发任何车辆动作。"
  }
}
```

未配置模型：**503**，不会产生模拟答复：

```json
{
  "ok": false,
  "error": {
    "code": "llm_not_configured",
    "message": "模型尚未配置，聊天接口不会返回模拟结果。请在设备上配置 CLOUD_AGENT_LLM_BASE_URL、CLOUD_AGENT_LLM_MODEL 和 CLOUD_AGENT_LLM_API_KEY（或 CLOUD_AGENT_LLM_API_KEY_FILE）后重启服务。",
    "details": {
      "missing": ["..."],
      "config_errors": []
    }
  }
}
```

上游错误映射：

| 上游 | 本服务 code | HTTP |
|---|---|---|
| 401/403 | `llm_auth_failed` | 502 |
| 404 | `llm_endpoint_not_found` | 502 |
| 429 | `llm_rate_limited` | 429 |
| 5xx | `llm_upstream_error` | 502 |
| 超时 | `llm_timeout` | 504 |
| 连接失败 | `llm_unreachable` | 502 |
| 非 JSON / 缺 choices | `llm_invalid_response` | 502 |
| 工具循环超限 | `tool_loop_limit` | 502 |

## 任务校验

### `POST /api/missions/validate`

请求：

```json
{
  "route_id": "route-a",
  "checks": ["aisle_clear", "extinguisher_present"],
  "robot_id": "mentorpi-01",
  "scheduled_for": "2026-10-18T09:00:00+08:00"
}
```

- `route_id`、`checks` 必填；`checks` 必须是该路线登记的检查项 id。
- `robot_id` 可选；车辆必须已登记、启用且具备 `inspection` 与 `navigation` 能力（巡检路线需要移动到检查点）。
- `scheduled_for` 可选；必须带时区的 ISO-8601，且不能早于服务当前时间。

成功 200：

```json
{
  "ok": true,
  "clarification_required": false,
  "validation_id": "val_...",
  "validated_at": "2026-10-17T12:00:00Z",
  "route": {
    "id": "route-a",
    "name": "A 区实验通道",
    "zone": "实训室 A 区",
    "checkpoints": ["A-01 入口", "..."]
  },
  "robot": {"id": "mentorpi-01", "name": "巡检车 01", "status": "registered", "telemetry": "not_connected"},
  "checks": [{"id": "aisle_clear", "label": "通道无占用"}],
  "scheduled_for": "2026-10-18T01:00:00Z",
  "warnings": [
    {"code": "planning_only", "message": "本结果只完成计划校验；没有探测车辆状态，也不代表车辆可执行。"},
    {"code": "telemetry_not_connected", "message": "车辆 ... 的在线/位置/电量未读取；本地注册表不能证明车辆可用。"}
  ],
  "registry": {
    "routes_source": "local_registry",
    "routes_sha256": "...",
    "fleet_source": "local_registry",
    "fleet_sha256": "...",
    "is_live": false
  }
}
```

未知路线 422：

```json
{
  "ok": false,
  "error": {
    "code": "unknown_route",
    "message": "路线 'route-z' 未登记，不能生成计划。",
    "details": {
      "route_id": "route-z",
      "known_routes": [{"id": "route-a", "name": "A 区实验通道", "enabled": true}]
    }
  },
  "clarification_required": true,
  "clarification": "没有找到路线 'route-z'。我不会猜测路线。请确认是以下哪条已登记路线：..."
}
```

其他校验错误：`unknown_check`、`route_disabled`、`unknown_robot`、`robot_unavailable`、`robot_capability_missing`、`invalid_scheduled_for`、`scheduled_in_past`。

## 提案

### `POST /api/proposals`

请求同 `/api/missions/validate`，可额外带 `rationale`（≤500 字符）。内部会再次校验；成功 **201**：

```json
{
  "ok": true,
  "proposal_created": true,
  "proposal_id": "prop_...",
  "proposal": {
    "schema_version": "1.0",
    "proposal_id": "prop_...",
    "plan_version": 1,
    "status": "pending_confirmation",
    "created_at": "2026-10-17T12:00:00Z",
    "source": "api",
    "rationale": "...",
    "mission": {
      "route": {"id": "route-a", "name": "A 区实验通道", "zone": "实训室 A 区", "checkpoints": ["..."]},
      "checks": [{"id": "aisle_clear", "label": "通道无占用"}],
      "robot": {"id": "mentorpi-01", "name": "巡检车 01", "status": "registered", "telemetry": "not_connected"},
      "scheduled_for": null,
      "validation_id": "val_...",
      "validated_at": "...",
      "warnings": [{"code": "planning_only", "message": "..."}]
    },
    "approval": {
      "required": true,
      "state": "pending",
      "binds_plan_version": 1,
      "binding": {"validation_id": "val_...", "route_id": "route-a"},
      "decided_at": null,
      "decided_by": null,
      "note": ""
    },
    "execution": {
      "state": "not_executed",
      "executor": "none_v1",
      "executor_available": false,
      "reason": "首版没有运动执行器。批准只表示计划被确认，不会下发车辆、不会改变车辆状态，也不等于已执行。",
      "last_attempt_at": null,
      "last_result": null
    },
    "registry": {"...": "..."}
  },
  "execution": {
    "state": "not_executed",
    "executor_available": false,
    "message": "提案已创建，等待人工确认；首版没有运动执行器，确认也不会下发车辆。"
  }
}
```

未登记路线返回 **422**，包含 `proposal_created: false`，不落库。

### `GET /api/proposals?limit=50`

返回新→旧的提案列表：`{"ok":true,"count":N,"total":M,"proposals":[...]}`。

### `GET /api/proposals/<id>`

不存在返回 404 `proposal_not_found`。

### `POST /api/proposals/<id>/decision`

请求：

```json
{"decision": "approve", "actor": "operator-name", "note": "同意本周巡检"}
```

- `decision`：`approve` 或 `reject`。
- `actor` ≤80，`note` ≤500。
- 批准后：`status=confirmed_not_executed`、`approval.state=approved`、`execution.state` 仍为 `not_executed`。
- 重复决定返回 **409** `proposal_already_decided`。
- 没有执行接口；任何“批准后已执行/车辆已出发”的说法都是错误的。

## 静态 UI

- `GET /`：同源控制台。
- `GET /static/*`：CSS/JS/SVG。
- 响应头包含 CSP：`default-src 'self'; connect-src 'self'; ...; frame-ancestors 'none'`。
- 页面不保存 key；可选访问口令仅存于当前标签页 `sessionStorage`。
