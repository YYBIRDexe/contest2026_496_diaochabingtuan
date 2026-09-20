# 四车自主定位与方阵编队

## 使用入口

本机工作目录：

`app/vela_mecanum`

本地仿真：

```powershell
& "app/vela_mecanum/outputs/formation-kit\run_formation.cmd" square --spacing 0.5 --simulate
```

四车只读预检：

```powershell
& "app/vela_mecanum/outputs/formation-kit\run_formation.cmd" square --spacing 0.5 --check-only
```

正式方阵任务：

```powershell
& "app/vela_mecanum/outputs/formation-kit\run_formation.cmd" square --spacing 0.5
```

四车同步运动模式：

```powershell
& "app/vela_mecanum/outputs/formation-kit\run_formation.cmd" square --spacing 0.5 --motion-mode synchronized
```

也可以使用专用入口：

```powershell
& "app/vela_mecanum/outputs/formation-kit\run_synchronized_formation.cmd" square --spacing 0.5
```

闭合场地路线仿真：

```powershell
& "app/vela_mecanum/outputs/formation-kit\run_formation_lap.cmd" --formation triangle --spacing 0.5 --bounds -2.6 2.6 -1.8 2.6
```

现场闭合路线入口：

```powershell
& "app/vela_mecanum/outputs/formation-kit\run_formation_lap.cmd" --formation triangle --spacing 0.5 --laps 1 --bounds -2.6 2.6 -1.8 2.6
```

路线边界使用地图坐标，程序在建立路线时检查地图自由区域、车间距和闭合段。全向轮速度使用世界坐标速度向量，车端允许速度上限为 0.875 m/s，该数值来自车端 `mentorpi.json` 的 `limits.max_linear_mps`。

正式闭合路线任务由四台小车同时执行。控制端发送带有统一 `trajectory_id` 的完整路线和低频心跳，车端 agent 根据本车 AMCL 位姿、雷达和队友状态自主跟踪路线。车端使用 `0.28 m` 前视距离连续通过拐角，减少逐个 waypoint 停顿；路线心跳中断约 `2 秒` 后车端自动停止。

四车同步运动模式会在同一个控制周期向四台小车发送各自速度向量，适合编队变换调试。闭合路线模式使用车端自主路线跟踪，控制端负责路线发布、状态检查和许可续期。

## 安全条件

- 四车地址为 `192.168.1.201–204`，SSH 用户为 `pi`。
- SSH 私钥位于 `work/keys/formation_autonomy_ed25519`。
- 固定主机密钥位于 `work/keys/formation_known_hosts`。
- 地图、车端代码校验值、agent 服务和 command bridge 服务全部通过后，程序才会继续。
- 四个 command bridge 全部确认短期许可后，程序才会发布 trajectory。
- agent 报告 `tracking` 且 command bridge 报告 `forwarding` 后，程序才会开始计算运动进展时间。
- 连续十秒没有至少 0.01 米进展时，程序发送全车停止指令并撤销许可。
- 定位、雷达、telemetry、路径规划、SSH 或许可续期异常都会停止任务。
- 程序退出时连续发送停止指令，并删除四车许可文件。

正式任务不会停止定位、雷达或电机安全桥服务。

## 当前验证状态

- `reconfiguration_agent.py` 使用 2 Hz 空闲发布频率和 10 Hz 运动发布频率，路线跟踪速度上限为 `0.875 m/s`。
- agent 支持 SIGINT 和 SIGTERM 安全退出，并在 ROS context 有效时发送五次零速指令。
- `fleet_endpoint.py` 可以连续输出原生 JSON telemetry。
- 短期许可权限为 `0644 root:root`，command bridge 使用只读方式验证许可。
- planner 会验证完整候选路线，候选路线未通过时继续检查其他候选路线。
- 本地回归测试共九项，全部通过。
- 三角编队闭合路线仿真速度为 `0.875 m/s`，单圈约 `15.06 秒`，最小车距为 `0.404 米`。
- 地图线段检查使用地图分辨率采样，A*单次搜索缓存线段安全结果和网格坐标；现场方阵规划耗时约 `5.4 秒`。
- 最近一次网络核验中，本机到路由器和四台小车各二十次 ping 均为 0% 丢包。
- 最近一次安全核验中，四车 agent 和 command bridge 均为 active，每车只有一个 agent，没有许可文件和 fleet endpoint 残留进程。
- robot1 与 robot4 的定位单元为 `mentorpi-localization-vendor-domain.service`，robot2 与 robot3 的定位单元为 `mentorpi-localization.service`。

当前 planner 更新已经通过本地现场位姿回归测试。更新后的正式方阵任务仍需现场观察完成情况。

## 代码目录

- `run_autonomous_formation.py`：任务控制、SSH telemetry、短期许可、停止处理和运行诊断。
- `payload/planner/formation_planner.py`：地图检查、目标分配、顺序路径规划和完整路线验证。
- `payload/planner/reconfiguration_session.py`：任务状态、telemetry 检查、暂停和重新规划。
- `payload/planner/reconfiguration_agent.py`：车端路线执行、前视跟踪、队友间距保护与雷达保护。
- `payload/planner/synchronized_formation.py`：四车同步路线生成和同步任务状态。
- `payload/planner/fleet_endpoint.py`：SSH 与 ROS 2 telemetry 连接。
- `payload/planner/auto_localize.py`：自动初始化 AMCL。
- `payload/planner/scan_localizer.py`：地图与激光扫描匹配。
- `payload/planner/simulate_current_map.py`：当前地图仿真。
- `payload/planner/test_reconfiguration.py`：planner 与 session 回归测试。
- `payload/evidence/current_map/`：当前地图和四车激光扫描样本。
- `payload/deploy/`：systemd 启动脚本和服务文件。
- `payload/baseline_robot1/`：车端基础控制代码资料。
- `payload/docs/`：历史源码资料。
- `build_bundle.py`：生成当前校验清单和压缩包。
- `verify_bundle.py`：检查当前校验清单。
- `test_local.cmd`：运行本地语法检查、回归测试、仿真和校验检查。

## 发布包

`manifest.json` 记录 `payload` 内每个文件的 SHA-256 和大小。`build_bundle.py` 只读取当前发布包内容，不会从历史目录复制源码。

生成发布包：

```powershell
& "app/vela_mecanum/work\formation-venv\Scripts\python.exe" "app/vela_mecanum/outputs/formation-kit\build_bundle.py"
```

生成文件为 `outputs/formation-kit-2026-09-19.zip`。

## 车端安装

本地安装检查：

```powershell
& "app/vela_mecanum/work\formation-venv\Scripts\python.exe" "app/vela_mecanum/work\install_formation_once.py" --check-only
```

四车安装入口：`app/vela_mecanum/outputs\install_formation_once.cmd`。安装程序逐车使用一次 SSH 连接，备份并安装规划、任务状态、agent、telemetry、自动定位、扫描定位、命令桥和命令限制文件，并将现有车端配置的线速度上限设为 `0.875 m/s`、加速度上限设为 `2.0 m/s²`。安装后检查两个服务、agent 数量、文件校验值和运动许可状态。任一车辆失败时立即终止，已经完成的车辆保持安装后的状态。
