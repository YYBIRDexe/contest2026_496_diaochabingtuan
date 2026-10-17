# VelaGuard——多机器人分区巡检与异常闭环系统

> **2026 首届 openvela AI 硬件开发者大赛** · 参赛作品仓
> **队伍**：调教小车太难了 ｜ **选题方向**：AI 硬件产品创新
> **作品形态**：**快应用**（`quickapp/velaguard-inspection/`）→ 由本仓 manifest 映射到 `packages/apps/contest2026_496_velaguard-inspection`
> **运行平台**：openvela Vela Emulator（`goldfish-arm64-v8a-ap`，720×1280 竖屏）
> **本仓另含**同课题组第二件作品 **VelaMecanum**（四车自主编队，应用形态），见 `app/vela_mecanum/`

---

## 一、作品简介

**一句话定位**

> 面向**实验室、展厅与教学空间的管理人员**，把固定区域的检查任务分派给不同编号的小车自主执行，
> 并由一个运行在 openvela 上、**会主动盯场的 AI Agent** 负责上报异常与闭环；
> 解决「人工巡查重复、区域覆盖不均、异常信息分散且没人第一时间知道」的问题。

**做什么**

在 openvela 上部署一个 AI Agent 作为「值班调度员」：它按周期主动汇总四个区域的覆盖情况、
在车辆阻塞或失联时**第一时间主动告警**并给出改派建议、
并记住上一轮未完成的区域在下一轮开头主动提醒。
说一句「开始巡检」，Agent 理解意图、按自定义 Skill 编排任务下发，
边缘层把任务单转给四台 ROS 2 麦克纳姆小车执行，触控界面呈现任务状态与异常闭环。

**面向谁**

- 直接用户：实验室 / 展厅 / 教学空间的值班管理员
- 最终受益者：空间的使用者与管理者（巡检不再依赖人工全程盯守）

**解决什么问题**

| 问题 | 现状 | 本作品 |
|---|---|---|
| 人工巡查重复、覆盖不均 | 靠人走一遍，容易漏区、难以留痕 | 四车分区执行固定路线，覆盖状态可查 |
| 异常信息分散 | 出问题要事后翻各车日志 | Agent **主动**告警，异常主动找上门 |
| 未完成区域被静默漏掉 | 没人记得上轮哪个区没查 | Agent 记住并**主动提醒**顺延 |
| 无人盯场 | 管理员不可能全程盯屏 | 定时主动汇报 + 阈值主动判定失联 |

**亮点**

- **主动 + 执行**（非纯对话机器人）：四类主动任务——**事件主动**（收到异常回执立即告警）、
  **阈值主动**（连续 20 秒无回执判定失联并摘除该车）、**定时主动**（周期汇总覆盖情况）、
  **上下文主动**（每轮开始前读记忆，提醒上轮未完成区域）
- **端侧 AI 通道**：快应用通过官方 `@system.velaclaw.ask()` 调用端侧 AI Agent，
  并把 Agent **调用了哪些工具**一并显示出来
- **自定义 Skill**：以 Markdown 沉淀区域表与车辆映射、任务单字段与回执语义、
  阻塞/失联判定阈值与处置流程、安全规则（赛题必做项）
- **地图是真的**：界面地图为车端真实 ROS 地图 `classroom.pgm`（350×197 格，0.05 m/格）
  自动转出的矢量轮廓（55 个墙块），不是占位图
- **端端协作**：触控交互层 / 边缘层 / 车端三层分工，构成赛题加分项「端云·端端协作」的落地形态

**系统架构**

```text
┌──────────────────────────────────────────────────────┐
│ ① 触控交互层 —— VelaGuard 快应用（本仓 quickapp/）     │
│   · 七个视图：桌面 / 调度台 / 地图与路线 / 区域与任务 / │
│     巡检记录 / 语音助手 / 系统与链路                   │
│   · 端侧 AI 对话：@system.velaclaw.ask()              │
│   · 自定义 Skill：skills/inspection.md                │
└───────────────┬──────────────────────────────────────┘
                │ 端侧 Agent 通道 / HTTP
                ▼
┌──────────────────────────────────────────────────────┐
│ ② 边缘层 —— 小米 AIoT 实训箱 M1（U2P Horizon X3M）    │
│   · VelaGuard 看板（本仓 edge-dashboard/）             │
│   · 车端执行器 patrol_controller.py（realcar/）        │
│   · 语音链路（唤醒 → ASR → 意图 → 下发 → TTS 播报）     │
└───────────────┬──────────────────────────────────────┘
                │ ws://<车>:9090  rosbridge → /cmd_vel
                ▼
   四台 MentorPi 麦克纳姆小车（Raspberry Pi 5 / ROS 2）
   —— 车端本地安全逻辑最高优先，遇障自行停车
```

---

## 二、选题方向

**AI 硬件产品创新**。

理由：本作品把「决策与闭环」放在 openvela 端侧——任务编排、状态机、异常判定、主动告警、
跨轮次记忆全部运行在 openvela 上；口语文案与汇总文本由云端 LLM 润色；感知与执行在车端。
落地的 openvela 能力为：

| openvela 能力 | 在本作品中的落点 |
|---|---|
| **AI**（`packages_ai_agent`） | 意图路由、Skill 加载器、**主动任务机制**、记忆机制 |
| **多媒体**（端侧语音交互链路） | 唤醒 → ASR → 意图 → 下发 → TTS 播报 |
| **快应用框架** | 触控界面七视图、`@system.velaclaw` 端侧 Agent 通道 |

> **不是**纯云端应用（Agent 运行在 openvela 上）；
> **不是**纯对话机器人（有主动任务 + 真实工具调用，能派单并驱动四台车）。

---

## 三、目录结构

```text
/
├── README.md                            本文件
├── contest2026_496_diaochabingtuan.xml  本仓 manifest（含 1 条快应用 <linkfile>）
├── openvela.xml                         openvela 全量工程清单（未改动）
│
├── quickapp/velaguard-inspection/       ★ VelaGuard：快应用源码工程（本仓主要作品）
│   ├── src/                             源码（唯一需要手改的地方，19 文件）
│   │   ├── manifest.json                包名 com.velaguard.inspection，720×1280
│   │   ├── app.ux.tmpl                  openvela 入口模板（产物由脚本拼装）
│   │   ├── app-shell.js                 宿主无关外壳：250ms tick、切页、事件派发
│   │   ├── common/                      data / map / map-data / store / agent / tpl / ui / router / styles
│   │   └── pages/                       七个视图（Home / Dispatch / Map / Zones / Records / Voice / System）
│   ├── tools/                           20 个脚本：测试、打包、ROS 地图转矢量、产物自检
│   ├── skills/inspection.md             ★ 自定义 Skill（赛题必做项）
│   ├── device/                          E5 触控屏演示宿主（可跑、可录）
│   ├── realcar/                         真车联动：车端执行器 + 路线表 + 逐轮实测证据 + 6 张截图
│   ├── dist-openvela/                   部署产物 app.ux + manifest.json（生成物）
│   └── docs/                            部署到 openvela / 模拟器命令单 / 地图与路线 / 拍摄执行单
│
├── edge-dashboard/                      边缘层工程（M1/U2P，Node + Python，不参与 openvela 编译）
│   ├── src/ linux/ tools/ data/ docs/   看板源码、设备脚本、调试工具、文档
│   └── preview/index.html               零依赖自包含预览页（双击可看界面）
│
├── app/vela_mecanum/                    ★ 第二件作品：VelaMecanum 四车自主编队（应用形态）
│   ├── openvela/                        openvela 端 ai_agent 改造 + Formation Lab + ROS 2 bringup
│   ├── outputs/formation-kit/           当前四车任务控制程序与现场任务记录
│   ├── work/                            部署、诊断、定位、安装与验收工具
│   ├── docs/                            代码索引 / 验收状态 / 测试结果 / 移交说明
│   └── 作品说明.md                      该作品的完整说明（简介 / 运行方式 / 验收结果）
│
└── logs/                                AI Coding 日志：36 会话 / 10,048 事件（见 logs/README.md）
```

**各目录为什么这样放**

| 目录 | 形态 | 进 openvela 编译？ | 说明 |
|---|---|---|---|
| `quickapp/velaguard-inspection/` | **快应用**（三种官方形态之一） | **是**，由本仓 manifest 的 `<linkfile>` 映射到 `packages/apps/contest2026_496_velaguard-inspection` | 本队主要作品的参赛形态 |
| `app/vela_mecanum/` | **应用**（三种官方形态之一） | 否（其 `ai_agent` 需手工覆盖 `packages/ai_agent/`） | 同课题组第二件作品 |
| `edge-dashboard/` | 配套边缘层工程 | 否 | 跑在 Ubuntu（X3M/M1）上，**不是** openvela 应用，不伪造形态 |
| `logs/` | AI Coding 日志 | 否 | 官方约定路径 |

---

## 四、运行方式

> 目标：评委照着本节可以一步步复现。

### 4.1 拉取完整工程

```bash
repo init -u https://github.com/open-vela/contest2026_496_diaochabingtuan \
  -b dev-ai-contest-2026 -m contest2026_496_diaochabingtuan.xml
repo sync -c -j8
```

同步后本仓位于工作区 `contest2026_496_diaochabingtuan/`，openvela 全量源码在外层
（`nuttx/`、`apps/`、`packages/`、`vendor/` 等）；
`quickapp/velaguard-inspection/` 已被软链为 `packages/apps/contest2026_496_velaguard-inspection/`。

### 4.2 快应用：本机零依赖跑测试与打包（**不需要 openvela 工程**）

只需 Node.js ≥ 18，无第三方依赖、不用 `npm install`：

```bash
cd contest2026_496_diaochabingtuan/quickapp/velaguard-inspection

node tools/preview-server.js   # 浏览器打开 http://127.0.0.1:8177 看界面（改完 src/ 刷新即可）
node tools/run-tests.js        # 七步测试与自检，应全部通过、exit 0
node tools/build-openvela.js   # 生成 build/openvela-app/{app.ux, manifest.json}
```

### 4.3 编译 openvela 并运行到 Vela Emulator

```bash
cd ..    # 回到 openvela 工作区根目录

./build.sh vendor/openvela/boards/vela/configs/goldfish-arm64-v8a-ap/ --cmake -j$(nproc)
./emulator.sh cmake_out/vela_goldfish-arm64-v8a-ap/
# 看到 goldfish-armv8a-ap> 提示符即启动成功
```

> **端侧 AI 对话需为固件补开以下配置**（官方默认 defconfig **不含**）：
> `CONFIG_EXAMPLES_AI_AGENT_VELA=y`、`CONFIG_FEATURE_SYSTEM_VELACLAW=y`、
> `CONFIG_MQ_MAXMSGSIZE=4096`（不足会**静默丢消息**）。详见 `quickapp/velaguard-inspection/docs/部署到openvela.md`。

### 4.4 部署快应用与 Skill

```bash
# 部署快应用（arm64 模拟器上 adb 只能传文件；adb shell 返回 error: closed 属正常现象）
adb -s emulator-5554 push contest2026_496_diaochabingtuan/quickapp/velaguard-inspection/dist-openvela \
    /data/app/com.velaguard.inspection

# 在模拟器串口控制台（不是 adb shell）输入：
vapp hap://app/com.velaguard.inspection
```

```bash
# 部署自定义 Skill
adb -s emulator-5554 push contest2026_496_diaochabingtuan/quickapp/velaguard-inspection/skills/inspection.md \
    /data/agent/skills/inspection.md
```

> ⚠️ Skill 目录名先确认：openvela 源码里 `ai_agent` 的 Kconfig 默认是 `/data/ai_agent`，
> 而官方大赛指引写 `/data/agent`，板级 defconfig 未覆盖该宏。**以设备上实际存在的目录为准**。
> 模拟器还需先推中文字体到 `/data/font/`，否则中文全是方块。

### 4.5 边缘层与真车联动（E5 触控屏演示形态）

```bash
ssh sunrise@192.168.1.104 "bash ~/velaguard/demo/run-demo.sh"      # 启动演示
ssh sunrise@192.168.1.104 "bash ~/velaguard/demo/reset.sh"         # 复位（录制前必做）
ssh sunrise@192.168.1.104 "bash ~/velaguard/demo/run-demo.sh --stop"
```

完整说明见 `quickapp/velaguard-inspection/device/README.md`；
车端执行器 `patrol_controller.py`、路线表与逐轮实测证据见
`quickapp/velaguard-inspection/realcar/`。

### 4.6 第二件作品（VelaMecanum）的运行方式

```powershell
# Windows 本地仿真与自动测试
cd app/vela_mecanum/outputs/formation-kit
& .\run_formation.cmd square --spacing 0.5 --simulate
& .\test_local.cmd
```

openvela QEMU 构建、Formation Lab 与四车现场任务见 `app/vela_mecanum/作品说明.md`。

### 4.7 复现清单（照着打勾即可）

| # | 步骤 | 期望结果 | 依赖 |
|---|---|---|---|
| 1 | `node tools/run-tests.js` | 七步全绿，exit 0（169 项断言） | 仅需 Node.js ≥ 18 |
| 2 | `node tools/build-openvela.js` | 生成 `app.ux`（约 134 KB）+ `manifest.json` | 同上 |
| 3 | `node tools/gen-waypoints.js --check` | 四条固定路线合规（每步 ≤ 0.90 m，总长 10.30 m） | 同上 |
| 4 | `./build.sh … && ./emulator.sh …` | 出现 `goldfish-armv8a-ap>` 提示符 | openvela 工作区 + Ubuntu 22.04 |
| 5 | `adb push dist-openvela /data/app/<包名>` | 文件落到 `/data/app/com.velaguard.inspection/` | 模拟器已启动 |

> 第 4、5 步的**实际运行结果**请对照下面第六节的「验证边界」——我们如实标注了哪些跑通、哪些没有。

---

## 五、AI Coding 使用说明

### 5.1 在哪些环节借助了 AI

| 环节 | AI 参与方式 |
|---|---|
| 需求拆解与方案论证 | 用 AI 交叉核对赛题条款与官方文档，收敛出「主动 + 执行」的核心定位；对多个候选方案做可行性比对 |
| openvela 平台边界确认 | 让 AI 读官方源码与文档，确认 Vela Emulator 的外设边界、快应用运行时能力、`@system.velaclaw` 的真实通道与限制（例如：**没有** `@system.websocket` 模块、Agent 侧的工具桥是返回 `not_implemented` 的桩） |
| 编码 | 快应用七视图、状态机、模板引擎、打包器与全部测试用例，大部分由 AI 生成后人工审查、修改与实机验证 |
| 调试 | 与 AI 一起定位设备侧语音链路、隧道、代理、唤醒词误触发等问题；AI 负责读日志、提假设、写复现脚本 |
| 文档与材料 | 部署文档、命令单、演示执行单、技术报告素材由 AI 起草后人工校订 |

### 5.2 AI 带来的实际帮助

- **平台调研时间大幅压缩**：openvela 的构建目标、快应用运行时、端侧 Agent 通道等边界，
  由 AI 直接读竞赛分支源码给出结论，替代了原本需要数天的资料检索与试错。
- **可重复的验收流程**：AI 协助把「检查」固化成脚本（`tools/` 下 20 个），
  包括 169 项断言的测试集与产物自检，使改动后能一键回归。
- **口径一致性**：AI 在多轮对话中持续比对「材料声称」与「实机实测」，
  促成了本 README 第六节那份「验过的 / 没验过的」分列声明。

### 5.3 完整对话日志

见 [`logs/`](logs/README.md) —— **36 个会话 / 10,048 个事件 / 约 25 MB**，
时间跨度 2026-09-14 ~ 09-19，覆盖四车网络与 ROS 域隔离、激光雷达与相机延迟排查、
实训箱联网与代理、语音控车链路、唤醒词与 TTS、建图定位等全过程。

> **如实声明（请评委注意）**：本目录的日志**不是官方采集器直接产出的**，
> 而是由我们自写的**忠实转录器**从 Codex 原始记录转换而来，原因如下 ——
>
> 官方采集器 `contest-log-collector` v1.3.0 的 `SKILL.md` **声明支持 Codex**，
> 但其唯一的事件展开器 `expand_claude_event()` 只实现了 Claude Code 的 transcript 结构
> （读顶层 `message.content`），而 Codex 把内容放在 `payload` 里。
> **对照实验**：同一套 harness 下，Claude 格式样本正常产出，Codex rollout 产出 **0 事件**；
> 官方 `--backfill --source` 合法取值也不含 `codex`。
> 我们核对过官方源码至今未修复（git blob 哈希与 GitHub 分支完全一致）。
>
> 转录器**严格按官方两份 schema 输出**，`seq` 从 0 连续递增，
> 内容**逐字来自原始 rollout，未增删改写**，仅套用官方同款脱敏（共 10 处）。
> 用**官方** `tools/validate-log.py` 校验结果为 **`✅ ALL OK`（exit 0）**。
> 完整方法、对照实验证据与数据来源见 [`logs/README.md`](logs/README.md)。

---

## 六、验证边界（如实声明）

> 这一节请连字号一起读——我们把「验过的」和「没验过的」分开写，不把计划说成已完成。

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
| `@system.velaclaw` 真通道 | 只在浏览器预览里验过**兜底路径**（本地指令表），与端侧 Agent 的真通道未接通 |
| 中文字体 / 触摸事件 / LVGL 下的 SVG 渲染 | 只有静态自检，真机未验 |

> **因此：本作品当前的现场演示形态是「E5 触控屏 + U2P(Ubuntu 20.04) + Firefox 全屏」，不是 openvela 系统。
> 我们不在任何材料里把它描述成「已在 openvela 上跑通」。**
> `device/` 与 `realcar/` 是**同一份应用代码换宿主外壳**，车辆数据的两种模式
> （内置模拟数据 / 真车实测）在界面上有明确标签区分。

---

## 附：提交与 CLA

- 本仓所有改动通过 **Pull Request** 合入（分支保护强制，可自行 review 合入自己的 PR）。
- 首次贡献需在[**官网签署 CLA**](https://openvela.com/#/community/cla)。
  PR 上会自动运行 `cla/signature` 检查；签署成功后在该 PR 评论 `/check-cla` 触发复检即可通过。
- **注意**：`cla/signature` 依据 **commit 的 author email** 匹配签名库，
  且校验的是 PR 内**全部** commit 的邮箱；使用 GitHub `noreply` 邮箱会导致检查无法通过。
- 若需改动 `nuttx` 等公共仓库，不在本仓改：fork 对应公共仓，以 PR 提交到
  `dev-ai-contest-2026` 分支，由组委会 review 后合入。
