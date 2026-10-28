# 升级或换板前的备份只读预检

在拥有备份的私有机器上，从 `app/vela_spine` 运行：

```bash
python3 -m host.backup_preflight \
  --backup /home/ggbird/.spine-full-before-intent-final-20261028 \
  --target-task-states PENDING DISPATCHING DISPATCHED RUNNING BLOCKED \
    STOP_REQUESTED STOP_CONFIRMED COMPLETED FAILED CANCELLED
```

`--target-task-states` 必须来自实际目标固件对应源码的状态表。工具只检查声明的列表，不会从固件镜像自动识别能力；不能为了让预检通过而给旧固件添加其不认识的状态。尤其不能把含 `DISPATCHING` 的活动账本交给旧版本使用。

工具仅读取 `first/`、`check/` 两份快照，以及 `manifest.json` 和 `modes.json`。它核对每份清单文件的 SHA-256、目录权限记录是否齐全、相对路径是否越界、是否存在符号链接及清单外的业务文件，并检查主任务账本状态是否在声明列表中。备份脚本刻意忽略的 `lock`、`*.lock` 和 `*.tmp` 不算业务文件；工具不会删除它们。

退出码 0 表示这些只读检查通过；退出码 1 表示失败，保留全部文件等待核对。输出不包含凭据或文件正文。工具不执行恢复、烧录、重启、联网、修改权限或写入快照。

它不验证设备型号、闪存布局、镜像真实性、账本 CRC、硬断电恢复、当前设备的实际权限，也不验证新板迁移成功。两份快照可能同时过时，不能把一致性当作最新性。当前主机备份文件权限用于保护副本，原板权限保存在 `modes.json`；不能要求备份副本权限与原板相同。

部署前仍需按现有流程准备包含当前数据的私有镜像、逐项核验和安全恢复方案；部署后从真实板读回核对内容与权限，执行功能验收。凭据备份与私有镜像不得上传到 GitHub 或共享目录。
