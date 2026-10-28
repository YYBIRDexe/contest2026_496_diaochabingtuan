# 真板与模拟三车：一键验收

此流程会向真实 Gemini-S1 写入独立的测试目录，并可按参数正常重启开发板。车辆、事件和平台都是模拟，不产生真实运动；不要用于接入真实车辆的端口。默认做三轮，输出单独目录，不清理已有测试或用户数据。

## 前提

- Gemini-S1、Windows PC 和构建 VM 已启动；PC 与板处于可互通的私有网络。已验证的例子：PC `10.175.92.181`，板 `10.175.92.70`，VM `192.168.6.129`，Windows VMnet8 `192.168.6.1`，USB/IP 总线 `6-1`。IP 或总线变化需传入新值。
- 板上已安装本项目固件；VM 可免交互 SSH，并有 `/usr/lib/linux-tools/6.8.0-40-generic/usbip`、sudo USB/IP 权限以及 `adb`。
- VM 的 `/home/ggbird/codex-five-20261027/vela_spine` 应包含 `host/simulated_platform.py`、`host/acceptance_operator.py` 和 `host/acceptance_reboot.py`。此目录是已有构建副本，不自动覆盖。
- VM 上要预先准备仅供测试的 32 字节随机密钥，文件内容为 64 位小写十六进制；不要使用实体平台的控制密钥。示例路径 `/home/ggbird/.spine-acceptance-private/test-control.key`。本流程只传密钥文件路径，不打印密钥。
- 默认测试端口：PC 的 18161、18162 监听当前私有地址，18163 仅监听回环；VM 的 18172、18173 仅回环。端口被占用时脚本会失败，不会停止其他进程。

## 运行

在 `app/vela_spine` 中执行，路径和 IP 根据现场调整：

```powershell
python -m host.board_acceptance_run `
  --output-dir 'F:/xiaomi alot决赛codex工厂/设备验收/五项续作-20261027/example-run' `
  --prefix example01 `
  --identity 'F:/xiaomiaiot/runtime/credentials/id_ed25519' `
  --test-key /home/ggbird/.spine-acceptance-private/test-control.key `
  --pc-ip 10.175.92.181 --board-ip 10.175.92.70 --usb-bus 6-1 `
  --rounds 3 --reboot
```

每次必须使用新的 `--output-dir` 和 `--prefix`。不带 `--reboot` 时不重启开发板，报告中 `reboot_verified` 为 false。脚本只停止它自己启动的服务，并保留测试数据库与 `report.json` 以供审计；VM 中的测试数据库和 PID 文件也保留，避免下次重名覆盖。

每轮依次验证：网络不可达时任务保持待派发；三车接收并反馈运行；高风险回放触发停止确认并送达隔离模拟平台；模拟人工接单、处理、复核关闭，关闭后不自动重新授权；其他模拟任务完成；如指定重启，检查任务与人工关闭状态持久化。`all_passed` 为 true 只代表所选模拟流程通过。

USB/IP 在新步骤前可自动尝试重新接入；若某个写操作执行结果不确定，流程停止，不自动重放该操作。报错前可能已有模拟任务或事件，请查输出和独立根目录，不要删除或强行覆盖。`--reboot` 的 ADB 检查是短时观察，不能证明长期连接稳定。
