# 巡检状态 JSON 格式（M1 侧写入）

界面通过 `GET /data/state.json` 轮询这个文件。**M1 侧只要按下面的字段写 JSON，
界面就会自动跟着变**，不需要改界面的任何代码。

- 文件位置：`data/state.json`（相对于工程目录）
- **轮询间隔：5 秒**（2026-09-19 起；原来是 2 秒 —— 用户要求"每 5 秒根据检测的参数
  更新一次页面数据"，两边节奏对齐）
- 编码：UTF-8
- 建议先写 `.tmp` 再改名，避免界面读到半截 JSON（`linux/car_state.py` 与
  `tools/simulate-m1.js` 都是这么做的）

> **设备上是谁在写这个文件**：`linux/car_state.py`（systemd 服务 `velaguard-cars.service`）。
> 它每 5 秒真去探测四台车：TCP 9090 判在线、订阅 `/ros_robot_controller/battery` 读电量，
> 然后写进 `cars[]`；`zones[]` 的"任务进度"是演示叙事（车端不上报任务状态），
> 但**车一离线，对应区域就会被写成 `offline`**，`detail` 里也是真实探测结果。
> 手动跑一次看结果：`cd ~/velaguard/linux && python3 car_state.py --once --verbose`


---

## 完整示例

```json
{
  "round": 3,
  "generatedAt": "2026-09-18T20:15:00+08:00",
  "zones": [
    {
      "id": "Z1",
      "name": "入口大厅",
      "route": "R-01",
      "routeDesc": "前台 → 闸机 → 电梯口",
      "car": "CAR-1",
      "status": "done",
      "progress": 100,
      "detail": "地面无杂物，闸机通行正常",
      "duration": "3 分 12 秒"
    }
  ],
  "cars": [
    {
      "id": "CAR-1",
      "zone": "入口大厅",
      "ip": "192.168.4.11",
      "online": true,
      "battery": 86
    }
  ],
  "records": [
    {
      "round": "第 3 轮",
      "time": "今天 14:20",
      "zones": [{ "name": "入口大厅", "result": "done" }],
      "summary": "3 区已收回结果，1 区阻塞待重派"
    }
  ]
}
```

---

## 字段说明

### zones（必填）—— 区域与任务状态

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 是 | 区域编号，如 `Z1`。界面的派单/取消指令按它定位 |
| `name` | string | 是 | 区域名，如 `入口大厅` |
| `route` | string | 否 | 路线编号 |
| `routeDesc` | string | 否 | 动作序列，给运维看的 |
| `car` | string | 否 | 责任车辆编号，须与 `cars[].id` 对应 |
| `status` | string | 是 | **只认这五个值**：`done` / `running` / `blocked` / `idle` / `offline` |
| `progress` | number | 否 | 0–100 |
| `detail` | string | 否 | 一句话说明，会显示在调度台与语音助手的回答里 |
| `duration` | string | 否 | 用时文案 |

`status` 与界面显示的对应关系：

| status | 显示 |
| --- | --- |
| `done` | 已完成（绿） |
| `running` | 进行中（蓝） |
| `blocked` | 阻塞（红） |
| `idle` | 未开始（灰） |
| `offline` | 离线（黄） |

> 注意：如果某区域的 `car` 对应车辆 `online: false`，
> 界面的汇总会把该区域计为**离线**，而不是它的 `status` 值。

### cars（建议填）—— 车辆状态

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 车辆编号，如 `CAR-1` |
| `zone` | string | 所属区域名 |
| `ip` | string | 车辆地址（C1 链路） |
| `online` | boolean | 是否在线 |
| `battery` | number | 电量百分比 |

### records（可选）—— 历史轮次

不填时界面会沿用内置的历史记录。填了就按你给的显示，
用于「巡检记录」页与按轮次回看。

| 字段 | 说明 |
| --- | --- |
| `round` | 轮次名，如 `第 3 轮` |
| `time` | 时间文案 |
| `zones[].name` | 区域名 |
| `zones[].result` | 同样是那五个状态值 |
| `summary` | 一句话结论 |

---

## 指令下发（界面 → M1）

界面上的派单 / 取消 / 一键取消会 `POST /api/command`，
M1 侧接收后执行，并把新状态写回 `state.json`。

请求体：

```jsonc
// 派单
{ "action": "dispatch",  "zoneId": "Z4", "at": 1758192000000 }

// 取消单个区域
{ "action": "cancel",    "zoneId": "Z4", "at": 1758192000000 }

// 一键取消全部未完成
{ "action": "cancelAll", "at": 1758192000000 }
```

`tools/serve.js` 收到后会追加写入 `data/commands.log`，
M1 侧可以轮询这个文件作为最简实现；也可以自己实现一个等价的 HTTP 接口，
把界面 `src/common/source.js` 里的 `commandUrl` 指过去。

---

## 快速验证链路（不需要真机）

```bash
# 终端 A：起服务
node tools/serve.js 8123

# 终端 B：模拟 M1 持续写状态
node tools/simulate-m1.js
```

浏览器打开 <http://127.0.0.1:8123/>，点状态栏右侧的**数据源标签**
切到「M1 数据」——之后界面会跟着 `state.json` 每 2 秒刷新一次：
任务从「未开始 → 进行中 → 已完成／阻塞」自己走起来。

---

## 用 file:// 打开时怎么办

浏览器禁止 `file://` 页面发起 `fetch`，所以**数据接口只能在 http 下工作**。
用 `file://` 直接双击打开时，界面会自动停留在**演示数据**模式
（点数据源标签会提示不可用），不会白屏也不会报错。

正式部署请用 http 方式，见 `docs/部署到M1-Linux.md`。
