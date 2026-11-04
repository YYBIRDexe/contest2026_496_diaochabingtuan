# 交接给 Codex：cloud-agent 测试、部署与验收

更新时间：2026-10-17  
交接方：DSH（实现）  
接收方：Codex（在已授权 exec 环境执行测试与部署）

## 0. 先看状态（不要误读）

- 本目录 `platform/cloud-agent/` 的代码、UI、配置样例、测试、部署脚本已写完。
- **DSH 没有执行测试或部署**：本会话启动 shell 时报 `grantWrite` 失败。DSH 按用户要求只用文件工具写产物，没有修改 ACL/所有者，没有绕过环境，也没有用子代理代跑。
- 因此下面任何“测试通过 / 已部署 / 模型可用”都不能由 DSH 宣称；需要 Codex 实际执行并把输出作为证据。
- 平台侧已知（用户提供）：Python 3.8.10，SSH 用户 `sunrise`，ASIX 直连 100 Mbps，既有 key/known_hosts 路径见下。设备 IP 以现场为准，历史连通值为 `192.168.137.134`。
- 首版**没有运动执行器**。任何批准都只是计划确认；不要让 UI/文档/汇报把 `approved` 说成 `executed`。
- `data/routes.json`、`data/fleet.json` 是样例注册表，**不是现场标定/实时遥测**。部署后可以先用样例验证拒绝逻辑，但正式演示前必须替换为真实路线/检查项/车辆。

## 1. 需要平台提供的非秘密信息

请只回报以下元信息，**不要发送 API key、访问口令、私钥或 env 文件内容**：

1. 设备当前 LAN IP、SSH 用户、hostname，以及 `HostKeyAlias=192.168.137.134` 是否仍适用。
2. TCP `8090` 是否空闲；若占用，换哪个端口；E5 浏览器/PC 浏览器从哪一侧访问页面。
3. `sunrise` 是否可写 `~/cloud-agent`、`~/.config/cloud-agent`、`~/.local/state/cloud-agent`。
4. 是否需要开机自启；是否有可用的 `systemd --user`/linger，还是接受 `nohup`（本部署默认 `nohup`）。
5. 真实路线注册表：route id、名称、区域、检查点顺序、每条路线允许的检查项 id/label、启用/停用状态。
6. 真实车辆注册表：id、显示名、能力（至少 `inspection` 与 `navigation`）、启用状态；不要提供实时位置/电量作为本服务输入。
7. 模型供应商的**非秘密**配置：OpenAI 兼容 `base_url`、`model`、是否支持 tools/tool_calls、`max_tokens`/超时限制。
8. API key 在设备上的既有受保护位置（只给路径和“sunrise 是否可读”），或确认需要在设备上新建 `~/.config/cloud-agent/cloud-agent.env` / `llm.key`。**不要把 key 内容发到聊天或写入工作区。**
9. 是否启用 `CLOUD_AGENT_ACCESS_TOKEN`；若启用，由谁在设备上生成和持有。
10. 计划时间使用的时区（如 `Asia/Shanghai`）和演示时段的可用性。

## 2. 安全检查（只读，不部署）

在 PC 上（PowerShell，使用既有严格 SSH 配置）：

```powershell
$Ssh = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$Key = "F:/xiaomiaiot/runtime/credentials/id_ed25519"
$Known = "F:/xiaomiaiot/runtime/credentials/known_hosts"

& $Ssh -b 192.168.137.1 -i $Key `
  -o "UserKnownHostsFile=$Known" -o "HostKeyAlias=192.168.137.134" `
  -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=8 `
  sunrise@192.168.137.134 "hostname; id -un; python3 --version"
```

工作区只读检查（不打印任何密钥内容）：

```powershell
cd "F:\xiaomi alot决赛codex工厂\platform\cloud-agent"
Get-ChildItem -Recurse -File |
  Select-String -Pattern 'BEGIN (OPENSSH|RSA|EC) PRIVATE KEY|sk-[A-Za-z0-9_-]{20,}' -CaseSensitive
```

预期无命中；测试里的 `test-secret-key`、代码里的 `sk-***` 是占位/脱敏文本，不是真实凭据。

设备端只读预检（上传脚本到 /tmp，运行后删除；不读取 env 内容，只输出布尔和权限）：

```powershell
$Scp = Join-Path $env:WINDIR "System32\OpenSSH\scp.exe"
& $Scp -i $Key -o "UserKnownHostsFile=$Known" -o "HostKeyAlias=192.168.137.134" `
  -o BatchMode=yes -o StrictHostKeyChecking=yes `
  .\scripts\check-device.sh sunrise@192.168.137.134:/tmp/check-device.sh

& $Ssh -b 192.168.137.1 -i $Key `
  -o "UserKnownHostsFile=$Known" -o "HostKeyAlias=192.168.137.134" `
  -o BatchMode=yes -o StrictHostKeyChecking=yes `
  sunrise@192.168.137.134 "bash /tmp/check-device.sh; rm -f /tmp/check-device.sh"
```

重点看：`PYTHON=Python 3.8.x`、`PORT_8090_IN_USE=0`、`ENV_FILE_MODE=600`（若已存在）、`LLM_KEY_SET=1`（若已配置）、`HOME` 可写。`check-device.sh` 不会打印 key。

## 3. 本地测试（不联网、不花钱、不需要 key）

```powershell
cd "F:\xiaomi alot决赛codex工厂\platform\cloud-agent"

python -m unittest discover -s tests -t . -v
python -m compileall -q cloud_agent app.py
python app.py --print-status
```

预期：

- 全部 `unittest` 通过（schema、配置、注册表、存储、Agent tool_calls 循环、HTTP、LLM 适配器）。
- `compileall` 无输出、退出码 0。
- `--print-status` 显示 `configured: false`（除非本机环境已有对应变量；不要在输出里找 key）。

### 3.1 本地未配置 503 验收（关键）

```powershell
# 清掉可能从本机环境继承的模型变量，确保是“未配置态”
$env:CLOUD_AGENT_LLM_BASE_URL = ""
$env:CLOUD_AGENT_LLM_MODEL = ""
$env:CLOUD_AGENT_LLM_API_KEY = ""
$env:OPENAI_API_KEY = ""

# 终端 A：启动，默认只监听 127.0.0.1:8091
cd "F:\xiaomi alot决赛codex工厂\platform\cloud-agent"
python app.py --host 127.0.0.1 --port 8091

# 终端 B：真实 HTTP 冒烟测试
cd "F:\xiaomi alot决赛codex工厂\platform\cloud-agent"
python scripts/smoke_test.py --base-url http://127.0.0.1:8091
```

预期冒烟输出包含：

- `PASS health ... status=unconfigured`
- `PASS unknown route rejected with clarification`
- `PASS unknown route created no proposal`
- `PASS proposal created ... execution=not_executed`
- `PASS approval recorded, still not executed`
- `PASS unconfigured chat returns 503 without mock reply`
- `SMOKE_OK=1`

这个测试会留下一条已批准的测试提案（`NOTE=smoke test leaves one approved test proposal in the store`），不会动任何车辆。

## 4. 部署

先 dry-run（只检查本地文件和工具，不 SSH、不写设备）：

```powershell
cd "F:\xiaomi alot决赛codex工厂\platform\cloud-agent"
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -DryRun
```

正式部署：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
```

默认参数（全部可覆盖）：

| 参数 | 默认 |
|---|---|
| `-TargetHost` | `192.168.137.134` |
| `-UserName` | `sunrise` |
| `-KeyPath` | `F:/xiaomiaiot/runtime/credentials/id_ed25519` |
| `-KnownHostsPath` | `F:/xiaomiaiot/runtime/credentials/known_hosts` |
| `-HostKeyAlias` | `192.168.137.134` |
| `-BindAddress` | `192.168.137.1` |
| `-RemoteDir` | `/home/sunrise/cloud-agent` |
| `-Port` | `8090` |
| `-ListenHost` | `0.0.0.0` |

脚本行为：

1. 本地跑测试 + `compileall`（`-SkipTests` 可跳过，不建议首次跳过）。
2. 打包 `platform/cloud-agent`，排除 `.deploy/`、`var/`、`__pycache__/`、密钥。
3. `scp` 到 `/tmp`，以 `sunrise` 运行 `remote-install.sh`，安装到 `~/cloud-agent/releases/<timestamp>`，切换 `current` 符号链接。
4. **不覆盖**已有的 `~/.config/cloud-agent/cloud-agent.env`；不存在时才创建 0600 模板，且 key 留空。
5. 用 `nohup` 启动，轮询 `/api/health`，打印 `HEALTH_JSON`（只含 version/status/configured）。
6. 清理远端 tar。

如果设备已有受保护的模型配置，不要把它拷回工作区；在设备 env 文件中设置路径即可：

```ini
CLOUD_AGENT_LLM_BASE_URL=https://<provider>/v1
CLOUD_AGENT_LLM_MODEL=<model>
CLOUD_AGENT_LLM_API_KEY=
CLOUD_AGENT_LLM_API_KEY_FILE=/home/sunrise/.config/cloud-agent/llm.key
```

创建 key 文件时用设备本地终端/编辑器，权限 600；不要用 `cat` 输出到聊天。配置后重跑 `deploy.ps1 -SkipTests` 重启服务（会保留 env）。

## 5. 部署后验收（设备上执行）

```powershell
& $Ssh -b 192.168.137.1 -i $Key `
  -o "UserKnownHostsFile=$Known" -o "HostKeyAlias=192.168.137.134" `
  -o BatchMode=yes -o StrictHostKeyChecking=yes `
  sunrise@192.168.137.134 "cd ~/cloud-agent/current && python3 scripts/smoke_test.py --base-url http://127.0.0.1:8090"
```

期望与本地相同。若尚未配置模型，503 那条必须通过；若已配置，脚本默认跳过 chat（不花 token），需要时可加 `--allow-chat`。

另外检查（安全摘要，不打印 key）：

```powershell
& $Ssh -b 192.168.137.1 -i $Key `
  -o "UserKnownHostsFile=$Known" -o "HostKeyAlias=192.168.137.134" `
  -o BatchMode=yes -o StrictHostKeyChecking=yes `
  sunrise@192.168.137.134 "cd ~/cloud-agent/current && python3 scripts/health_check.py --base-url http://127.0.0.1:8090"
```

`health_check.py` 在 `service` 不符或 `execution_available` 不为 `false` 时返回非 0。

日志检查（不打印 env 内容）：

```powershell
& $Ssh ... sunrise@192.168.137.134 "tail -n 60 ~/.local/state/cloud-agent/cloud-agent.log"
```

确认日志中没有 `Bearer`、`Authorization`、key 值；只有服务启动、配置状态、HTTP 摘要。

## 6. 验收清单

- [ ] 本地 unittest 全通过，`compileall` 退出 0。
- [ ] 本地未配置态：`/api/chat` 503，`llm_not_configured`，无 mock 答复。
- [ ] 部署后 `/api/health` 200，`service=velaguard-cloud-agent`，`execution.available=false`。
- [ ] `GET /` 200，CSP 同源，页面无内联脚本/样式。
- [ ] 未知路线 `validate` 422 + `clarification_required=true`；`proposals` 总数不变。
- [ ] 未登记路线 `POST /api/proposals` 422 + `proposal_created=false`。
- [ ] 合法路线创建提案 201，`status=pending_confirmation`，`execution.state=not_executed`。
- [ ] 批准后 `status=confirmed_not_executed`，`approval.state=approved`，`execution.state` 仍 `not_executed`。
- [ ] 重复决定 409。
- [ ] 无任何车辆动作、速度、坐标、执行日志。
- [ ] 设备 env/key 未出现在工作区、聊天、日志、`/api/health`。
- [ ] 若配置模型：一条真实对话返回 200；若未配置：保持 503，不伪造。

## 7. 回滚

部署使用版本目录 + `current` 符号链接，环境文件独立保留：

```bash
ls -1dt ~/cloud-agent/releases/* | head -n 5
kill "$(cat ~/.local/state/cloud-agent/cloud-agent.pid)" 2>/dev/null || true
ln -sfn ~/cloud-agent/releases/<previous-release> ~/cloud-agent/current
cd ~/cloud-agent/current
CLOUD_AGENT_ENV_FILE="$HOME/.config/cloud-agent/cloud-agent.env" \
CLOUD_AGENT_STATE_DIR="$HOME/.local/state/cloud-agent" \
nohup ./scripts/run-server.sh --host 0.0.0.0 --port 8090 \
  >> "$HOME/.local/state/cloud-agent/cloud-agent.log" 2>&1 &
echo $! > "$HOME/.local/state/cloud-agent/cloud-agent.pid"
```

回滚不会修改 `cloud-agent.env`，也不会删除提案状态。确认新进程健康后再清理旧 release；不要在未确认 PID/端口时做递归删除。

## 8. 明确不要做

- 不要把设备上的 `cloud-agent.env`、`llm.key`、API key、访问口令复制到工作区或聊天。
- 不要用假 key 启动“看起来已配置”的服务；没有 key 就保持未配置态，503 是正确行为。
- 不要为测试方便新增“执行”接口或把 `approved` 写成 `executed`。
- 不要修改 ACL/所有者来绕过 DSH 的文件权限问题；测试/部署在 Codex 已授权环境执行即可。
- 不要把样例路线/车辆当成现场标定；不要声称实时遥测、定位、电量。
- 不要并发让 DSH 与 Codex 改同一份生产文件；本目录由 DSH 写，Codex 执行与反馈，修改走差异。
