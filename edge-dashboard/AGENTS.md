# AGENTS.md · VelaGuard 巡检桌面（AI 助手开工必读）

> 本文件是给**任何 AI 助手 / 新接手的人**看的：开工前 60 秒读完，能省几小时。
> 人看的完整版在 `../交接-20260919/`（工作区根目录下）。

## 这是什么

小米 AIoT 实训箱 M1（Ubuntu 20.04 / aarch64 / 1920×1080 外接触控屏）上的
**手机式触控看板**：`.ux` 源码 → 编译成**单文件 HTML** → 浏览器 kiosk 全屏；
「语音助手」app 驱动 M1 上原有的 `voice_pipeline`（云端 ASR → 意图 → 下发小车 → TTS 播报）。

## 开工三步

1. **先查历史对话**（本工作区已有 8 个对话，别重复调研）：
   `node "$env:DSH_HOME\skills\cross-session-context\scripts\session-context.cjs" --list`
   再用 `--grep "关键词"` / `--show <id> --turn N`。
2. **读当前状态**：`docs/当前状态与恢复步骤.md`（新对话入口）。
3. **读设计路线**：`../交接-20260919/03-设计路线与红线.md`（哪些不要做）。

## 硬约束（违反会出事）

- 界面产物必须**单文件自包含、离线可开**：不要引 CDN / 外链字体 / 外部 JS。
- 改数据必须走 Proxy：页面里 `this.x = ...`，测试里 `window.__velaguard.patch({...})`。
  **直接改 `getData()` 拿到的对象不会重渲染**，会让断言变成空断言。
- 语音不要自己重做：设备上那条 `voice_pipeline` 才是唯一链路；
  本地 vosk 模型是**有意删掉的**（云端 ASR 架构）。
- 下发小车只走 `vcmd`；`stop` 等安全关键只走本地规则。
- 改 `/home/sunrise/voice_pipeline/` 前：`ls -lt` + 备份 + 幂等补丁脚本 +
  `compile()` 校验（`ast.parse` 拦不住 `continue` 位置错误）+ 重启服务 + 实机验证。
- 不要改笔记本的电源/网络策略：设备出网靠它的代理 + SSH 反向隧道。
- 不要随手改唤醒词或交互策略，这类改动先跟用户说清代价。

## 验收（"改好了"必须有证据）

```powershell
npm test                                                   # 静态 + 运行时41 + 触摸13 + 溢出8 + 语音27 + 滚动24
node tools/vnc/run.js --file tools/vnc/scripts/diag-now.sh  # 设备侧体检
node tools/vnc/run.js --file tools/vnc/scripts/e2e-carcmd.sh # 不用人说话的端到端语音复测
```

真机证据优先于推理；历史结论（"已经修好"）一律回文件/设备核实再用。

## 设备

`sunrise@192.168.1.104` / 密码 `sunrise`（`sudo` 同密码，用 `echo sunrise | sudo -S -p "" <cmd>`）。
看板 `/home/sunrise/velaguard/`；语音管线 `/home/sunrise/voice_pipeline/`（不在 git 里）。
