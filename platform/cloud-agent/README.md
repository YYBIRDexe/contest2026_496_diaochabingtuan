# VelaGuard Cloud Agent

平台侧认知服务：把自然语言巡检需求转成**经过本地注册表校验的待确认计划**，并通过同源静态页面展示对话、工具调用、车辆登记表、路线和提案。

- Python **3.8.10** 兼容，只用标准库，无 pip 依赖。
- 标准 **OpenAI 兼容 `POST /chat/completions`** 工具调用适配；默认 DeepSeek，`base_url` / `model` / 密钥文件可配置。
- 首版**没有运动执行器**：没有坐标、速度、车辆控制或自动执行接口。
- 未配置模型时服务照常启动，`POST /api/chat` 返回 **503** 并说明缺什么；**不会生成 mock 答复**。
- 未登记路线不能提案成功；工具会返回 `clarification_required=true`，Agent 必须向用户澄清。
- 批准计划只记录人工确认，提案的执行状态固定为 `not_executed`。

> **生产数据默认是空的。** `data/routes.json` 与 `data/fleet.json` 当前没有路线、没有车辆；
> 它们只接受维护者现场标定/核对后登记的数据。测试用的虚构路线和车辆只存在于
> `tests/fixtures/`，不会被生产默认数据加载，也不代表真实场地或真实能力。

## 1. 快速开始

```bash
cd platform/cloud-agent

# 1) 单元测试（不联网、不需要 key；使用 FakeLLM 和 tests/fixtures/）
python3 -m unittest discover -s tests -t . -v

# 2) 看配置状态（不会打印 key）
python3 app.py --print-status

# 3) 启动（默认 127.0.0.1:8130；未配置模型也可启动）
python3 app.py --host 127.0.0.1 --port 8130
```

打开 `http://127.0.0.1:8130/`。未配置时页面顶部显示“模型服务尚未配置”，聊天入口暂不可用；
路线、车队、校验、提案接口仍可用。技术细节只放在页面折叠的“连接设置与技术详情（维护者）”中。

### 配置模型（在设备上）

平台统一路径：

```text
/home/sunrise/.config/velaguard-cloud-agent/cloud-agent.env
/home/sunrise/.config/velaguard-cloud-agent/deepseek.key
```

`cloud-agent.env` 只引用 key 文件，不内联 key：

```ini
CLOUD_AGENT_HOST=0.0.0.0
CLOUD_AGENT_PORT=8130
CLOUD_AGENT_LLM_BASE_URL=https://api.deepseek.com
CLOUD_AGENT_LLM_MODEL=deepseek-v4-flash
CLOUD_AGENT_LLM_API_KEY_FILE=/home/sunrise/.config/velaguard-cloud-agent/deepseek.key
```

- 用户已选择 DeepSeek：默认 `base_url=https://api.deepseek.com`、`model=deepseek-v4-flash`。
- 不要把 key 写进 `CLOUD_AGENT_LLM_API_KEY` 或 `OPENAI_API_KEY`；key 文件优先，旧空/旧直写变量不会覆盖它。
- 保存 key 后执行 `systemctl --user restart velaguard-cloud-agent.service`。
- 密钥只放在平台，不要回传到工作区，也不要提交。部署脚本不会覆盖已存在的 env/key，也不会打印其内容。

## 2. 工具与语义

| 工具 | 作用 | 关键限制 |
|---|---|---|
| `get_capabilities` | 返回服务能力、`calibration`（路线/车辆是否已核验登记）、执行器状态、数据来源 | `calibration.routes.status=uncalibrated` / `calibration.fleet.status=unregistered` 时，应说明需要维护者登记 |
| `get_fleet_snapshot` | 返回本地车队登记表 | `is_live=false`、`telemetry=not_connected`；不声称在线/位置/电量 |
| `validate_mission` | 按注册表校验路线、检查项、车辆、计划时间 | 未知路线/检查项返回澄清，不创建计划 |
| `create_plan_proposal` | 创建待确认计划 | 内部再次校验；失败不落库；执行状态固定 `not_executed` |

### 空注册表

当前生产注册表为空，`POST /api/missions/validate` 对任何路线都会返回 HTTP 422 +
`unknown_route` + `clarification_required=true`。Agent 必须说明“当前没有已核验的标定路线，
需要维护者现场标定并登记”，不得用 `route-a` 等 fixture 或历史候选补足。

### 确认不等于执行

创建后的提案 `status=pending_confirmation`，`approval.state=pending`，`execution.state=not_executed`。
批准后 `status=confirmed_not_executed`，`approval.state=approved`，`execution.state` 仍为 `not_executed`。
没有“执行”接口。

## 3. HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务/模型配置/执行器状态（无需访问口令） |
| GET | `/api/tools` | 工具定义与执行器边界 |
| GET | `/api/routes` | 本地路线注册表与 `calibration` |
| GET | `/api/fleet` | 本地车队登记表（非实时）与 `calibration` |
| GET | `/api/capabilities` | 能力汇总；含 `calibration` |
| POST | `/api/chat` | Agent 对话；未配置返回 503 |
| POST | `/api/missions/validate` | 校验任务；失败返回 422 + 澄清 |
| GET | `/api/proposals` | 提案列表（新→旧，`?limit=`） |
| POST | `/api/proposals` | 创建待确认计划；成功 201，失败 422 |
| GET | `/api/proposals/<id>` | 单个提案 |
| POST | `/api/proposals/<id>/decision` | `{"decision":"approve"|"reject","actor":"","note":""}`；批准≠执行；重复决定 409 |

所有 API 返回 JSON；错误统一为：

```json
{"ok": false, "error": {"code": "machine_code", "message": "中文说明", "details": {}}}
```

可选访问口令：设置 `CLOUD_AGENT_ACCESS_TOKEN` 后，除 `/api/health` 外的 API 需要
`Authorization: Bearer <token>`（或 `X-Cloud-Agent-Token`）。页面折叠设置中可临时保存口令到 `sessionStorage`。

## 4. 部署

推荐在已授权的 PC 环境运行：

```powershell
cd "F:\xiaomi alot决赛codex工厂\platform\cloud-agent"
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
```

默认使用已有严格 SSH 配置：

- `TargetHost=192.168.137.134`，`UserName=sunrise`
- `KeyPath=F:/xiaomiaiot/runtime/credentials/id_ed25519`
- `KnownHostsPath=F:/xiaomiaiot/runtime/credentials/known_hosts`
- `HostKeyAlias=192.168.137.134`
- `BindAddress=192.168.137.1`（SSH 和 SCP 都绑定该源地址）
- `RemoteDir=/home/sunrise/cloud-agent`
- `Port=8130`

脚本会先跑本地测试，打包源码，上传到 `/tmp`，以 `sunrise` 运行 `scripts/remote-install.sh`。
打包显式排除真实 `.env`、`config/*.env`、`*.key`、`var/`、`state/`、`__pycache__/`、`*.pyc`、
`.pytest_cache/`、`.deploy/`，并保留 `config/cloud-agent.env.example`。

远程安装会：

1. 把 release 放到 `~/cloud-agent/releases/<timestamp>/`，原子切换 `current`；
2. 只在缺失时创建 `/home/sunrise/.config/velaguard-cloud-agent/cloud-agent.env`（0600，默认 DeepSeek、无 key）；
3. 安装用户级 `~/.config/systemd/user/velaguard-cloud-agent.service`；
4. 执行 `systemctl --user daemon-reload`、`enable`、`restart`，然后轮询 `/api/health`；
5. 不打印环境文件内容，也不需要 sudo 改全系统。

设备端目录：

```text
~/cloud-agent/releases/<timestamp>/                       版本化代码
~/cloud-agent/current -> ...                              当前版本符号链接
~/.config/velaguard-cloud-agent/cloud-agent.env           配置（0600；已存在则保留）
~/.config/velaguard-cloud-agent/deepseek.key              key（0600；由维护者/本地输入窗口写入）
~/.config/systemd/user/velaguard-cloud-agent.service      用户级服务
~/.local/state/cloud-agent/                               提案持久化
```

## 5. 测试

```bash
cd platform/cloud-agent
python3 -m unittest discover -s tests -t . -v
```

测试使用 `tests/fixtures/` 的虚构注册表；生产 `data/` 为空且有独立测试确认这一点。
覆盖配置、注册表、空注册表、提案、Agent 循环、HTTP（503/422/201/409/401/413）、
DeepSeek thinking 关闭、key 文件优先级等。

端到端（真实服务，不 mock）：

```bash
python3 scripts/smoke_test.py --base-url http://127.0.0.1:8130
python3 scripts/health_check.py --base-url http://127.0.0.1:8130
```

生产注册表为空时，冒烟脚本会验证未知路线被拒绝，并跳过依赖已标定路线的提案步骤；
未配置模型时验证聊天返回 503 且不生成 mock 答复。

## 6. 安全与边界

- 无 shell、文件、坐标、速度、车辆控制工具。
- 工具参数先按 JSON Schema 校验，再进入领域校验；领域校验再查注册表。
- API 请求体上限 64 KiB，且在模型配置检查之前执行；聊天每 IP 20 次/分钟；静态资源路径穿越拒绝。
- 响应带 CSP（`default-src 'self'`）、`nosniff`、`DENY` 等头；无 CORS 通配。
- 日志不打印 key、Authorization、环境文件内容；`public_status()` 只返回脱敏 URL 与来源标记。
- 默认仅监听 `127.0.0.1`；部署脚本按参数监听 `0.0.0.0`，建议设置访问口令或限制在隔离的 ICS 网段。
- 提案持久化文件权限尝试设为 0600；设备上的状态目录建议 0700。
- 平台历史上导出的 `http_proxy/https_proxy` 可能指向不可用主机。模型客户端默认 `CLOUD_AGENT_LLM_PROXY=direct`，不继承失效代理；需要代理时显式设为 `env` 或具体 URL。

## 7. 文件结构

```text
platform/cloud-agent/
├── app.py                     入口（WSGI、线程服务器、--print-status）
├── cloud_agent/
│   ├── agent.py               tool_calls 循环、会话、系统提示
│   ├── config.py              环境/文件配置、key 文件优先、脱敏
│   ├── errors.py              统一错误码/HTTP 状态
│   ├── http_api.py            API + 同源静态 + 安全头 + 请求体上限
│   ├── llm.py                 OpenAI 兼容客户端；DeepSeek 关闭 thinking
│   ├── registry.py            路线/车队注册表、calibration、领域校验
│   ├── schema.py              JSON Schema 子集
│   ├── store.py               提案存储/批准语义/持久化
│   ├── tools.py               四个真实工具
│   └── util.py                时间/ID/路径/脱敏
├── data/{routes,fleet}.json   生产注册表（当前为空，等待维护者标定/登记）
├── tests/fixtures/            仅测试使用的虚构注册表
├── static/                    同源 UI（HTML/CSS/JS/SVG）
├── config/cloud-agent.env.example
├── systemd/cloud-agent.service  安装为 velaguard-cloud-agent.service
├── scripts/                   deploy.ps1, remote-install.sh, check-device.sh,
│                              run-server.sh, smoke_test.py, health_check.py, test.sh
├── tests/                     标准库 unittest
└── docs/                      API、部署、交接
```

## 8. 已知缺口

1. 生产路线/车辆为空，必须由维护者现场标定、核对并登记后才能生成计划。
2. 没有实时遥测、定位、电池、健康适配器；`get_fleet_snapshot` 只读登记表。
3. 没有运动执行器；后续若要执行，必须新增独立适配器、车端安全策略、授权与回放验收。
4. 会话历史在内存中，重启丢失；提案持久化在 `CLOUD_AGENT_STATE_DIR/proposals.json`。
5. 用户级 systemd 依赖桌面用户会话/`systemctl --user`；部署脚本在不可用时明确失败，不静默改用 nohup。
