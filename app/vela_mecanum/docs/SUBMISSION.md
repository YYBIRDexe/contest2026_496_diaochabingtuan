# 参赛仓库移交说明

目标仓库分支为 `dev-ai-contest-2026`。将本压缩包内容复制到参赛仓库根目录后，保留以下目录：

- `app/vela_mecanum/`
- `docs/`
- `logs/`
- `README.md`

仓库原有 `.github/`、manifest XML 与组委会配置文件继续保留。

如需让 repo manifest 自动映射 openvela 端 C 代码，可以把 `app/vela_mecanum/openvela/ai_agent/` 配置为 `<linkfile>` 来源，并将目标设置为 openvela 编译树中的对应 `packages/ai_agent/` 路径。Python 控制程序、ROS 2 包、文档与日志保存在参赛仓库中，方便评委查看和复现。

本包包含本地程序和 AI Coding 记录，没有包含 SSH 私钥、登录口令、Python 环境、缓存文件、完整 openvela 公共源码与重复的外部参考仓库。
