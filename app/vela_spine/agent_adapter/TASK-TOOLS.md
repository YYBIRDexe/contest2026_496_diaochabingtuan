# 官方 ai_agent 业务工具（D 项）— 落地说明与板端接入清单

状态（2026-10-26 22:40）：**主机侧已实现并通过真 C 执行测试；板端注册未应用**。
本文件如实区分“已验证”与“待验证”，不得把主机通过写成板端通过。

## 1. 已实现（主机可执行）

| 文件 | 内容 |
|---|---|
| `agent_adapter/task_tools.h` | `sp_task_tool_prompt()`、`sp_task_tool_call(root, endpoint, name, args_json, reply)` |
| `agent_adapter/task_tools.c` | 三个工具的参数形状检查 + 调用账本 + 结果封装 |
| `spine_main.c` | 调试入口 `--task-tool ROOT NAME ARGS_JSON [ENDPOINT]` |
| `tests/test_task_tools.py` | 6 个用例，真 C 进程 × 环形回路模拟器 |

三个工具（只此三个，拒绝 shell／文件路径／速度／任意 URL）：

| 工具 | 参数 | 执行体 | 退出码语义 |
|---|---|---|---|
| `task_status` | `{}` 或 `{"task_id":"T1"}` | `sp_task_view()` | 0；任务不存在=2 且 `status=TASK_NOT_FOUND` |
| `task_submit` | `spine-plan-v1` 计划，≤8 条任务 | `sp_task_plan_apply()` | 0 落盘；2 计划非法；3 存储损坏 |
| `task_stop` | `{"task_id":"T1"}`，可选 endpoint | `sp_task_stop()` + `sp_task_stop_sync()` | 0；2 参数非法；3 存储；4 网络 |

统一应答（模型看到的就是工具执行结果，不是自然语言解释）：

```json
{"tool":"task_stop","ok":true,"code":0,"motion":false,"ack_scope":"LOCAL_STORAGE_ONLY",
 "result":{"request":{"status":"STOP_REQUESTED","executor_confirmed":false,...},
           "executor":{"status":"STOP_SYNC_STEP","tasks":[{"status":"STOP_CONFIRMED","executor_confirmed":true}]}}}
```

关键边界与账本一致：`task_submit` 成功只代表**计划落盘**（`PLAN_PERSISTED`），不代表车辆执行；
`task_stop` 未带 endpoint 或执行器未回报 `STOP_CONFIRMED` 时 `executor_confirmed=false`。

## 2. 尚未完成（板端，阻塞）

板端需要把三个工具注册进官方 ai_agent 的工具表，并把模型文本里的工具调用交给
`sp_task_tool_call()` 执行。待设备恢复后按下列顺序做，每一步都要留原始输出：

1. 找到官方工具表与执行器分发位置（`packages/ai_agent/src/tools/` 下的工具定义 +
   `core/agent_loop.c` 里的分发表；`install_bridge.py` 曾 patch 过 `llm/llm_parse.c`、
   `tools/tool_files.c`、`core/agent_loop.c`、`llm/llm_proxy.c`）。**先读源码确认结构，不猜测改动。**
2. 新增 `tools/tool_task.c`：把 name/arguments 转给 `sp_task_tool_call("/data/ai_agent/sp", endpoint, ...)`，
   把返回 JSON 作为工具结果回填。endpoint 取自 `/data/ai_agent/sp/endpoint.txt`（现有约定）。
3. 把三个工具名写进系统提示（`sp_task_tool_prompt()` 已给出中文说明），并确保
   现有 `read_file` 只读桥不再把这三个名字当成普通文本。
4. 板端冒烟：真实模型说“查一下当前任务” → 必须看到 `tool=task_status` 的执行记录与账本回执；
   再让它“提交计划”“停止 T1”，逐条比对账本 `tasks.json` 与模拟器 `/v1/state`。
5. 失败路径：给不存在的 task_id、给带 `speed` 字段的计划、断网时 stop，确认分别返回
   2/2/4 且账本未被改写。

## 3. 未做（明确排除）

- 不开放任意 shell、文件路径、运动速度、地图坐标；
- 不做云端完整协商与自动重规划；
- 不让模型解释替代工具执行，也不把工具成功当成执行完成。

## 4. 证据

- 主机测试：`Ran 81 tests ... OK`（含 6 个工具用例），日志见
  `设备验收/五项闭环-20261026/evidence/build-tools.log`；
- 账本与协议：`host/BOARD-TASK-PROTOCOL.md`、`host/ROBOT-PROTOCOL.md`；
- 板端证据：**尚无**（真板离线，`adb devices` 无设备）。
