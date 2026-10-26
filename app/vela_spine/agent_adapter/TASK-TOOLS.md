# 官方 ai_agent 业务工具（D 项）— 落地说明与板端接入清单

状态（2026-10-26 22:45）：**主机侧三工具实现、真 C 执行测试、官方源码注册补丁均已通过；
补丁尚未应用到真板镜像，真机模型调用未验证**。本文件如实区分“已验证”与“待验证”，
不得把主机通过写成板端通过。

## 1. 已实现（主机可执行，有真实日志）

| 文件 | 内容 |
|---|---|
| `agent_adapter/task_tools.h/.c` | 三个工具的参数形状检查 + 调用板端账本 + 结果封装 |
| `agent_adapter/board/tool_task.h/.c` | 板端执行器：交给 `sp_task_tool_call("/data/ai_agent/sp", endpoint, ...)`，endpoint 读 `/data/ai_agent/sp/endpoint.txt` |
| `agent_adapter/install_task_tools.py` | 幂等注册补丁（复制执行器、在 `tool_registry.c` 注册三工具、在 `CMakeLists.txt` 追加源文件） |
| `spine_main.c` | 调试入口 `--task-tool ROOT NAME ARGS_JSON [ENDPOINT]` |
| `tests/test_task_tools.py` | 6 个用例，真 C 进程 × 环形回路模拟器 |

三个工具（只有这三个，拒绝 shell／文件路径／速度／任意 URL）：

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

## 2. 官方源码注册（补丁已就绪，对官方代码副本验证过）

`install_task_tools.py --ai-agent <官方 ai_agent 目录>` 做三件事，全部用 marker
`VELAGUARD_SPINE_TASK_TOOLS` 保证幂等，改前留 `<文件名>.codex-pre-spine-tasks` 备份：

1. 把 `board/tool_task.c/.h` 复制到 `src/tools/`；
2. 在 `src/tools/tool_registry.c` 的 `tool_formation_execute);` 之后插入
   `#ifdef CONFIG_EXAMPLES_VELA_SPINE` 块，内含三个 `extern` 声明与三条
   `REGISTER_TOOL(name, description, schema_json, tool_task_*_execute)`；
   （用就地 `extern` 而不是 `#include`，与已验证的只读桥 `install_bridge.py` 同一约定，
   避免 `#ifdef CONFIG_AI_AGENT_FORMATION_TOOL` 头文件嵌套破坏编译）
3. 在 `CMakeLists.txt` 的 formation 源文件块后追加
   `if(CONFIG_EXAMPLES_VELA_SPINE) list(APPEND AGENT_SRCS src/tools/tool_task.c) endif()`。

验证记录（2026-10-26 22:41）：对本仓 `app/vela_mecanum/openvela/ai_agent` 的**临时副本**执行
`--dry-run` → `DRY_RUN 4 edits`、正式应用 → `PATCHED 4 edits`、再跑一次 → `UNCHANGED`；
生成的 diff 存 `设备验收/五项闭环-20261026/evidence/ai-agent-task-tools.patch.diff`。
这证明补丁可应用且幂等，**不等于板端已注册或模型已调用**。

## 3. 真板待办（阻塞，设备恢复后按序执行）

1. 板端 `adb devices` 可见后，用 `install_task_tools.py --ai-agent /data/.../ai_agent` 应用补丁，
   重编 ai_agent 并烧写；或先只在镜像外用同一源码树验证补丁可编译。
2. 板端冒烟：真实模型说“查一下当前任务” → 工具记录里必须出现 `task_status` 与账本回执，
   不是自然语言解释；再“提交计划”“停止 T1”，逐条比对 `tasks.json` 与模拟器 `/v1/state`。
3. 失败路径：不存在的 task_id、带 `speed` 字段的计划、断网时 stop，确认分别返回 2/2/4，
   且账本未被改写。
4. 记录模型原文、工具名、参数、工具回执、账本与模拟器状态，五项缺一不可。

主机侧已证明失败路径语义（`evidence/tool-driver-20261026.log`，见 §4）。

## 4. 证据

- 主机 81 项测试：`Ran 81 tests ... OK`（含 6 个工具用例），`evidence/tests-81-verbose.log`；
- 三工具直达板端执行器的主机驱动（`tool_task.c` 原样、真 C 账本）：
  `SUBMIT→PLAN_PERSISTED`、`SUBMIT_AGAIN→DUPLICATE_PLAN`、`STOP_PENDING→CANCELLED(executor_confirmed=false)`、
  `REUSE_OLD_REVISION→PLAN_VERSION_CONFLICT`、`BUMP_REVISION→PLAN_PERSISTED`、
  `MISSING→TASK_NOT_FOUND`、`BROKEN_JSON→tool_execution_failed`、`STOP_EXTRA_FIELD→code 2`，
  日志 `evidence/tool-driver-20261026.log`；
- 注册补丁 diff：`evidence/ai-agent-task-tools.patch.diff`；
- 账本与协议：`host/BOARD-TASK-PROTOCOL.md`、`host/ROBOT-PROTOCOL.md`；
- 板端证据：**尚无**（真板离线，`adb devices` 无设备）。
