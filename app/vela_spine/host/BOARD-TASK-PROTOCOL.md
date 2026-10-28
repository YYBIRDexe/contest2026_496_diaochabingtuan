# 板端任务账本协议 v1（spine-plan-v1）

这是端侧任务闭环的板端契约。实现位于 `native/task.c` / `native/task.h`，与事件账本 `native/store.c` 并列但互不替代。2026-10-28 已在真实 Gemini-S1 与 PC 模拟三车验证派单、风险停止、人工闭环、断网和重启。本文所述车辆均为模拟，不代表真实车辆运行。

## 三段接口

```
平台/测试客户端 --(1 提交计划)--> 板端任务账本 --(2 ASSIGN/STOP)--> 车辆执行器(当前=PC 三车模拟器)
                 <--(4 状态查询)---            <--(3 回执/实时状态)---
```

1. 提交计划：`--task-plan FILE ROOT`，JSON 为 `spine-plan-v1`（下节）。计划先落盘再谈派单，落盘成功才返回 `PLAN_PERSISTED`。
2. 派单：`--task-dispatch ROOT ENDPOINT`，先将 PENDING 持久化为 DISPATCHING，再向 `POST /v1/commands` 发 ASSIGN（见 `ROBOT-PROTOCOL.md`）；意图保存失败时不发送网络请求。重试 DISPATCHING 使用原命令 ID。仅当应答 `persisted=true`、`motion=false`、`ack_scope=SIMULATOR_STORAGE_ONLY` 且任务 `state=ACCEPTED`、`task_id/robot_id/revision` 与请求一致，才把本地状态写成 DISPATCHED。**ACCEPTED 不代表执行完成。**
3. 回执：`--task-poll ROOT ENDPOINT` 读 `GET /v1/state`；只更新已派单任务；`sequence` 必须严格递增，旧回执丢弃，错车辆/错版本记 `VEHICLE_STATE_CONFLICT` 且不改本地状态；网络失败直接返回 4，**任何超时都不改状态、不释放归属、不重派**。
4. 查询：`--task-view ROOT [TASK_ID]`。

## 计划格式

```json
{"schema":"spine-plan-v1","plan_id":"p1","version":1,
 "tasks":[{"task_id":"T1","tag_id":"D1","robot_id":"S1","revision":1}]}
```

- 键集严格：顶层 `{schema,plan_id,version,tasks}`，任务 `{task_id,tag_id,robot_id,revision}` 加可选 `priority`；未知键或重复键整单拒绝。
- `task_id`/`tag_id` 单次计划内不得重复；显式 `robot_id` 不得重复；`robot_id` 允许 `AUTO`，由 `sp_allocate` 在“未被显式占用”的机器人池里求解，解不出则整单拒绝（不做半截分配）。
- 版本：`version < stored` → `STALE_PLAN_REJECTED`；`==` 且计划 ID 或内容不同 → `PLAN_VERSION_CONFLICT`；`==` 且计划相同 → `DUPLICATE_PLAN`（幂等，不重复派单）；`>` 才写入。
- 任务版本：新任务必须 `revision=1`；已终态任务重派必须 `revision=旧+1`；非终态任务再次授权 → `DOUBLE_AUTHORIZATION_REJECTED`（同一任务不会获得双重授权）。

## 账本文件

`ROOT/tasks.json`：`{"schema":1,"crc32":"%08lx","plan_id","plan_version","tasks":[...],"commands":[...]}`。
每条任务字段：`task_id,plan_id,tag_id,robot_id,plan_version,revision,state,vehicle_state,sequence,dispatch_id,stop_id,note`。
`commands` 是命令日志（最多 64 条，超出丢最旧），字段 `command_id,kind,request_crc,result`；命令 id 是确定性的 `assign-<task_id>-<revision>` / `stop-<task_id>-<revision>`，同一 id 不同请求体直接拒绝，重试只返回原结果。

持久化纪律与事件账本一致：`ROOT/task.lock` 上加 `fcntl(F_WRLCK)`；先写 `tasks.tmp` → `fsync` → `close` → `rename` 覆盖 `tasks.json`；上限 131072 字节；读取时校验 schema、CRC32、状态枚举、机器人枚举、sequence 非负、task_id 唯一。**任何校验失败都返回退出码 3 且不重建、不覆盖原文件**；模块不提供“修复/清空”入口。

## 状态机

```
PENDING --发送前落盘--> DISPATCHING --有效ACK--> DISPATCHED --回执--> RUNNING/BLOCKED
   |                       |                     |                     |
   |                       +------风险/人工停止---+---------------------+
   |                                             v
   +--从未尝试派单即停止--> CANCELLED          STOP_REQUESTED --停止确认--> STOP_CONFIRMED
```

终态：`COMPLETED / FAILED / STOP_CONFIRMED / CANCELLED`。`STOP_REQUESTED` 不是终态，归属不释放，直到执行器回 `STOP_CONFIRMED`。

DISPATCHING 表示任务可能已被执行器接收；超时、错误 ACK 或确认保存失败均不能将其当作“从未发送”。只能使用原命令重试，或转 STOP_REQUESTED 等待执行器确认，不能本地取消并释放车辆。原子保存发送意图时也复查任务状态和车辆占用，避免并发停止后仍发送新授权。普通任务在未请求停止时可由有效回执进入 COMPLETED/FAILED；一旦进入 STOP_REQUESTED，迟到的 COMPLETED/FAILED/CANCELLED 只更新执行器状态及递增序号，不释放归属，必须显式 STOP_CONFIRMED。

2026-10-28 发送意图加固正在进行真板部署验收；旧固件的 PENDING 可能包含曾尝试发送的任务，升级或迁移前需对照执行器核查，不可直接视为未发送。新状态账本不能直接交给不认识 DISPATCHING 的旧固件使用。

## 风险联动

- 派单前对每辆车查事件账本 `sp_store_tag_risk(ROOT_tasks, tag_id)`：命中 `IMMEDIATE`（评分 > 阈值并锁存）→ 本地标记 `HELD_BY_RISK`；命中 `REVIEW` → `HELD_HUMAN_REVIEW`。被标记的 PENDING 任务**冻结在账本里**，之后即使人工关闭事件也不会自动恢复旧授权；只有更高 `version` 的新计划显式重写该行才重新授权。
- 同一次派单还会扫描已派单/运行中的任务：其 tag 命中 `IMMEDIATE` 时自动发出 STOP，收到执行器 `STOP_CONFIRMED` 才转终态并释放归属；应答里的 `stops` 数组给出逐任务结果，整体 `status=RISK_STOPPED`（当次没有新的可派任务时）。
- 封锁按 tag 局部进行，不做全图封锁；人工关闭只解除该事件的待办，不解除已冻结任务，也不写回旧分数。

## 命令与退出码

| 命令 | 说明 |
|---|---|
| `--task-plan FILE ROOT` | 写入计划，返回 `PLAN_PERSISTED` / `DUPLICATE_PLAN` / `PLAN_VERSION_CONFLICT` / `STALE_PLAN_REJECTED` / `DOUBLE_AUTHORIZATION_REJECTED` / `REJECTED` |
| `--task-dispatch ROOT ENDPOINT` | 派单+风险停止，返回 `DISPATCH_STEP` / `RISK_STOPPED` / `NOTHING_TO_DISPATCH` / `PARTIAL_NETWORK_ERROR` |
| `--task-poll ROOT ENDPOINT` | 拉实时状态，返回 `POLLED`（含每任务 `local_state/vehicle_state/sequence/note`：`REPORT_APPLIED` / `DUPLICATE_REPORT` / `STALE_PROGRESS_IGNORED` / `VEHICLE_STATE_CONFLICT`） |
| `--task-stop ROOT TASK_ID [REASON]` | 请求停止：`STOP_REQUESTED` / `CANCELLED` / `ALREADY_REQUESTED` / `STOP_NOT_REQUIRED` |
| `--task-stop-sync ROOT ENDPOINT` | 发送 STOP 并等执行器确认：`STOP_CONFIRMED` 才转终态 |
| `--task-view ROOT [TASK_ID]` | 读账本 |

退出码：`0` 成功；`2` 参数或计划校验失败（未产生任何状态变化）；`3` 账本损坏或存储失败；`4` 网络或回执校验失败。批量操作可能在某一项失败前已成功处理其他项；执行器可能已经接收，而本地持久化尚未成功，必须逐项核对并使用原命令 ID 幂等重试，不能把非零返回理解为“什么都没发生”。源码已修复部分保存失败误报成功的路径，当前真板已部署该修复并完成模拟闭环回归；存储故障注入验证在主机执行。所有应答都带 `motion:false`；派单类应答带 `ack_scope=REMOTE_STORAGE_ONLY`，账本类应答带 `ack_scope=LOCAL_STORAGE_ONLY`。

## 未实现（红线）

设备身份认证与签名、心跳/租约、区域禁入、车端物理安全停车、真实导航或运动、云端完整协商与自动重规划均未验证。AUTO 当前采用模拟的等成本、等资格和每车一个任务配额；不是实际电量、能耗或可达性验证。派单成功只证明模拟器持久化接收，不得据此声称真实车辆已运动或任务已完成。

账本加载补强（待板端部署）：拒绝尾随非JSON内容、重复根字段及非整数schema；损坏文件不自动重建或覆盖。执行器在未请求停止时确认CANCELLED可转终态；已有STOP_REQUESTED时仍等待STOP_CONFIRMED。
