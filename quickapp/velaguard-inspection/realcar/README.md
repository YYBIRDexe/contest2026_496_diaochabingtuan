# 真车联动：按一下「开始巡检」，四台车按预编路线真的动

> 2026-09-20 实机验证。E5 触控屏上那个蓝色的「开始巡检」按钮，现在**真的**会让
> 四台小车动起来 —— 不再是页面内的动画。本文记录怎么用、怎么改、以及踩过的坑。

---

## 零、当前状态（2026-09-20 18:40 冻结）

**功能已完成并实机验证过。** 停在这里的原因不是代码问题：

- 🔋 **小车没电了** —— 用户 2026-09-20 晚指示「暂停对小车的调试」。
  最后几次雷达探测里 **CAR-1 的 `/scan_raw` 四个方向都是 0.00 m**
  （雷达头被挡或探头无数据），另外三台车当时还能正常动。
- ✅ 车端执行器已停到 `idle`，`ros_car.py` 进程数 0 —— **没有车在动，也没有巡检在跑**。
- 📌 充电后再演示时，**先看这一条**：

  ```bash
  # 1) 起执行器（开机本来就会自启，手动也行）
  ssh sunrise@192.168.1.104 "bash ~/velaguard/demo/start-patrol.sh"
  # 2) 体检：这一步会直接告诉你哪台车没空间/没上线，不用猜
  ssh sunrise@192.168.1.104 "bash ~/velaguard/demo/start-patrol.sh --selftest"
  # 3) 屏上点「开始巡检」即可
  ```

  体检不通过时**不会空跑**：它会把「CAR-x 要 0.94 m，雷达只给出 0.94 m」这种话
  直接回给页面，页面右下角的徽标也会写明原因。

- 🎬 **要拍视频**：先读
  `F:\xiaomiaiot\03-大赛送审材料\演示视频\真车版-拍摄须知-20260920.md` ——
  它替换了旧操作单里过时的口径、主镜时长（9 秒 → 30~50 秒）与自检项。
  工具入口：`powershell -File tools\vg.ps1 clearance|reset|patrol-status|shot`。

- ⚠️ **没做完的一件事**：CAR-1 那个「四个方向全 0」的现象**没有查到底**
  （是雷达被挡、还是探头本身的问题，未定论）。充电后先单独验一次 CAR-1 的
  `/scan_raw`，再决定要不要挪车/清障。

---

## 一、30 秒版

```
E5 触控屏（1920×1080）上的蓝色「开始巡检」
   → POST http://127.0.0.1:8127/patrol/start      ← 车端执行器 patrol_controller.py
   → 4 个线程并行，各跑一条预编路线
   → python3 ros_car.py --robots N --cmd FORWARD/STRAFE_* --set distance_m=…
   → ws://192.168.1.20N:9090（rosbridge）→ /cmd_vel
   → 四台车真的动；每 800 ms 把真实进度回灌到界面
```

**实测（2026-09-20 18:16 那一轮，点屏幕触发的）**：四台车全部完成，
`/odom` 逐步实测位移与命令值逐条吻合，净航向漂移 ≤ 0.9°。

| 车 | 区域 | 路线 | 每步命令 → 实测 |
|---|---|---|---|
| CAR-1 | 入口大厅 | 入口→前台→闸机 | 0.90→0.892 ｜ 0.90→0.893 ｜ 0.90→0.894 ｜ 0.90→0.893 m |
| CAR-2 | 主通道 | 通道 A→B 段 | 0.90→0.892 ｜ 0.90→0.893 ｜ 0.90→0.894 ｜ 0.90→0.893 m |
| CAR-3 | 展项区 | 展台 1→4 绕行 | 0.90→0.892 ｜ 0.90→0.893 ｜ 0.90→0.894 ｜ 0.90→0.893 m |
| CAR-4 | 设备区 | 配电柜→机柜背面 | 0.90→0.892 ｜ 0.90→0.894 ｜ 0.90→0.904 ｜ 0.90→0.893 m |

全过程录在车端 `~/velaguard/demo/rounds/round-00N.json`（本目录 `rounds/` 有副本）。

---

## 二、怎么用（照抄）

设备是 `sunrise@192.168.1.104`，SSH 必须带密钥（本机默认身份在设备上没被授权）：

```powershell
$VG = 'F:\xiaomiaiot\02-openvela迁移\openvela-VelaGuard快应用-20260920\tools\vg.ps1'
powershell -ExecutionPolicy Bypass -File $VG ssh 'bash ~/velaguard/demo/start-patrol.sh'
```

| 想干什么 | 命令 |
|---|---|
| 起执行器（页面才连得上） | `bash ~/velaguard/demo/start-patrol.sh` |
| 看它活着没 | `bash ~/velaguard/demo/start-patrol.sh --status` |
| 只校验路线表 | `bash ~/velaguard/demo/start-patrol.sh --selftest` |
| 看日志 | `bash ~/velaguard/demo/start-patrol.sh --log` |
| 停车 + 关执行器 | `bash ~/velaguard/demo/start-patrol.sh --stop` |
| 换演示页（界面改动后） | `bash ~/velaguard/demo/run-demo.sh` |

HTTP 接口（都在 `127.0.0.1:8127`，CORS 全开）：

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/patrol/start` | 下发一轮：体检 → 四车并行跑路线 |
| GET | `/patrol/status` | 当前轮 + 逐车状态 + 逐步实测（界面轮询这个） |
| POST | `/patrol/stop` | 立即给四台车发 STOP 并中止后续动作 |
| POST | `/patrol/reset` | 复位到「尚未开始巡检」 |
| GET | `/health` · `/patrol/routes` | 存活探测 · 当前路线表 |

**开机自启**：`~/.config/autostart/velaguard-patrol.desktop`
（`install-autostart.sh` 装的；先起执行器再拉 E5 页面，因为页面一打开就轮询 8127。
脚本里刻意 `sleep 20` 等旧的 `velaguard.desktop`（8123 看板）先起完 ——
`run-demo.sh` 会杀掉所有 firefox，谁最后跑谁占屏，所以要让演示页确定性地赢）。
不想要就 `bash ~/velaguard/demo/install-autostart.sh --remove`。

**屏幕按钮位置**（1920×1080，用 xdotool 自动化时要用）：

| 按钮 | 屏幕坐标 |
|---|---|
| 「开始巡检」 | `(877, 1019)` |
| 「复位」 | `(1136, 1022)` |

---

## 三、两条路线的差别（**这条最要紧，别搞混**）

路线表 `patrol_routes.json` 的 `safety.route_mode` 决定「每一步往哪走、走多远」：

### `fixed` —— 严格照地图上那四条固定路线

`zones[].steps` 写死：Z1 前进 0.9 → 左横移 0.9 → 前进 0.5，Z2 全程前进 2.6 m ……
和 openvela 快应用 `data.js` 里的 `route_entrance / route_aisle / route_exhibit /
route_equipment` 几何一致（单步 ≤ 0.90 m，总长 2.3~2.7 m）。

**硬前提**：车得按 `placement` 摆好，而且每一步的方向上都要有
`距离 + 0.20 m` 的净空 —— 车端 `ros_car.py` 自带雷达避障，
空间不够会直接**拒动**（退出码 9）。

> 09-20 实测：四台车摆在教室里，前进方向可用空间只有 0.41~0.94 m，
> `fixed` 模式下**四台车全被拒动**。这不是故障，是没地方走。
> 所以 fixed 只适合摆好的场地。

### `adaptive`（默认）—— 同一个形状，交给现场测量

保留闭环矩形巡检的形状（四个原语、每步 ≤ 0.90 m、跑完回出发点），
但每步方向挑**当前空间放得下的那条**，距离取
`min(表里的距离, max_step_m, 该方向可用空间 − 0.20 m)`。两级候选：

1. **四段直线**：`前进 → 右横移 → 后退 → 左横移`（或镜像），四方向两两相反 → 回出发点；
2. **Z 字形兜底**：`前进 → 右转 90° → 右横移 → 左转 90°`（某个方向被堵死时用，
   两次转向把车头带回原朝向，净位移为零）；
3. **单向前扫兜底**：矩形和 Z 字都放不下时，沿唯一有空间的方向
   按可走距离分多段推进（**不回出发点**，形状名会如实写明）。

返回里带 `shape` 字段说明这一轮实际是什么形状，界面/记录里不会把单向扫冒充成闭环路线。

### 出航前体检（`preflight`）

`/patrol/start` 会先逐车检查，任何一项不过就**拒绝派单并说清差多少**：

- `9090` 通不通（rosbridge）
- 电量是否低于 `battery_min`（15%）
- **雷达四个方向各有多少空间**，够不够跑完这次生成的路线

宁可拒绝并告诉你「CAR-4 要 0.94 m，雷达只给出 0.94 m」，也不发一堆注定被拒的指令。

---

## 四、安全边界（不是摆设）

| 机制 | 在哪 | 说明 |
|---|---|---|
| 雷达避障拒动 | 车端 `ros_car.py` | 0.20 m 内有障碍直接否决，**拥有最终否决权** |
| 距离/角度上限 | 车端 | 单步 ≤ 3.0 m、转角 ≤ 180°、速度 ≤ 0.25 m/s |
| 本端夹取 | `patrol_controller.py` | 单步 ≤ 0.90 m、速度 0.15 m/s、超时 40 s |
| 里程计闭环 | 车端 | 每一步按 `/odom` 做到位（实测 0.90 m 命令 → 0.892 m 实际） |
| 航向保持 | 车端 | 横移时用偏航反馈纠偏，实测净漂移 ≤ 0.9° |
| 一键停止 | `/patrol/stop` | 立即给四台车各发一次 STOP，并中止后续步骤 |
| 页面「复位」 | 演示页 | **先** `stopReal()` 停车，再清界面台账（不做假复位） |

**不知道的事，如实说**：车端 `/odom` 是上电清零的相对里程计，**没有全局定位**。
所以路线只能是「相对动作序列」，不能是「去地图上的某个坐标」。
界面地图上画的那四条路线是按 `classroom.pgm` 的坐标系画的，
和真车当前实际位置**没有实时对应关系** —— 这一点在演示口径上要守住。

### 实测过的两条安全行为

| 场景 | 做法 | 结果 |
|---|---|---|
| 行进中调 `POST /patrol/reset` | 下发一轮，等 8 秒（四车都在走），再调复位 | 0.386 s 返回「已复位；同时向四台车发送了停止指令」；复位后 2 s 与 9 s 两次读 `/odom`，四台车坐标**逐字节不变** → 全部停住 |
| 行进中点屏幕「复位」 | 下发一轮，等 7 秒，`xdotool` 点 `(1136,1022)` | 车端状态 `running → idle`，消息「尚未开始巡检」 → 按钮这条路径也会停车 |

> ⚠️ 复位**必须**先停车再清状态。原来只清状态：演示者点了复位、界面回到干净画面，
> 车却还在往前走。`reset_state()` 现在会置 ABORT、杀掉当前步骤的子进程，
> 并无条件给四台车各补发一次 STOP（即使没在跑也发，防车端残留速度指令）。

---

## 五、界面这一侧改了什么

演示页 `demo-e5.html` 的宿主脚本加了一段「真车联动」（源码在
`tools/build-demo-e5.js`，用 `tools/_patch_demo_realcar.js` +
`_patch_demo_realcar2.js` 打的补丁，都可幂等重跑）：

| 行为 | 说明 |
|---|---|
| 点「开始巡检」 | **先** `POST /patrol/start`；车端不接就**不演界面**，并在徽标上写明原因 |
| 每 800 ms | 拉 `/patrol/status`，把真实状态/进度写进应用状态机 |
| 状态徽标 | 常驻显示「真车联动就绪 / 第 N 轮 · 执行中 4/4 / 全部完成 / 未连接 + 恢复命令」 |
| 四车都收工 | 自动 `closeRound()` 归档，并重绘一次（否则记录页还显示旧内容） |
| 点「复位」 | 先停车、再清台账、再 `/patrol/reset` |

**改完必须重跑产物**：

```powershell
cd F:\xiaomiaiot\02-openvela迁移\openvela-VelaGuard快应用-20260920
node tools/_patch_demo_realcar.js --check     # 看补丁状态
node tools/build-demo-e5.js                   # 重新生成 build/demo-e5.html
```

然后把 `build/demo-e5.html` 传到设备 `~/velaguard/demo/demo-e5.html`，
跑 `run-demo.sh` 重载 kiosk。

---

## 六、踩过的坑（都实测过，别再踩）

| # | 坑 | 现象 | 修法 |
|---|---|---|---|
| 1 | `store.tasks` / `store.round` **没导出** | 页面弹「真车联动未连接：store.tasks is undefined」 | 改用导出的 `store.zoneStates()` 拿任务对象 |
| 2 | 取状态用「内部表」而不是公开接口 | 同上，且进度数字对不上 | `zoneStates()` 的 progress 就是界面显示的那个数，来源唯一 |
| 3 | `--set` 被三元表达式卷进去 | 四台车全部 `argument --set: expected one argument` | 先把值算好，再拼 argv |
| 4 | 子进程中文输出按 locale 解码 | `measured_m` 永远是 `None`（实测值解析不出来） | 设 `PYTHONIOENCODING=utf-8`，并用正则取**第一个**数 |
| 5 | 出航前量的空间和发指令时差 1~3 cm | 体检说能走、发指令被拒 | 加 0.03 m 容差 + 被拒后按 0.7/0.4 倍距离自动重试（只会更短） |
| 6 | 转向会换车头方向 | 掉头兜底算错空间，误判「没有空间」 | 逐步累计 θ，用 `rotate_key(op, θ)` 查对应方向的空间 |
| 7 | 往返路线只按出行方向留空间 | 车出去了回不来，第 3 步被拒 | 往返距离取同轴两个方向的较小者 |
| 8 | 归档后不重绘 | 四车全完成、徽标也对，记录页仍写「历史轮次（0 条）」 | `closeRound()` 后显式 `__vg.render()` |
| 9 | 补丁幂等判据用了通用字符串 | 补丁②静默不生效（`store.zoneStates()` 在 bundle 里本来就有） | 判据必须用**只属于该补丁**的代码 |
| 10 | 设备没有 ImageMagick | `xwd` 抓的图没法转 PNG | `probe/xwd2png.py`：XWD 头 25×u32 + 窗口名 + 色表，之后是 32bpp 像素 |
| 11 | 复位只清状态不停车 | 点了复位，界面干净了、车还在走 | `reset_state()` 先 `stop_all()` + 杀子进程 + 补发 STOP（见第四节实测） |
| 12 | 两个 autostart 抢屏 | `run-demo.sh` 杀所有 firefox，谁后跑谁占屏 | 新自启脚本先 `sleep 20`，让演示页确定性地赢 |

---

## 七、文件清单

本目录（`真车联动-20260920\`）：

| 文件 | 说明 |
|---|---|
| `device\patrol_controller.py` | 车端执行器（纯标准库，Python 3.8 可用，无第三方依赖） |
| `device\patrol_routes.json` | 路线表 + 安全参数 + `route_mode` |
| `device\start-patrol.sh` | 起/停/查/自检 执行器 |
| `device\start-demo-with-patrol.sh` | 先起执行器、再拉 E5 页面 |
| `device\install-autostart.sh` | 装/卸开机自启（xdg autostart） |
| `demo-e5.html` | 带真车联动的演示页产物（= 设备上跑的那一份） |
| `rounds\round-00N.json` | 每轮的逐步证据（命令值 / 实测值 / odom 位移 / 航向漂移 / 出航前雷达空间） |
| `证据截图\*.png` | 01 链路就绪 ｜ 02 点击后 8 秒四车执行中（地图页）｜ 03 跑完并归档（记录页）｜ 04 未连接时的提示 ｜ 05 行进中点复位后立刻停住 ｜ 06 复位后回到待执行 |
| `实测脚本\*.py` | 复现用的探针：`read_odom.py`（读四车位置）· `check_clearance.py`（读四车四方向可用空间）· `calib_单步标定.py`（单车单步标定，四个方向各走一次）· `run_round.py`（远端下发一轮并全程观察）· `xwd2png.py`（设备没装 ImageMagick，用它把 xwd 转 PNG） |

> 截图与 `rounds\` 里的 JSON 是**同一批实测**：第 2 轮（点屏幕触发的完整一轮，
> 四车全绿）与第 3 轮（复位安全测试，刻意中途打断）。
> ⚠️ `rounds\round-00N.json` 是**按轮号命名、会被新轮次覆盖**的
> （round-002 的内容就是被后一轮覆盖过的）—— 要看某一轮的确切细节，对时间戳。
> 这是车端 `write_round_log()` 的现有行为，没改；要留档就自己复制一份。

工程内相关文件：

| 文件 | 说明 |
|---|---|
| `tools\build-demo-e5.js` | 演示宿主模板（**改界面改这里**，`build/demo-e5.html` 是生成物） |
| `tools\_patch_demo_realcar.js` | 补丁①：徽标 + 联动逻辑 + 按钮改写 |
| `tools\_patch_demo_realcar2.js` | 补丁②：改用 `zoneStates()` + 徽标位置 + 收轮重绘 |
| `tools\build-demo-e5.js.bak-before-realcar*` | 打补丁前的模板备份（回滚用） |
| `docs\真车联动说明.md` | 原来那份「地图与路线」文档的配套说明（本文件） |
