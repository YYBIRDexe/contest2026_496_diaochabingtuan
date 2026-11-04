# 部署手册

目标平台：小米 AIoT 实训平台，Ubuntu，Python 3.8.10，SSH 用户 `sunrise`。  
部署方式：版本目录 + `current` 符号链接 + **用户级 systemd**（`velaguard-cloud-agent.service`）；
不需要 sudo、不需要 pip、不联网安装依赖。

## 1. 目标目录

```text
~/cloud-agent/
├── releases/20261017-120000-1234/         每次部署一个完整版本
└── current -> releases/...                 原子切换的当前版本
~/.config/velaguard-cloud-agent/
├── cloud-agent.env                         0600；不存在才创建；已有则保留
└── deepseek.key                            0600；key 文件；不内联到 env
~/.config/systemd/user/
└── velaguard-cloud-agent.service           用户级服务
~/.local/state/cloud-agent/
└── proposals.json                          提案持久化（0600）
```

代码目录可被替换；提案、env 和 key 独立于 release，升级不丢。

## 2. 推荐路径：PC 侧一键部署

前置：

- 已有 SSH 私钥和 known_hosts（不复制内容）。
- PC 到平台 TCP 22 可达；PC 侧源地址通常是 `192.168.137.1`。
- 平台 `python3` ≥ 3.8，`tar`、`bash`、用户级 `systemctl` 可用。

```powershell
cd "F:\xiaomi alot决赛codex工厂\platform\cloud-agent"

# 只检查参数和打包计划
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -DryRun

# 测试 + 打包 + 上传 + 安装 systemd 用户服务 + 启动 + 健康检查
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
```

默认值：

- `TargetHost=192.168.137.134`，`UserName=sunrise`
- `BindAddress=192.168.137.1`：SSH 与 SCP 都通过 `-b` / `-o BindAddress=...` 绑定源地址
- `Port=8130`，`ListenHost=0.0.0.0`
- `RemoteDir=/home/sunrise/cloud-agent`

打包使用 `tar`，显式排除：

```text
.env
config/*.env
*.key
var/
state/
__pycache__/
*.pyc
.pytest_cache/
.deploy/
```

`config/cloud-agent.env.example` 保留。打包后会列出归档并拒绝包含上述敏感路径的包。

首次部署时脚本创建空的 `cloud-agent.env` 模板（默认 DeepSeek、引用 `deepseek.key`、不填 key），
服务进入 **unconfigured** 状态：页面和只读工具可用，`POST /api/chat` 返回 503，不生成 mock 回复。

## 3. 手工部署（脚本不可用时）

```bash
# PC -> 平台；源地址绑定 192.168.137.1
scp -o BindAddress=192.168.137.1 \
  -i <key> -o UserKnownHostsFile=<known_hosts> -o StrictHostKeyChecking=yes \
  -r platform/cloud-agent sunrise@192.168.137.134:/tmp/cloud-agent-src

# SSH 同样绑定源地址
ssh -b 192.168.137.1 \
  -i <key> -o UserKnownHostsFile=<known_hosts> -o StrictHostKeyChecking=yes \
  sunrise@192.168.137.134 \
  "bash /tmp/cloud-agent-src/scripts/remote-install.sh \
     --staging /tmp/cloud-agent-src \
     --app-dir /home/sunrise/cloud-agent \
     --host 0.0.0.0 --port 8130"
```

注意：手工 `scp -r` 可能把工作区的 `.deploy/`、`var/`、`__pycache__/`、真实 `.env` 一起带上；
正式部署优先用 `deploy.ps1`，它会排除这些路径并校验归档。

## 4. 配置模型

### 4.1 环境文件与 key 文件

```bash
install -d -m 700 ~/.config/velaguard-cloud-agent
install -m 600 /dev/null ~/.config/velaguard-cloud-agent/cloud-agent.env
install -m 600 /dev/null ~/.config/velaguard-cloud-agent/deepseek.key
# 用平台本地编辑器写入 key；不要把内容贴到聊天或复制回工作区
```

`~/.config/velaguard-cloud-agent/cloud-agent.env` 最小配置：

```ini
CLOUD_AGENT_HOST=0.0.0.0
CLOUD_AGENT_PORT=8130
CLOUD_AGENT_LLM_BASE_URL=https://api.deepseek.com
CLOUD_AGENT_LLM_MODEL=deepseek-v4-flash
CLOUD_AGENT_LLM_API_KEY_FILE=/home/sunrise/.config/velaguard-cloud-agent/deepseek.key
```

- 用户已选 DeepSeek；其他 OpenAI 兼容供应商可改 `base_url` / `model`。
- 不要填 `CLOUD_AGENT_LLM_API_KEY` 或 `OPENAI_API_KEY`。配置加载器优先读取 key 文件，
  旧空/旧直写变量不会覆盖它。`tools/platform-connect/configure-deepseek.py` 会写入上述两个文件，
  并移除会遮蔽 key 文件的旧直写变量。
- 环境文件权限 0600；目录 0700。不要打印其内容。
- 代理：设备历史上可能导出指向 `192.168.1.100:7890` 的失效代理。默认
  `CLOUD_AGENT_LLM_PROXY=direct` 忽略 `http_proxy/https_proxy`；若确实需要代理，
  设为 `env`（继承进程环境）或具体 URL。

### 4.2 配置优先级

1. `CLOUD_AGENT_LLM_API_KEY_FILE` 指向的 key 文件（优先）。
2. 进程环境 `CLOUD_AGENT_LLM_API_KEY`（仅在未设置 key 文件时）。
3. `OPENAI_API_KEY` 兜底（仅在以上都未设置时）。

显式指定的 env 文件不存在、或文件中有格式错误时，服务会拒绝进入 `configured=true`，
不会误用其它凭据。

### 4.3 重启

```bash
systemctl --user restart velaguard-cloud-agent.service
systemctl --user status velaguard-cloud-agent.service
```

通过 SSH 执行时如提示无法连接用户总线，先设置：

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
```

不需要 sudo 改全系统；不要用 `nohup` 代替已启用的用户服务。

## 5. 访问与网络

- 默认监听 `127.0.0.1`；部署脚本按参数监听 `0.0.0.0:8130`，供同网段浏览器访问。
- 若从 PC 浏览器访问且平台有防火墙，需要放行 TCP 8130（仅在获授权时操作，不要关闭防火墙）：
  ```bash
  sudo ufw allow from 192.168.137.0/24 to any port 8130 proto tcp
  ```
- 更安全的替代：服务只监听 `127.0.0.1`，从 PC 建 SSH 本地转发：
  ```powershell
  ssh -b 192.168.137.1 -L 8130:127.0.0.1:8130 sunrise@192.168.137.134
  ```
  然后打开 `http://127.0.0.1:8130/`。
- 设置 `CLOUD_AGENT_ACCESS_TOKEN` 后，除 `/api/health` 外的 API 需要 `Authorization: Bearer`；
  页面折叠的“连接设置与技术详情”可填。

## 6. 用户级 systemd

`scripts/remote-install.sh` 会自动完成以下步骤：

```bash
mkdir -p ~/.config/systemd/user
cp ~/cloud-agent/current/systemd/cloud-agent.service \
   ~/.config/systemd/user/velaguard-cloud-agent.service
systemctl --user daemon-reload
systemctl --user enable velaguard-cloud-agent.service
systemctl --user restart velaguard-cloud-agent.service
systemctl --user is-active velaguard-cloud-agent.service
```

unit 使用 `EnvironmentFile=-%h/.config/velaguard-cloud-agent/cloud-agent.env`，systemd 直接读取，
不会把环境内容写入 stdout。服务名固定为 `velaguard-cloud-agent.service`，默认端口 8130。

没有用户会话/`systemctl --user` 不可用时，安装脚本会明确输出 `SYSTEMD_USER_UNAVAILABLE=1`
并失败；不会静默退回 `nohup`，避免把“文件已复制”误报成“服务已启用”。

## 7. 注册表替换（现场标定后）

编辑 `data/routes.json` 和 `data/fleet.json`，保持结构不变：

- 生产默认注册表为空；只登记维护者现场标定/核对过的路线和车辆。
- 路线 id 唯一；`enabled=false` 的路线仍可见但不可提案。
- 每条路线的 `checks` 至少一个，id 在路线内唯一；`checkpoints` 至少一个。
- 车辆 id 唯一；被指定执行时需登记所需能力（如 `inspection` / `navigation`）；`enabled=false` 不可用。
- 不要加入实时位置/电量字段来“看起来实时”；本服务没有遥测适配器。
- 修改后 `GET /api/health` 的 `routes_sha256` / `fleet_sha256` 会变化，可作为版本证据。
- `tests/fixtures/` 中的 `route-a` / `mentorpi-01` 只是测试数据，不能复制到生产 `data/`。

替换后重新部署，并跑 `scripts/smoke_test.py`。生产注册表为空时，冒烟脚本会跳过依赖已标定路线的提案步骤。

## 8. 健康检查与排障

```bash
python3 ~/cloud-agent/current/scripts/smoke_test.py --base-url http://127.0.0.1:8130
python3 ~/cloud-agent/current/scripts/health_check.py --base-url http://127.0.0.1:8130
systemctl --user status velaguard-cloud-agent.service
journalctl --user -u velaguard-cloud-agent.service -n 80 --no-pager
```

| 现象 | 检查 | 处理 |
|---|---|---|
| `Address already in use` | `ss -ltnp \| grep 8130` | 换端口或停止旧实例；不要盲杀未知进程 |
| `SYSTEMD_USER_UNAVAILABLE=1` | 用户会话、`XDG_RUNTIME_DIR`、`/run/user/$(id -u)/bus` | 在桌面用户会话中重试；不要改用 nohup 冒充已部署 |
| health 200 但 `configured=false` | key 文件是否存在、env 中的 base/model | 在设备上补配置；不要用假 key |
| 502 `llm_unreachable` | 设备到 provider 的网络、`CLOUD_AGENT_LLM_PROXY` | 设备需能出网；默认 direct 不继承失效代理 |
| 502 `llm_auth_failed` | key 是否属于该 provider、base_url 是否正确 | 在设备上修正并重启 |
| 404 `llm_endpoint_not_found` | base_url 是否重复/缺少路径 | 客户端会自动补 `/chat/completions`；检查 provider 文档 |
| 502 `llm_invalid_response` | provider 是否返回标准 OpenAI JSON | 换兼容端点；不要在本服务里伪造 |
| 422 `unknown_route` | 生产注册表是否为空 | 由维护者标定登记，或向用户澄清；不要猜测 |
| 409 `proposal_already_decided` | 提案状态 | 创建新提案；不要重复批准 |
| 401 | 是否设置了 `CLOUD_AGENT_ACCESS_TOKEN` | 在页面连接设置填口令 |
| 页面 CSP 报错 | 是否新增了内联脚本/样式 | 放回 `static/app.js` / `static/styles.css` |

## 9. 回滚

原则：切换 `current` 到上一个 release，保留 env 与 state，不递归删除未知路径。示例：

```bash
ls -1 ~/cloud-agent/releases
ln -sfn ~/cloud-agent/releases/<previous> ~/cloud-agent/current
systemctl --user restart velaguard-cloud-agent.service
```

不要删除 `~/.config/velaguard-cloud-agent/` 或 `~/.local/state/cloud-agent/`。

## 10. 部署边界

- 不复制设备 key/env 到工作区。
- 不修改 ACL/所有者来绕过权限。
- 不添加运动执行器、速度/坐标接口。
- 不把 fixture 注册表当现场标定，不把历史候选当真实车辆。
- 不把“批准计划”宣传成“已执行”。
