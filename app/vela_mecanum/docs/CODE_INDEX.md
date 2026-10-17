# 四车编队代码目录

> 本文所有路径均**相对参赛仓根目录**。

## 当前发布包

目录：`app/vela_mecanum/outputs/formation-kit`

这里保存正式运行入口、当前 planner、车端 agent、fleet endpoint、自动定位代码、地图资料、回归测试和发布包工具。后续功能修改以此目录为准。

## 历史资料

目录：`app/vela_mecanum/openvela/history/formation-dev-prototype`

这里保存早期 openvela 与 Formation Lab 的原型快照（`ai_agent/`、`deploy/`、`formation_lab/`、`generated/`、`ros2_ws/`）。该目录仅供核对，不参与当前发布包生成。

## 部署与诊断

目录：`app/vela_mecanum/work`

- `deploy_*.py`：车端部署与版本更新。
- `audit_*.py`、`inspect_*.py`、`verify_*.py`：服务、进程、版本和网络核验。
- `count_udp_*.py`、`run_udp_attribution.py`：UDP 数据量分析。
- `fetch_*.py`、`gather_robot_data.py`：读取车端配置和资料。
- `agent-stop-fix/`：systemd 停止流程文件。
- `agent-network-audit/`：部署与核验记录。
- `audit_after_teammate/`：四车源码、DDS 配置和检查结果。
- `control_sources/`：基础控制代码资料。
- `robot_data/`：地图、位姿和激光扫描资料。
- `keys/`：**现场连接文件的放置位置**。本仓只含该目录的说明 `keys/README.md`；
  实际使用的 SSH 私钥与固定主机密钥属敏感内容，**不随仓提交**，由操作者在现场自行放入。
- `runtime_config/`：车端运行配置副本。

> 本机 Python 虚拟环境（`formation-venv` 等）不随仓提交，运行时会按需重建。

## 常用命令

运行全部本地检查：

```powershell
& "app/vela_mecanum/outputs/formation-kit/test_local.cmd"
```

运行四车只读预检：

```powershell
& "app/vela_mecanum/outputs/formation-kit/run_formation.cmd" square --spacing 0.5 --check-only
```

运行正式方阵任务：

```powershell
& "app/vela_mecanum/outputs/formation-kit/run_formation.cmd" square --spacing 0.5
```

运行本地同步运动模式的四车预检：

```powershell
& "app/vela_mecanum/outputs/formation-kit/run_formation.cmd" square --spacing 0.5 --motion-mode synchronized --check-only
```

同步运动入口：

```powershell
& "app/vela_mecanum/outputs/formation-kit/run_synchronized_formation.cmd" square --spacing 0.5
```
