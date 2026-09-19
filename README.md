# VelaGuard——多机器人分区巡检与异常闭环系统

> **2026 首届 openvela AI 硬件开发者大赛** · 参赛作品仓
> **队伍**：调教小车太难了 ｜ **选题方向**：AI 硬件产品创新
> **报名硬件形态**：模拟器（Vela Emulator `goldfish-arm64-v8a-ap`）

---

## 一、作品简介

面向园区 / 厂区巡检场景的**自然语言调度与安全监督系统**。

说一句「开始本轮巡检」，openvela 端侧的 `ai_agent` 理解意图、编排任务并**主动**上报异常；
X3M 边缘层把任务单下发给四台 ROS 2 麦克纳姆小车，驱动它们完成四区分区巡检；
触控看板实时呈现任务状态、覆盖情况与异常闭环。

**要解决的问题**：传统多机器人巡检依赖人工逐台派单、人工盯屏，异常发现滞后。
本作品把「派单 → 执行 → 回执 → 异常告警 → 汇总」做成闭环，
并把**主动告警**（而非被动问答）作为核心交互形态——这正是赛题对
「纯对话机器人」的排除条款所指向的能力。

**亮点**

- **主动 + 执行**：异常回执到达即触发端侧主动播报与上下文提醒，不等用户提问
- **端云 / 端端协作**：openvela 端侧负责意图理解与任务编排，X3M 边缘层负责机器人对接，云侧 LLM 负责文本润色
- **自定义 Skill**：以 Markdown 沉淀区域表与车辆映射、任务单字段与回执语义、阻塞/失联判定阈值与处置流程、安全规则

**系统架构**

```text
┌──────────────────────────────────────────────────────┐
│ ① openvela 端侧设备（跑官方 ai_agent）                │
│   · 自然语言交互（唤醒词：你好，openvela / Hello，openvela）│
│   · 自定义 Skill（/data/agent/skills/inspection.md）  │
│   · 主动任务：定时轮询 + 异常事件即时告警              │
│   · 交互渠道：Channel（WebSocket）                    │
└───────────────┬──────────────────────────────────────┘
                │ 官方 Channel（端云协作）
                ▼
┌──────────────────────────────────────────────────────┐
│ ② 云端 LLM（文本润色 / 兜底理解）                     │
└───────────────┬──────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────┐
│ ③ X3M 边缘层（Ubuntu）                               │
│   · VelaGuard 触控看板：四车状态、任务清单、派单/取消  │
│   · 本地代理服务：把「四车状态 / 异常」暴露给 ①        │
│   · 语音链路（云端 ASR → 意图 → 下发 → TTS 播报）      │
└───────────────┬──────────────────────────────────────┘
                │ eth0 / vcmd
                ▼
        四台 MentorPi 麦克纳姆小车（ROS 2）
```

---

## 二、选题方向

**AI 硬件产品创新**。

作品落地 openvela 的 **AI**（`packages_ai_agent`：意图路由、Skill 加载器、主动任务、记忆机制）
与**多媒体**（端侧语音交互链路）能力。

---

## 三、目录结构

```text
/
├── README.md      本文件（作品说明）
├── logs/          AI Coding 日志，一人一目录：logs/<github_login>/<date>/<tool>__<sid>.jsonl
└── （作品代码）    见下
```

### 关于作品形态目录

本仓骨架原带三个占位样例——`app/hello_app`、`quickapp/hello_quickapp`、`board/contest_board`。
经核对，它们都是组委会模板 `contest2026_000_openvela` 的**残留**（样例内部仍写着 team 000：
`packages/demos/contest2026_000_hello_app`、`team000` 等），并非本队作品。

本作品不使用这三种形态，已连同 `contest2026_496_diaochabingtuan.xml` 中对应的
三条 `<linkfile>` 一并移除。**新增形态时按原规则补回即可**，生产仓库
（`packages/` `nuttx/` `vendor/`）保持零改动：

| 作品形态 | 你的代码放这里 | manifest 软链到 |
| --- | --- | --- |
| 应用 | `app/<app名>/` | `packages/demos/contest2026_496_<app名>` |
| 快应用 | `quickapp/<快应用名>/` | `packages/apps/contest2026_496_<快应用名>` |
| 板级适配 | `board/<board名>/` | `vendor/openvela/boards/contest2026_496_<board名>` |

---

## 四、运行方式

### 1. 拉取完整工程

```bash
repo init -u https://github.com/open-vela/contest2026_496_diaochabingtuan \
  -b dev-ai-contest-2026 -m contest2026_496_diaochabingtuan.xml
repo sync -c -j8
```

同步后本仓位于工作区 `contest2026_496_diaochabingtuan/`，openvela 全量源码在外层
（`nuttx/`、`apps/`、`packages/`、`vendor/` 等）。

### 2. 编译并运行到 Vela Emulator

```bash
cd ..    # 进入 openvela 工作区根目录

./build.sh vendor/openvela/boards/vela/configs/goldfish-arm64-v8a-ap/ --cmake -j$(nproc)
./emulator.sh cmake_out/vela_goldfish-arm64-v8a-ap/
# → goldfish-armv8a-ap> 提示符
```

### 3. 部署自定义 Skill

```bash
adb -s emulator-5554 push inspection.md /data/agent/skills/inspection.md

# 在 openvela 控制台确认可读回：
vela> read_file /data/agent/skills/inspection.md
```

### 4. 边缘层（X3M 看板与代理服务）

**待补充**：边缘层代码与启动步骤尚未并入本仓，见第六节。

---

## 五、AI Coding 使用说明

本作品在需求拆解、方案论证、代码编写、设备调试与文档撰写各环节均借助 AI 辅助完成。
完整对话日志见 [`logs/`](logs/README.md)。

**关于日志的两点说明（如实声明）**

1. 本届官方采集工具支持 Claude Code / AIoT-IDE / OpenCode / Codex（仓内
   `logs/README.md` 记为 claude-code / opencode / codex / kiro）。本作品的对话分布在
   多种工具上，`logs/` 中已按官方格式归集可采集的部分。
2. openvela 相关开发在另一台具备完整环境的机器上进行，其日志由对应成员各自导出后提交，
   以保证 `logs/<github_login>/` 的归属正确。

**AI 对开发的实际帮助**：主要体现在 openvela 平台边界的快速确认
（官方支持列表、BSP 可用性、模拟器目标）、方案的多轮论证与收敛，
以及设备侧链路的故障定位——这些在无 AI 辅助时通常需要数天资料检索。

---

## 六、当前状态与待补清单

> **本节为提交前的工作清单，请在最终提交前更新或删除。**

**已完成**

- [x] 仓库初始化与骨架清理（移除模板残留的三个 team-000 占位样例）
- [x] 作品说明（本文件）
- [x] `logs/` 目录结构与说明就位

**待补**

- [ ] openvela 端侧：`ai_agent` 配置与自定义 Skill `inspection.md`
- [ ] 边缘层：VelaGuard 看板与本地代理服务并入本仓
- [ ] `logs/<github_login>/`：各成员按官方格式导出的真实日志
- [ ] 编译与运行验证：`build.sh` + Vela Emulator 跑通并留存证据
- [ ] 提交前删除 `logs/README.md` 中的示例说明段（如已不再需要）

---

## 附：提交与 CLA

- 本仓所有改动通过 **Pull Request** 合入（分支保护强制，可自行 review 合入自己的 PR）。
- 首次贡献需在[**官网签署 CLA**](https://openvela.com/#/community/cla)。
  PR 上会自动运行 `cla/signature` 检查；签署成功后在该 PR 评论 `/check-cla` 触发复检即可通过。
- **注意**：`cla/signature` 依据 **commit 的 author email** 匹配签名库，
  请确保提交邮箱与签署 CLA 时使用的邮箱一致；使用 GitHub `noreply` 邮箱会导致检查无法通过。
- 若需改动 `nuttx` 等公共仓库，不在本仓改：fork 对应公共仓，以 PR 提交到
  `dev-ai-contest-2026` 分支，由组委会 review 后合入。
