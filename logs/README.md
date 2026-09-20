# logs/ — AI Coding 日志

> ⚠️ **请评委先读这一页。** 本目录的日志**不是官方采集器直接产出的**，
> 而是由我们自写的**忠实转录器**从 Codex 原始会话记录转换而来。
> 转换原因、方法与验证结果全部写在下面，**没有任何隐藏**。

## 一、这里有什么

| 项 | 值 |
|---|---|
| 会话数 | **36** |
| 事件总数 | **10,048** |
| 体积 | 约 25.3 MB |
| 时间跨度 | **2026-09-14 ~ 2026-09-19** |
| 工具 | `codex`（Codex CLI / Codex Desktop） |
| 目录 | `logs/YYBIRDexe/<YYYY-MM-DD>/codex__<session_id>.jsonl` + `manifest.json` |

事件覆盖本作品从原型到验收的完整过程：四车固定 IP 与 ROS 域隔离、激光雷达与相机延迟排查、
M1/U2P 实训箱联网与代理、语音控车链路、唤醒词与 TTS、建图定位、打包收尾等。

## 二、为什么不是采集器直接产出的

官方采集器 `contest-log-collector` v1.3.0 的 `SKILL.md` 声明支持 Codex
（兼容性表：`Codex | CLI | ✅`），但其**唯一**的事件展开器
`adapters/shared/snapshot_core.py` 的 `expand_claude_event()` 只实现了 Claude Code 的
transcript 结构（读顶层 `message.role` / `message.content`）。

Codex rollout 的实际结构是：

```json
{"timestamp":"…","ordinal":2,"type":"response_item","payload":{"type":"message","role":"…","content":[{"type":"input_text","text":"…"}]}}
```

内容在 **`payload`** 里，展开器只读 `message`，于是每个事件都展开成 0 条。

**对照实验（2026-09-20，Python 3.14，同一套 harness）：**

| 喂给采集器的输入 | 结果 |
|---|---|
| Claude Code 格式 transcript（对照组） | ✅ 正常产出：`captured 2 event(s) -> logs/<login>/<date>/claude-code__<sid>.jsonl` |
| **Codex rollout `.jsonl`（我们的真实记录）** | ❌ **0 事件产出，静默无文件** |

官方 `tools/export-session.py --backfill --source` 的合法取值也只有
`all | claude | sqlite | opencode | mimocode | cursor`，**不含 codex**，
即 Codex 没有官方历史补录通道。

我们核对过：本机下载的 `snapshot_core.py` 与 GitHub `dev-ai-contest-2026` 分支上
**完全一致**（git blob 哈希均为 `b79a1e796d246ba88b80474584e86eac458d5cf9`），
说明该缺陷至今未被修复。

## 三、我们是怎么转换的

自写转录器 `codex2contest.js`，**严格按官方两份 schema 输出**：

- 事件逐行符合 `schema/event.schema.json`：必填 `schema_version` / `session_id` /
  `team_id` / `github_login` / `tool` / `ts` / `role` / `seq`；`role=tool` 时补
  `tool_name` + `tool_call_id`
- `seq` 从 **0 连续递增**，与官方 `append_events()` 的写法一致
- `manifest.json` 符合 `schema/manifest.schema.json`，`file_path` 用正斜杠
- 只取 `response_item` 一条流。Codex 会把同一内容同时写进
  `response_item/message` 与 `event_msg/item_completed`，**两条都取会让日志翻倍**，
  故只保留模型级的 `response_item`
- 映射规则：`message` → `user`/`assistant`/`system`（`developer` 归入 `system`）；
  `reasoning` → `assistant.thinking`；`function_call` / `custom_tool_call` →
  `role=tool` + `tool_name` + `input`；对应 `*_output` → `role=tool` + `output`；
  `compacted`（上下文压缩时的交接摘要）→ `system`
- 脱敏：套用官方同款三条正则（`sk-*` / `ghp_*` / `Bearer *`），本次共替换 **10 处**

**内容逐字来自原始 rollout，未增删、未改写、未润色。**

## 四、验证结果

用**官方校验器** `tools/validate-log.py` 校验本目录：

```text
=== contest-log-upload validation ===
Logs dir:       <本仓>/logs
Files checked:  36
Events checked: 10048

✅ ALL OK
```

退出码 `0`。（另有一份自写校验脚本按官方 schema 逐字段复核，同样 0 错 0 警。）

## 五、数据来源（三台机器）

| 来源 | 会话数 | 说明 |
|---|---:|---|
| 开发用 Windows 笔记本 | 9 | 2026-09-14 ~ 09-16 |
| U2P 实训箱（Horizon X3M，`192.168.1.104`） | 19 | 2026-09-15 ~ 09-17，设备端语音链路开发 |
| 课题组另一台 Windows 电脑 | 8 | 2026-09-14 ~ 09-19，四车网络/域/语音控车 |

> **关于「源文件 39 个、这里 36 个」**：另 3 个 rollout 是 Codex 的**实时语音对话**会话
> （`thread_source: "voice_chat"`），每个文件仅 3 行 —— `session_meta` +
> `realtime_session_started` + `realtime_session_closed`，**不含任何对话内容**，
> 无可转录，故未纳入。这一点主动说明，便于核对。

> **如实说明**：另一台电脑上运行的是 **Codex Desktop 外接自定义模型后端**
> （`model_provider: "custom"`，`model: "deepseek-v4-flash"`）。
> **工具本身仍是官方支持列表中的 Codex**，外接模型只是客户端配置；
> 这一点我们主动写明，不做隐瞒。
>
> 每个会话的 `manifest.json` 条目里带有 `data_completeness_warning` 字段，
> 逐条注明其转换来源与限制。

## 六、我们**没有**做什么

- **没有**修改任何一条对话内容
- **没有**手工拼装或伪造事件（`seq` 由转录器按顺序生成，可通过校验器逐条复核）
- **没有**把非 Codex 工具的对话混进 `logs/`（本作品开发中另有使用 DSH 等工具，
  官方支持列表内没有它们，故**未纳入**本目录）
- **没有**把原始 rollout 直接丢进 `logs/`（那会因目录层级与命名不符而校验失败）

## 七、原始记录

三处原始 Codex rollout（`.codex/sessions/**/rollout-*.jsonl`，共约 65 MB）
均由本队留存，可随时提供以核对上述转换的忠实性。
