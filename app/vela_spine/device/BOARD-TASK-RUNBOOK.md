# 真板任务账本部署与验收手册（B/C/E 板端部分）

状态：**全部步骤未在真板执行**（2026-10-26 22:50 真板离线，`adb devices` 仅 `emulator-5562 offline`）。
本手册是恢复设备后的操作顺序，不是已完成记录。每步都要保存原始输出，命令与输出一起归档。

## 0. 前置检查（缺一即停，不要跳步）

```bash
adb devices                       # 必须出现真板序列号且状态 device
adb shell "uname -a; ls -l /data/ai_agent/sp 2>&1"
adb shell "/data/ai_agent/bin/vela_spine --task-view /data/ai_agent/sp"   # 路径以实测为准
```

判定：
- 无设备 → 停，报告"真板离线"。
- `--task-view` 报 `unknown command`/`Unsupported` → 说明现有镜像**不含任务账本**，
  必须先重编镜像（当前 Windows/Ubuntu 两侧都没有 ARM 工具链与 vendor 树，需先解决构建环境）。
- 有输出但 `TASK_LIST` 为空 → 正常，可继续。

## 1. 板端账本冒烟（不涉及网络）

```bash
adb shell "cat > /data/ai_agent/sp/plan1.json" <<'JSON'
{"schema":"spine-plan-v1","plan_id":"board-p1","version":1,
 "tasks":[{"task_id":"B1","tag_id":"D1","robot_id":"S1","revision":1}]}
JSON
adb shell "vela_spine --task-plan /data/ai_agent/sp/plan1.json /data/ai_agent/sp"   # 期望 PLAN_PERSISTED
adb shell "vela_spine --task-view /data/ai_agent/sp"                                # 期望 T1/B1 PENDING
adb shell "cat /data/ai_agent/sp/tasks.json"                                        # 期望 schema/crc32/tasks
```

重启保持（关键验收）：`adb reboot` → 等待回连 → 再 `--task-view`，任务仍在且状态未变；
重复同一条 `--task-plan` 应得 `DUPLICATE_PLAN`，不是第二次派单。

## 2. 板端向 PC 三车派单（真网络回执）

PC 侧先起模拟器（仅回环/内网，非公网）：

```powershell
python host\robot_simulator.py --database F:\xiaomiaiot\_tmp\board-20261027\fleet.db --port 18140
```

板端与 PC 连通性二选一（按现场网络能力，二选一即可，不要同时开）：
- 板子与 PC 同网段：`adb shell "vela_spine --task-dispatch /data/ai_agent/sp <PC_IP>:18140"`；
- 只通 USB：`adb reverse tcp:18140 tcp:18140` → 板端用 `127.0.0.1:18140`。

期望：`DISPATCHED` + 模拟器 `state=ACCEPTED`（**只是接单**）；
`--task-poll` 在模拟器 `REPORT RUNNING` 后得 `REPORT_APPLIED`，`COMPLETED` 后才 `COMPLETED`。
断开模拟器再 `--task-dispatch`：期望 `PARTIAL_NETWORK_ERROR`/`UNREACHABLE`，本地仍 `PENDING`，
模拟器无该任务，恢复后重派成功（不凭超时改派）。

## 3. 风险联动与停止确认（C 项）

```bash
adb shell "vela_spine --ingest /data/ai_agent/sp/risk92.json /data/ai_agent/sp"   # 92 分 IMMEDIATE
adb shell "vela_spine --task-dispatch /data/ai_agent/sp <endpoint>"               # 期望 RISK_STOPPED
adb shell "vela_spine --task-view /data/ai_agent/sp T1"                          # 期望 STOP_CONFIRMED 或 STOP_REQUESTED
```
判定：
- 未收到执行器 `STOP_CONFIRMED` 前，任务不能算释放（`robot_released=true` 只在 `STOP_CONFIRMED`/`CANCELLED`）。
- 人工在平台关闭该事件后，再 `--task-plan` 同 tag 的新计划仍应 `HELD_BY_RISK`
  （只有更高 version 的新计划重写该行才解除），证明"不经人工确认不自动恢复"。

## 4. 平台与人工链（不触碰 8130）

```bash
ssh -i <key> sunrise@192.168.137.134 "cd /home/sunrise/vela-spine-w2-20261022 && python3 deploy_platform.py"
```
期望 `"production_8130_unchanged": true`；8132 接收板端告警、8133 人工接单→提交处理→复核关闭，
关闭需板端回签（`STALE_REVISION` 旧版本必须拒绝）。这条链路 2026-10-25 已验过，本轮只需回归。

## 5. 证据归档

每步保留：命令、原始 stdout/stderr、`tasks.json`、模拟器 `/v1/state`、时间戳、固件 SHA256 与源码提交。
主机跑出来的结果必须标注 `board_verified=false`；只有真板跑出来的才能进"板端证据"。
