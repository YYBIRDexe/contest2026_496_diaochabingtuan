# VelaGuard 巡检快应用（openvela）

把 M1 实训箱上那套**「手机式触控程序」**移植到 **openvela 快应用**，并补齐**方案二的功能一~四（分区巡检）**：
区域与任务清单管理（功能一）、派单与路线执行（功能二）、异常中断与人工处置（功能三）、覆盖汇总与跨轮次记忆（功能四），
再加一页端侧 AI 对话。**小车行为刻意保持简单**——只有最朴素的原语：直行 → 到点停留 → 转向下一段；
**路线也短**：四条固定路线各 2~3 段，单步 ≤ 0.90 m，总长 **10.30 m**。
本工程不声称具备 SLAM / 导航 / 避障 / 自由路径规划能力，路线是**预设的**，车端只沿线走。

---

## 一、技术路线与关键事实

下面每条都是从**竞赛分支 `dev-ai-contest-2026` 源码**里核实过的，不是照文档转述，改动前请先确认它们仍然成立。

### 1.1 目标平台

| 项 | 值 |
|---|---|
| 板级配置 | `goldfish-arm64-v8a-ap`（openvela Vela Emulator） |
| 设备模拟器 AVD | `skin.name = xiaomi_smart_screen_10`，virtio-gpu |
| 屏幕 | **720 × 1280 竖屏**；`src/manifest.json` 的 `designWidth/designHeight` 已按此设置 |
| 包名 | `com.velaguard.inspection` |
| 启动 | 模拟器串口控制台 `vapp hap://app/com.velaguard.inspection`（**不是** `adb shell`——arm64 模拟器上会 `error: closed`） |

### 1.2 官方 defconfig：快应用运行时**已带**，`ai_agent` **没带**

`goldfish-arm64-v8a-ap` 的 defconfig 里**已经包含**快应用运行时，**不需要 menuconfig**：

```text
CONFIG_QUICKAPP=y                  CONFIG_QUICKAPP_VAPP=y
CONFIG_INTERPRETERS_QUICKJS=y      CONFIG_LIB_YOGA=y
CONFIG_GRAPHICS_LVGL=y             CONFIG_FEATURE_FRAMEWORK=y
CONFIG_INPUT_GOLDFISH_EVENTS=y
```

**缺的是** `CONFIG_EXAMPLES_AI_AGENT_VELA=y` —— `ai_agent` **不在默认配置里**，端侧 AI 对话要它为固件再编一次
（另需 `CONFIG_FEATURE_SYSTEM_VELACLAW=y` 与 `CONFIG_MQ_MAXMSGSIZE=4096`，后者不够会**静默丢消息**）。

| 你想要的效果 | 固件要不要重编 |
|---|---|
| 看界面、跑巡检功能一~四、地图动画 | **不用** |
| 语音页接真端侧 Agent（`@system.velaclaw`） | **要**，见 `docs/部署到openvela.md` 第二节 |

### 1.3 快应用 ↔ 端侧 Agent 的**唯一**官方通道

| 事实 | 说明 |
|---|---|
| 通道 | `@system.velaclaw.ask()` —— IDL `promise<AskResponse> ask(AskParam)` |
| 返回体 | `AskResponse = { reply, extra_info, tool_calls: [{name, result}] }` |
| 传输 | POSIX 消息队列 `/velaclaw_qapp_in`、`/velaclaw_qapp_out`，消息体 `"chat_id\ncontent"` |
| **没有** `@system.websocket` | 快应用侧根本没有这个模块，**别照着 WebSocket 28789 那套写** |
| **不能让 Agent 调任意工具** | 桥里的 `velaclaw_quickapp_bridge_call_tool()` 是个返回 `not_implemented` 的**桩** |

推论：本工程语音页只负责「把问题送进去 + 把回复和**它调了哪些工具**显示出来」，
「查车 / 派单」这类动作靠 Agent 自己按 Skill 去调**它自己的**工具，快应用不越权。
Agent 不可用时（没编进固件 / 没配 LLM / 浏览器预览）自动退到**本地指令表**并如实标注，演示不会卡住。

### 1.4 单页 + 仓内路由：**不使用 `@system.router`**

官方 Feature Framework 的 **modules 清单里没有 router 这个 JS 模块**（只有 C 层的 `ApplicationRoute` / `ApplicationStackPagePush`），
也就是说 `.ux` 里 `import router from '@system.router'` 在模拟器上**不一定能解析**。本工程用仓内路由绕开这个不确定性：

- `src/manifest.json` 的 `router.pages` **只有 `index` 一个页面**；
- 七个视图（桌面 + 六个磁贴页：调度台 / 地图与路线 / 区域与任务 / 巡检记录 / 语音助手 / 系统与链路）靠 `app-shell.js` 的 `navigate()` 按 `curPage` 条件渲染切换，**零系统依赖**；
- `src/common/router.js` 只提供页面标题与返回栈，是普通仓内模块。

代价是七个视图共用一个页面文件（编译时由 `tools/build-openvela.js` 拼装成一份 `app.ux`），
换来的是「不依赖未验证的系统模块」。

### 1.5 地图不是占位图

地图是**车端真实 ROS 地图** `classroom.pgm`（350 × 197 格，0.05 m/格，原点 `[-4.61, -4.1, 0]`）
自动转出来的**矢量轮廓**（**55 个墙块** + 7 处外边界缺口），落在 `src/common/map-data.js`（3.5 KB，自动生成，勿手改）。
详见 `docs/地图与路线.md`。

---

## 二、目录结构

| 路径 | 内容 | 说明 |
|---|---|---|
| `src/` | 源码（**唯一需要手改的地方**） | ES Module 语法，快应用与浏览器预览**共用同一份** |
| `src/common/data.js` | 端侧预设表 | 地图 / 航点 / 四条路线 / 四个区域 / 车辆 / 状态字典 / 阈值限值，**功能一的全部数据** |
| `src/common/map-data.js` | 地图矢量轮廓 | **自动生成**，由 `tools/ros-map-to-vector.js --auto` 产出，**不要手改** |
| `src/common/map.js` | 地图渲染（纯函数） | `makeProjector`（坐标系换算的唯一位置）、`ZONE_BLOCKS`、`renderMap` 出 SVG 字符串 |
| `src/common/store.js` | 任务状态机 | 功能一~四的逻辑主体（派单 / 推进 / 阻塞 / 改派 / 顺延 / 覆盖汇总 / 跨轮次记忆） |
| `src/common/agent.js` | 语音助手 | 端侧 Agent 通道封装 + **本地指令表兜底**（7 条规则） |
| `src/common/router.js` | 仓内路由 | 页面标题 + 返回栈 |
| `src/common/tpl.js` | 模板引擎 | 插值 / `if` / `each` / 转义，六个页面共用 |
| `src/common/ui.js`、`styles.js` | 浮层与公共样式 | toast、基础 CSS |
| `src/pages/` | 七个视图 | `Home` / `Dispatch` / `Map` / `Zones` / `Records` / `Voice` / `System`，各含 `tpl` + `data()` + `act` |
| `src/app-shell.js` | 宿主无关的应用外壳 | tick（250 ms）、切页、`[data-act]` 事件派发、重绘钩子 |
| `src/app.ux.tmpl` | openvela 入口**模板** | 生成 `build/openvela-app/app.ux`，**不要直接改产物** |
| `src/manifest.json` | 快应用清单 | 包名、`designWidth/designHeight` 720×1280、`features: ["system.velaclaw"]` |
| `tools/` | 全部脚本（15 个） | 见下表 |
| `docs/` | 文档 | `部署到openvela.md`、`模拟器验证命令单.md`、`地图与路线.md`、`E5-开拍执行单.md`、**`E5触控演示-录视频执行单.md`**、**`E5触控演示-口播稿与字幕时间轴.md`** |
| `device/` | **E5 触控演示版**（可跑、可录） | 见下方专节，**当前唯一能实际演示的形态** |
| `openvela-app/skills/inspection.md` | 自定义 Skill | 赛题必做项，含四类主动任务声明 |
| `build/` | **生成物，不要手改、不要提交为源** | 见下 |

### `build/` 是生成物

| 产物 | 由谁生成 |
|---|---|
| `build/velaguard.bundle.js`（122 KB，17 个模块） | `tools/bundle.js --target openvela`（经 `build-openvela.js`） |
| `build/bundle.browser.js` | `tools/bundle.js --target browser`（预览时现打） |
| `build/openvela-app/app.ux`（134 KB）+ `manifest.json`（0.6 KB） | `tools/build-openvela.js`，**部署到模拟器的就是这两个** |
| `build/ui-*.html`、`build/shot-*.html`、`build/shots/*.png` | `tools/shot.js` / `tools/test-ui.js` 的调试产物 |

### `tools/` 一览

| 脚本 | 作用 |
|---|---|
| `preview-server.js` | 零依赖预览服务，`http://127.0.0.1:8177`，每次请求**现打** bundle（改完 `src/` 刷新即可） |
| `run-tests.js` | 一键跑 6 步（先纯逻辑 → 模板 → 路线 → 界面 → 产物生成 → 产物自检）；**第一个失败即停**，`--keep-going` 可跑完 |
| `test-store.js` | 端侧预设表 + 任务状态机（54 项） |
| `test-tpl.js` | 模板引擎（36 项） |
| `test-ui.js` | 界面冒烟，**真实浏览器**（37 项） |
| `gen-waypoints.js` | 航点生成 / **路线合规校验**（`--check`） |
| `ros-map-to-vector.js` | ROS `classroom.pgm/.yaml` → 矢量轮廓（`--auto`） |
| `bundle.js` | 把 `src/` 打成单文件 bundle（`--target browser\|openvela`） |
| `esm.js` | 极小的 ESM→CJS 载入器，**只做语法转换、不复制代码**（避免"测试过了但源码不是那份"） |
| `host-browser.js` | 浏览器宿主（DOM 渲染 + 事件代理） |
| `build-openvela.js` / `check-openvela-app.js` | 生成 / 自检 openvela 产物（自检 13 项） |
| `shot.js` | 逐页渲染并截图到 `build/shots/` |
| **`vg.ps1`** | **设备助手（本机跑）**：`status` / `reset` / `start` / `stop` / `legacy` / `shot` / `ssh <cmd>`。**内置设备 SSH 私钥** —— 这台 PC 的默认身份在设备上未授权，裸敲 `ssh sunrise@192.168.1.104` 会 `Permission denied`。纯 ASCII，PS 5.1 直跑 |

---

## 三、怎么跑

三条命令，都在工程根目录执行（Windows PowerShell 直接可用）：

```powershell
# 1) 预览界面（零依赖，改完 src/ 刷新页面即可）
node tools/preview-server.js          # → http://127.0.0.1:8177

# 2) 跑全部测试与自检（6 步）
node tools/run-tests.js

# 3) 生成 openvela 产物 → build/openvela-app/{app.ux, manifest.json}
node tools/build-openvela.js
```

`package.json` 里也有等价脚本：`npm run preview` / `npm test` / `npm run build`，
另有 `test:logic` / `test:tpl` / `test:ui` / `check:routes` / `check:app` / `map` / `shots`。

部署到模拟器的完整流程（含中文字体、`adb push`、`vapp` 启动）见 **`docs/部署到openvela.md`**；
可直接复制粘贴的命令单见 **`docs/模拟器验证命令单.md`**。

---

## 四、测试现状：验证到什么程度

`node tools/run-tests.js` 当前**七步全绿**（`exit code 0`）。逐项：

| # | 步骤 | 命令 | 结果 |
|---|---|---|---|
| 1/7 | 端侧预设表 + 任务状态机 | `node tools/test-store.js` | **54 通过，0 失败** |
| 2/7 | 模板引擎 | `node tools/test-tpl.js` | **36 通过，0 失败** |
| 3/7 | 页面契约（模板动作 ↔ act 实现） | `node tools/check-page-acts.js` | **18 通过，0 失败** |
| 4/7 | 路线合规校验 | `node tools/gen-waypoints.js --check` | **4 条全合规**（2.30 / 2.60 / 2.70 / 2.70 m，最长步均 0.90 m，总长 **10.30 m**） |
| 5/7 | 界面冒烟 + 真实点击 | `node tools/test-ui.js` | **48 通过，0 失败** |
| 6/7 | openvela 产物生成 | `node tools/build-openvela.js` | 17 模块 / bundle 122 KB / `app.ux` 134 KB / `manifest.json` 0.6 KB |
| 7/7 | openvela 产物自检 | `node tools/check-openvela-app.js` | **13 通过，0 失败** |

合计 **169 项断言 + 4 条路线校验**。

### ✅ 已验证（在 Windows 本机真实执行过）

| 范围 | 怎么验的 |
|---|---|
| 端侧逻辑 54 项 | Node 里直接加载 **`src/` 下同一份源码**（`tools/esm.js` 只做语法转换，不复制代码——不存在"测的不是那份"） |
| 模板 36 项 | 同上，覆盖插值 / 转义 / `if` / `each` / 三层嵌套 |
| 页面契约 18 项 | 静态比对每个页面模板里的 `data-act` 与该页 `act` 表，防"按钮点了没反应" |
| 路线 4 条 | 用 `data.js` 的**实际数值**算长度与单步，不是手算 |
| 界面 48 项 | **真实浏览器**（本机 Edge）里渲染 + **真实点击** + 地图动画：点磁贴跳页、派单推进、故障注入转阻塞、改派换车、失联判定、语音页本地兜底 |
| 产物 13 项 | `build/openvela-app/app.ux` 里七个视图都能渲染、地图能画出四条路线、无残留 `import/export`、`data-act` 已改写成 `onclick` |

### ❌ 未验证（**需要接手的人按命令单去跑**）

| 未验证项 | 说明 |
|---|---|
| **openvela 模拟器上的实际运行** | ⛔ **已尝试并定位到上游缺陷**：`vapp hap://app/<包名>` 触发**递归断言**并复位板子，**官方自带 demo 同样崩溃**，故非本应用问题。证据与全过程见 `../模拟器部署-20260920/进度与恢复步骤.md` 第十三节。**当前的演示走 `device/`（E5 触控屏 + U2P Ubuntu），不走 openvela** |
| 中文字体 | 不推 `/data/font/` 会整屏方块，容易误判成"应用没起来"——**但这一步没实测过** |
| 触摸事件 | `data-act` → `onclick` 的改写逻辑只有产物自检（字符串级），真机上点得动没验过 |
| LVGL 下的 SVG 子集渲染 | 地图用的是 SVG 子集，浏览器支持不代表 LVGL 支持 |
| `@system.velaclaw` 实际通道 | 只在预览里验过**兜底路径**（本地指令表），真通道没接通 |
| `ai_agent` 是否编进固件 | 默认 defconfig **没有**，需重编，未执行 |

> 结论：**"界面与逻辑对"是本机验过的；"在 E5 触控屏上能演示"是设备实测过的；
> "在 openvela 上能跑"被上游固件缺陷阻塞，未验证。**
> 对外不要把它描述成"已在 openvela 上跑通"。

---

## 五、两条红线

### 🔴 红线 1：页面模块里**不要**把 `data.js` 的导入命名成 `data`

页面模块（`src/pages/*.js`）**导出**一个 `data()` 函数给外壳当视图数据源：

```js
export function data(ctx) { ... }
```

如果再写 `import data from '../common/data.js'`，同一作用域里就有两个 `data`，
打包时直接 **`Identifier 'data' has already been declared`** → 整页白屏。

**本工程统一用 `CFG`：**

```js
import CFG from '../common/data.js'   // ✅
// import data from '../common/data.js'  // ❌ 打包必炸
```

### 🔴 红线 2：改 `src/` 下的文件**只能用文件编辑工具**，不要用 PowerShell 的 `Get-Content -Raw` + `Set-Content`

**PowerShell 5.1 在没有 BOM 时会按 ANSI（GBK）读取 UTF-8 文件**，
`Get-Content -Raw` 读进来时中文就已经坏了，`Set-Content` 再写回去 = **不可逆的乱码**。
本工程就这样一次毁过 **8 个文件**（源码里的中文注释与界面文案全变问号）。

- ✅ 用文件编辑工具（read / edit / write）改 `src/` 下的任何文件；
- ✅ 需要脚本化批量处理时用 **Node**（`fs.readFileSync(p,'utf8')`），不要用 PS 5.1 的文本 cmdlet；
- ❌ 不要 `Get-Content -Raw ... | Set-Content ...`，也不要 `-Encoding` 试图补救 —— 读的那一步已经晚了。

---

## 六、另外两个已修的坑

| 坑 | 现象 | 修法 |
|---|---|---|
| **`export async function` 的转换** | `tools/esm.js` 用正则去掉 `export` 前缀时，只匹配了 `function` 而漏了 `async function`，产物里残留一个 `export` 关键字 → 浏览器 **SyntaxError、整页白屏** | 正则必须把 `async` 一起匹配：`^export\s+(async\s+function\|function\|const\|let\|var\|class)\s+`，并加一条「任何残留的行首 `export` 都去掉」的兜底 |
| **模块必须惰性求值** | 早期版本在 bundle 里**立即执行**所有模块，而模块是**按名字母序**跑的 → `agent` 先跑，它 `import` 的 `store` 还没注册 → `模块未注册` 报错、白屏 | `__def()` **只登记工厂不执行**，真正的求值推迟到第一次 `__mod()` 取用（`__resolve` 里「先标记再执行」，循环依赖也不会无限递归） |

---

## 七、E5 触控演示版（`device/`）—— 当前唯一能实际演示的形态

openvela 模拟器的 QuickApp 运行时存在缺陷（`vapp` 触发递归断言并复位，**官方 demo 同样崩溃**，见
`../模拟器部署-20260920/进度与恢复步骤.md` 第十三节），因此本工程**另做了一条可演示的路径**：

> 在 **M1/U2P 实训箱的 E5 触控屏**上，用 Firefox 全屏运行同一个应用，
> 手指点「开始巡检」→ 四台车按固定路线执行 → 1 号车遇障停车 → 弹出阻塞告警 → 轮次汇总。

| 项 | 值 |
|---|---|
| 运行位置 | U2P（Horizon X3M，**Ubuntu 20.04**）的 Firefox |
| E5 的角色 | U2P 的**外接触控屏**（1920×1080 横屏） |
| 应用代码 | **与正式版完全相同**（同一份 bundle，只换宿主外壳） |
| 车辆数据 | **两种模式**：默认仍是内置模拟数据（界面自带「模拟器演示」标签，刻意保留）；接了车端执行器则显示**真车实测进度** |
| 是否控制真车 | ✅ **可以** —— 见下面第七节之二（2026-09-20 加的真车联动） |

**快速上手**

```bash
ssh sunrise@192.168.1.104 "bash ~/velaguard/demo/run-demo.sh"    # 启动
ssh sunrise@192.168.1.104 "bash ~/velaguard/demo/reset.sh"       # 复位（录制前必做）
ssh sunrise@192.168.1.104 "bash ~/velaguard/demo/run-demo.sh --stop"
```

**完整说明见 [`device/README.md`](device/README.md)**（含横屏适配的三个坑、时间轴依据、与真车系统的区别、
口径红线、排错表）。

**要录视频就看这两份**：

| 文件 | 内容 |
|---|---|
| [`docs/E5触控演示-录视频执行单.md`](docs/E5触控演示-录视频执行单.md) | **照着做就能拍**：可达性自检、不用 SSH 的兜底流程、一分钟成片分镜表、剪辑、重录三路径、30 秒自检清单、离线兜底素材 |
| [`docs/E5触控演示-口播稿与字幕时间轴.md`](docs/E5触控演示-口播稿与字幕时间轴.md) | 口播稿（约 110 字）+ 逐条字幕时间轴 + 字幕样式 + 尾板诚实标注 + 禁语清单 |

更早的现场执行单（机位/反光/手部动作）见 [`docs/E5-开拍执行单.md`](docs/E5-开拍执行单.md)。

---

## 七之二、真车联动：按一下「开始巡检」，四台车真的动（2026-09-20）

上一节那个演示页原来只有**内置动画** —— 按下按钮界面上四台车在跑，真车一动不动。
2026-09-20 补上了执行链，**已实机验证**：

```
E5 屏蓝色「开始巡检」
  → POST 127.0.0.1:8127/patrol/start      车端执行器 patrol_controller.py（U2P 上）
  → 4 线程并行 → ros_car.py --robots N --cmd FORWARD/STRAFE_* --set distance_m=…
  → ws://192.168.1.20N:9090 → /cmd_vel    四台车真的动
  → 每 800 ms 回灌真实进度到界面（状态徽标 + 地图 + 记录页）
```

**实测那一轮（点屏幕触发的第 2 轮）**：四台车全部完成，`/odom` 逐步实测
0.892~0.904 m（命令 0.90 m），净航向漂移 ≤ 0.9°，记录页自动归档。

| 项 | 值 |
|---|---|
| 车端执行器 | `~/velaguard/demo/patrol_controller.py`（纯标准库，Python 3.8 可用） |
| 路线表 | `~/velaguard/demo/patrol_routes.json`（`route_mode`: `fixed` / `adaptive`） |
| 起停 | `bash ~/velaguard/demo/start-patrol.sh [--status|--stop|--selftest|--log]` |
| 开机自启 | `~/.config/autostart/velaguard-patrol.desktop`（`install-autostart.sh` 装/卸） |
| 完整交付 | [`真车联动-20260920/`](真车联动-20260920/)：代码 + 路线表 + 逐轮证据 + 截图 + **坑清单** |

> **要改界面就改 `tools/build-demo-e5.js` 再跑 `node tools/build-demo-e5.js`** ——
> `build/demo-e5.html` 是生成物。真车联动那两段是
> `tools/_patch_demo_realcar.js` 与 `_patch_demo_realcar2.js` 打进去的补丁，都可幂等重跑。
>
> ⚠️ **`fixed` / `adaptive` 的差别必须先弄明白**：`fixed` 严格照地图上那四条固定路线，
> 但要求车按摆放说明摆好且每步方向有 ≥ 距离+0.20 m 净空，否则车端雷达会直接拒动；
> `adaptive`（默认）保留同一个闭环形状，方向与距离按现场雷达实时选，车摆哪儿都能跑完。
> 细节与实测数据见交付目录的 README 第三节。

---

## 八、相关文档

| 文件 | 内容 |
|---|---|
| `docs/地图与路线.md` | 底图来源、两个坐标系与换算、四条路线完整航点表、区域分区块、怎么改成真实航点、门洞检测与"只画图不控制"的边界 |
| `docs/部署到openvela.md` | 重编固件、`menuconfig`、`adb push`、中文字体、Skill 安装、13 项验收清单、排错速查 |
| `docs/模拟器验证命令单.md` | 可直接复制粘贴的命令单（给另一台电脑用） |
| `openvela-app/skills/inspection.md` | 自定义 Skill（赛题必做项） |
