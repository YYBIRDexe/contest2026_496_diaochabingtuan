# dist-openvela —— 部署产物（由本仓构建脚本生成）

本目录里的两个文件是 `node tools/build-openvela.js` 从 `../src/` 生成的**部署产物**，
用途是让评委不必装工具链也能看到「快应用最终长什么样」：

| 文件 | 说明 |
|---|---|
| `app.ux` | 单文件应用入口（七个视图编译进来的结果），约 134 KB |
| `manifest.json` | 快应用清单（包名 `com.velaguard.inspection`，720×1280） |

重新生成：

```bash
cd ..
node tools/build-openvela.js
# → build/openvela-app/{app.ux, manifest.json}
```

## ⚠️ 它不是官方签名包，请勿混称

- **官方要求的 `release.rpk` 本仓没有产出**。按官方《快应用开发指南（手动开发）》第三章，
  release.rpk 需要 **AIoT-IDE** 图形化打包 + 生成签名，本队未走这条链路。
- `app.ux` 由本仓 `tools/bundle.js`（自写的 ESM 打包器）生成，**不是** AIoT-IDE 的编译产物。
- 部署到 openvela 设备的方式是把这两个文件 push 到 `/data/app/<包名>/`，
  再在串口控制台 `vapp hap://app/com.velaguard.inspection`（见 `../docs/部署到openvela.md`）。

> **实测结论（如实声明）**：本应用**未能在 openvela 模拟器上跑起来**——
> `vapp` 触发 QuickApp 运行时的递归断言并复位板子，**官方自带 demo 同样崩溃**，属上游固件缺陷。
> 全过程与证据见本队工作区文档《模拟器部署-进度与恢复步骤》第十三节
> （该文档未随仓提交，此处仅作索引）。
