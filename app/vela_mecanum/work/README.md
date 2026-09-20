# 部署、诊断与记录

## 当前部署工具

- `deploy_formation_planner.py`：顺序同步 planner，备份原文件，不重启服务，不创建许可。
- `deploy_kit_agent_lifecycle_fix.py`：顺序同步 agent，逐车重启并核对单实例。
- `deploy_fleet_endpoint_bool_fix.py`：同步 fleet endpoint，不重启常驻服务。
- `deploy_agent_stop_fix.py`：安装 systemd 停止流程。
- `deploy_agent_rate_fix.py`：安装 agent 发布频率与信号处理版本。
- `deploy_autonomous_formation.py`：早期自主编队部署工具，保留用于核对部署过程。
- `deploy_reconfiguration.py`：早期变阵服务部署工具，保留用于历史核对。

所有部署工具都需要固定主机密钥和当前 SSH 私钥。运行前必须确认四车没有运动许可。

## 当前诊断工具

- `audit_agent_network.py`：服务、进程、许可、无线和日志检查。
- `read_only_blocker_audit.py`：编队阻塞项检查。
- `diagnose_fleet_endpoint_exit.py`：fleet endpoint 退出原因检查。
- `count_udp_by_process.py`、`count_udp_peers.py`、`run_udp_attribution.py`：UDP 数据量归因。
- `verify_agent_restart.py`：agent 重启状态检查。
- `test_bridge_lease_handshake.py`：短期许可读取测试，不发送 waypoint。
- `fetch_*.py`、`gather_robot_data.py`：车端配置与资料读取。

## 资料目录

- `agent-stop-fix/`：当前 systemd 停止流程文件。
- `agent-network-audit/`：部署和检查结果。
- `audit_after_teammate/`：四车源码、DDS 配置和检查结果。
- `control_sources/`：基础控制代码资料。
- `robot_data/`：地图、位姿和激光扫描资料。
- `runtime_config/`：车端启动脚本和环境配置资料。
- `keys/`：SSH 私钥、公钥和固定主机密钥。
- `formation-venv/`：本机 Python 环境。

当前发布包位于 `outputs/formation-kit`。发布包生成与校验统一使用其中的 `build_bundle.py` 和 `verify_bundle.py`。
