# VelaGuard——多机器人分区巡检与异常闭环系统

> **2026 首届 openvela AI 硬件开发者大赛** · 参赛作品仓
> **队伍**：调教小车太难了 ｜ **选题方向**：AI 硬件产品创新
> **作品形态**：**快应用**（`quickapp/velaguard-inspection/`）→ 映射到 `packages/apps/contest2026_496_velaguard-inspection`
> **报名硬件形态**：模拟器（Vela Emulator `goldfish-arm64-v8a-ap`，720×1280 竖屏）

---

## 一、作品简介

面向园区 / 厂区巡检场景的**自然语言调度与安全监督系统**。

说一句「开始巡检」，端侧 AI Agent 理解意图、按自定义 Skill 编排任务并**主动**上报异常；
边缘层把任务单下发给多台 ROS 2 麦克纳姆小车，驱动它们完成四区分区巡检；
触控看板实时呈现任务状态、覆盖情况与异常闭环。

**要解决的问题**：传统多机器人巡检依赖人工逐台派单、人工盯屏，异常发现滞后。
本作品把「派单 → 执行 → 回执 → 异常告警 → 汇总」做成闭环，
并把**主动告警**（而非被动问答）作为核心交互形态——这正是赛题对
「纯对话机器人」的排除条款所指向的能力。

**亮点**

- **主动 + 执行**：异常回执到达即触发主动播报与上下文提醒，不等用户提问
- **端侧 AI**：快应用通过官方 `@system.velaclaw` 通道调用端侧 AI Agent，并展示它调了哪些工具
- **自定义 Skill**：以 Markdown 沉淀区域表与车辆映射、任务单字段与回执语义、阻塞/失联判定阈值与处置流程、安全规则
- **地图是真的**：地图为车端真实 ROS 地图 `classroom.pgm` 自动转出的矢量轮廓（55 个墙块），非占位图

**系统架构**

```text
┌──────────────────────────────────────────────────────┐
│ ① 触控交互层 —— VelaGuard 快应用（本仓 quickapp/）     │
│   · 七个视图：桌面/调度台/地图与路线/区域与任务/        │
│     巡检记录/语音助手/系统与链路                       │
│   · 端侧 AI 对话：@system.velaclaw.ask()              │
│   · 自定义 Skill：skills/inspection.md                │
└───────────────┬──────────────────────────────────────┘
                │ 端侧 Agent 通道 / HTTP
                ▼
┌──────────────────────────────────────────────────────┐
│ ② 边缘层 —— U2P(X3M, Ubuntu) / M1 实训箱              │
│   · VelaGuard 看板（本仓 edge-dashboard/）             │
│   · 车端执行器 patrol_controller.py（realcar/）        │
│   · 语音链路（唤醒 → ASR → 意图 → 下发 → TTS 播报）     │
└───────────────┬──────────────────────────────────────┘
                │ ws://…:9090  rosbridge → /cmd_vel
                ▼
        四台 ROS 2 麦克纳姆小车（车端本地安全逻辑最高优先）
```

---

## 二、选题方向

**AI 硬件产品创新**。作品落地 openvela 的 **AI**（端侧 Agent、Skill 加载器、主动任务、记忆机制）
与 **多媒体**（端侧语音交互链路）能力。

---

## 三、作品代码在哪（目录结构）

```text
/
├── README.md                            本文件
├── contest2026_496_diaochabingtuan.xml  本仓清单（含 1 条快应用 <linkfile>）
├── openvela.xml                         openvela 全量工程清单（未改动）
├── quickapp/
│   └── velaguard-inspection/            ★ 作品形态：快应用源码工程
│       ├── src/                         源码（唯一需要手改的地方）
│       │   ├── manifest.json            包名 com.velaguard.inspection，720×1280
│       │   ├── app.ux.tmpl              openvela 入口模板
│       │   ├── app-shell.js             宿主无关外壳（250ms tick、切页、事件派发）
│       │   ├── common/                  data / map / store / agent / tpl / ui / router
│       │   └── pages/                   七个视图（Home/Dispatch/Map/Zones/Records/Voice/System）
│       ├── tools/                       19 个脚本：测试、打包、地图转换、产物自检
│       ├── skills/inspection.md         ★ 自定义 Skill（赛题必做项）
│       ├── device/                      E5 触控屏演示宿主（可跑、可录）
│       ├── realcar/                     真车联动：车端执行器 + 路线表 + 逐轮实测证据
│       ├── dist-openvela/               部署产物 app.ux + manifest.json（生成物）
│       └── docs/                        部署、命令单、地图与路线、拍摄执行单
├── edge-dashboard/                      边缘层工程（M1/U2P，Node + Python，不参与 openvela 编译）
├── app/
│   └── vela_mecanum/                    ★ 第二件作品：四车自主编队（应用形态）
│       ├── openvela/                    openvela 端 ai_agent 改造 + Formation Lab + ROS 2 bringup
│       ├── outputs/formation-kit/       当前四车任务控制程序与现场任务记录
│       ├── work/                        部署、诊断、定位、安装与验收工具
│       ├── docs/                        代码索引 / 验收状态 / 测试结果 / 移交说明
│       └── 作品说明.md                  该作品的完整说明（简介 / 运行方式 / 验收结果）
└── logs/                                AI Coding 日志，一人一目录
```

### 各目录为什么放这里

| 目录 | 形态 | 进 openvela 编译？ | 理由 |
|---|---|---|---|
| `quickapp/velaguard-inspection/` | **快应用**（三种官方形态之一） | **是**，由本仓 xml 的 `<linkfile>` 映射到 `packages/apps/contest2026_496_velaguard-inspection` | 这是本作品的参赛形态 |
| `edge-dashboard/` | 配套边缘层工程 | 否 | 跑在 Ubuntu（X3M/M1）上，**不是** openvela 应用，不伪造形态 |
| `app/vela_mecanum/` | **应用**（三种官方形态之一） | 否（需手工覆盖 `packages/ai_agent/`） | 同课题组另一件作品：四车自主编队。说明见 `app/vela_mecanum/作品说明.md` |
| `logs/` | AI Coding 日志 | 否 | 官方约定路径 |

---

## 四、运行方式

### 1. 拉取完整工程

```bash
repo init -u https://github.com/open-vela/contest2026_496_diaochabingtuan \
  -b dev-ai-contest-2026 -m contest2026_496_diaochabingtuan.xml
repo sync -c -j8
```

同步后本仓位于工作区 `contest2026_496_diaochabingtuan/`，openvela 全量源码在外层；
`quickapp/velaguard-inspection/` 已软链为 `packages/apps/contest2026_496_velaguard-inspection/`。

### 2. 快应用：本机零依赖跑测试与打包（不需要 openvela 工程）

```bash
cd contest2026_496_diaochabingtuan/quickapp/velaguard-inspection

node tools/preview-server.js   # 浏览器预览 → http://127.0.0.1:8177
node tools/run-tests.js        # 七步测试与自检
node tools/build-openvela.js   # 生成 build/openvela-app/{app.ux, manifest.json}
```

### 3. 编译 openvela 并运行到 Vela Emulator

```bash
cd ..    # 进入 openvela 工作区根目录

./build.sh vendor/openvela/boards/vela/configs/goldfish-arm64-v8a-ap/ --cmake -j$(nproc)
./emulator.sh cmake_out/vela_goldfish-arm64-v8a-ap/
# → goldfish-armv8a-ap> 提示符
```

> 端侧 AI 对话另需为固件补开 `CONFIG_EXAMPLES_AI_AGENT_VELA=y`、
> `CONFIG_FEATURE_SYSTEM_VELACLAW=y`、`CONFIG_MQ_MAXMSGSIZE=4096`（默认 defconfig **不含**）。

### 4. 部署快应用（arm64 模拟器）

```bash
# adb 只能传文件；adb shell 在 arm64 模拟器上返回 error: closed，属正常
adb -s emulator-5554 push quickapp/velaguard-inspection/dist-openvela /data/app/com.velaguard.inspection

# 在模拟器串口控制台输入：
vapp hap://app/com.velaguard.inspection
```

### 5. 部署自定义 Skill

```bash
adb -s emulator-5554 push quickapp/velaguard-inspection/skills/inspection.md \
    /data/agent/skills/inspection.md
```

### 6. 边缘层与真车联动

见 `edge-dashboard/README.md`（看板）与 `quickapp/velaguard-inspection/realcar/README.md`
（车端执行器 `patrol_controller.py`、路线表、起停脚本、逐轮实测证据）。

---

## 五、验证到什么程度（如实声明）

**这一节请评委连字号一起读——我们把「验过的」和「没验过的」分开写。**

### ✅ 已实测通过

| 范围 | 证据 |
|---|---|
| 端侧逻辑 54 项 + 模板 36 项 + 页面契约 18 项 + 界面冒烟 48 项 + 产物自检 13 项 | `node tools/run-tests.js` 七步全绿，合计 **169 项断言** |
| 四条固定路线合规（每步 ≤ 0.90 m，总长 10.30 m） | `node tools/gen-waypoints.js --check` |
| 生成 openvela 部署产物 | `node tools/build-openvela.js` → `app.ux` 134 KB + `manifest.json` |
| **真车联动**（2026-09-20 实机） | E5 触控屏点「开始巡检」→ 四台车按固定路线真动；`/odom` 逐步实测 **0.892~0.904 m**（命令 0.90 m），净航向漂移 ≤ 0.9°。逐轮证据见 `quickapp/velaguard-inspection/realcar/rounds/` 与 `证据截图/` |
| 地图数据来源真实 | 车端 ROS `classroom.pgm`（350×197，0.05 m/格）自动转矢量，`tools/ros-map-to-vector.js --auto` |

### ❌ 未验证（不声称）

| 未验证项 | 实情 |
|---|---|
| **在 openvela 模拟器上实际运行** | ⛔ **已尝试并定位到上游缺陷**：`vapp hap://app/<包名>` 触发 QuickApp 运行时的**递归断言并复位板子**，**官方自带 demo 同样崩溃**，故非本应用问题 |
| 官方 `release.rpk` | **未产出**。官方手册要求用 **AIoT-IDE** 图形化打包并生成签名，本队未走这条链路；`dist-openvela/` 是本仓构建脚本的产物，**不是**官方签名包 |
| `@system.velaclaw` 真通道 | 只在预览里验过**兜底路径**（本地指令表），与端侧 Agent 的真通道未接通 |
| 中文字体 / 触摸事件 / LVGL 下的 SVG 渲染 | 只有静态自检，真机未验 |

> **因此：本作品当前的现场演示形态是「E5 触控屏 + U2P(Ubuntu 20.04) + Firefox 全屏」，
> 不是 openvela 系统。我们不在任何材料里把它描述成「已在 openvela 上跑通」。**
> 设备侧的 `device/` 与 `realcar/` 是**同一份应用代码换宿主外壳**，车辆数据两种模式
> （内置模拟数据 / 真车实测）在界面上有明确标签区分。

---

## 六、AI Coding 使用说明

本作品在需求拆解、方案论证、代码编写、设备调试与文档撰写各环节均借助 AI 辅助完成。
完整对话日志见 [`logs/`](logs/README.md)。

- 本作品快应用源码、构建脚本、测试用例、Skill 与文档大部分由 AI 辅助生成、经人工审查与实机验证。
- openvela 平台相关开发在另一台具备完整环境的机器上进行，其日志由对应成员各自导出后提交，
  以保证 `logs/<github_login>/` 的归属正确。
- 仓库内不含手工拼装的日志：官方 `validate-log.py` 会校验序号连续性，篡改会被判作弊。

---

## 附：提交与 CLA

- 本仓所有改动通过 **Pull Request** 合入（分支保护强制，可自行 review 合入自己的 PR）。
- 首次贡献需在[**官网签署 CLA**](https://openvela.com/#/community/cla)。
  PR 上会自动运行 `cla/signature` 检查；签署成功后在该 PR 评论 `/check-cla` 触发复检即可通过。
- **注意**：`cla/signature` 依据 **commit 的 author email** 匹配签名库，
  且校验的是 PR 内**全部** commit 的邮箱；使用 GitHub `noreply` 邮箱会导致检查无法通过。
- 若需改动 `nuttx` 等公共仓库，不在本仓改：fork 对应公共仓，以 PR 提交到
  `dev-ai-contest-2026` 分支，由组委会 review 后合入。
