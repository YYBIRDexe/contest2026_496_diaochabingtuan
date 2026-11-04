# 三车网络模拟协议 v2

端侧任务接口的 PC 模拟实现，v2 加入执行器停止动作与 STOP_CONFIRMED 终态，用于配合 Gemini 原生 C 任务账本（`native/task.c`）。模拟器自身仅监听 127.0.0.1；可通过 `board_sim_network` 限定源 IP 的转发供真板连接。已进行真板与模拟器测试；没有真实导航或真实车端认证。所有输入必须 `mode=simulation`，ACK 只代表 PC SQLite 提交；禁止据此显示真车完成。S1 左岸、S2 右岸、S3 机房是默认展示角色，协议不把区域硬编码为可达性证明。

## 运行

在 app/vela_spine 目录运行：

```sh
python -m host.robot_simulator --database var/robots.sqlite3 --port 18140
python -m host.robot_network_demo --output var/robot-network-new-run
python -m unittest discover -s tests -p test_robot_simulator.py -v
```

数据库父目录需存在；demo 必须使用全新目录，自动关闭服务并保存数据库和逐条 HTTP 请求/应答 report.json。可用 `--offline S2` 模拟整次服务期间该车不可达；测试在运行中注入 503 和恢复。服务与 8130/8132/8133 无关联。

## HTTP 和消息

POST /v1/commands，JSON 最多 4096 字节，拒绝重复键、未知字段及非法值。GET /v1/state 返回每辆车最近的一条任务状态（最多三条），历史任务仍保存在 SQLite；这样状态消息不会随历史增长而超过当前 Gemini HTTP 2 KB 响应上限。三辆逻辑车共享一个测试端点，并非三个真实车端进程。对于同一辆车，模拟器在已有非终态任务时拒绝新分配，指挥端也不得在旧任务未确认终结时重复授权。

分配：

```json
{"schema":"spine-robot-sim-v1","mode":"simulation","command_id":"assign-S1-1","robot_id":"S1","task_id":"inspect-D1","revision":1,"action":"ASSIGN","tag_id":"D1"}
```

执行回报由测试驱动显式注入，不自动把时间流逝视为到点：

```json
{"schema":"spine-robot-sim-v1","mode":"simulation","command_id":"run-S1-1","robot_id":"S1","task_id":"inspect-D1","revision":1,"action":"REPORT","state":"RUNNING","sequence":1}
```

停止请求（v2 新增）：指挥端发出 STOP，执行器必须实际确认停止后才回 STOP_CONFIRMED：

```json
{"schema":"spine-robot-sim-v1","mode":"simulation","command_id":"stop-inspect-D1-1","robot_id":"S1","task_id":"inspect-D1","revision":1,"action":"STOP"}
```

STOP 的应答是任务快照 `state=STOP_CONFIRMED`、`sequence` 已加 1。车辆/版本不符返回409。同一命令重试返回原应答。若完成/失败与停止请求竞态，执行器仍应显式确认旧任务已静止；PC模拟器仅在该车辆没有另一活动任务时允许将终态任务转为 STOP_CONFIRMED，否则拒绝旧任务的 STOP。序号达到上限时拒绝，不能溢出后继续授权。

ACCEPTED→RUNNING→COMPLETED；RUNNING 可进入 BLOCKED，BLOCKED 只能恢复 RUNNING 或终止 FAILED/CANCELLED。ACCEPTED 也允许 FAILED/CANCELLED。`STOP_CONFIRMED` 是 v2 的第四个终态，只能由 STOP 动作进入，不能由 REPORT 伪造。终态不再接收 REPORT 转换，只有上述明确 STOP 确认例外。sequence 必须逐次加 1，错序拒绝后由发送方补齐，不能跳过回执。CANCELLED 是模拟执行器确认已取消，不是指挥端仅发出取消请求。

HTTP200 返回 persisted=true、ack_scope=SIMULATOR_STORAGE_ONLY、motion=false 及命令生效时的任务快照。相同 command_id 和正文重试返回原应答；历史 ACK 不是实时状态，要查询 /state。同 ID 不同正文 409；业务冲突 409 且 persisted=false；注入离线或存储失败 503，不得当完成或释放任务。SQLite 事务提交后才允许发 ACK。

task_id 全局唯一，首次 revision=1；仅终态允许下一版本（严格+1）再分配。板端自动生成的 `assign-任务ID-版本` 必须不超过 64 字节，故版本为 1 时任务 ID 最多 55 字节，版本位数增加时可用长度相应减少。源码已新增计划落盘前的检查；**当前板端已部署该检查，并在真板验证55字节接受、56字节拒绝且账本不变；客户端仍应遵守长度限制**。非终态任务只有一个 robot_id，单车同时最多一个非终态任务（STOP_CONFIRMED 也释放车辆）。旧版本/错误车辆回报不能更新新版。数据库重开保留命令去重和任务，离线注入属于测试配置，不保存为业务状态。

## 与板端账本的关系

`native/task.c` 已在真板部署，通过本协议派单与收账：POST /v1/commands 的 ASSIGN/STOP、GET /v1/state 的实时状态。板端只在收到 `persisted=true` 且 `state=ACCEPTED` 后才把任务记为 DISPATCHED，ACCEPTED 不是完成；收到 STOP_CONFIRMED 才把任务记为停止完成并释放归属。协议细节与账本状态机见 `BOARD-TASK-PROTOCOL.md`。

## 边界与下一步

目前验证包括真板、PC 模拟器和隔离模拟平台；没有真实车端认证、心跳超时、租约或物理安全停车验证。真实车端接入还须设备身份、独立连接、新鲜度和物理执行验证。断线保留归属，不能凭超时自动改派。SQLite 命令历史目前不清理，仅用于有限验收回放；长期服务需要容量策略。
