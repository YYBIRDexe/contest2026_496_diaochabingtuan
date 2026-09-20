# VelaGuard 巡检桌面

> **接手/新对话请先看**：工作区根目录 `..\接手必读.md` 与 `..\交接-20260919\`（完整交接包：
> 工作总报告、待办优先级、设计路线与红线、按调试时间线的代码清单）。
> AI 助手开工前读本目录的 `AGENTS.md`。

把「语音助手」这类程序包装成 app，用一个**手机式可视化操作页面**统一呈现，
跑在 **M1 实训箱的 Linux（Horizon X3M / Ubuntu）+ 外接触控显示器**上。

界面是**一个单文件 HTML**：零构建、离线可用、触控原生支持。
部署只有一件事——把它拷到 M1，全屏打开。

> **重要前提**：M1 实训箱**不支持 openvela**，所以不能用 `.rpk` 快应用方案，
> 也不能用 `@system.velaclaw` 端侧 AI。原因与取舍见
> [`docs/技术选型与兼容性.md`](docs/技术选型与兼容性.md)。

---

## 一、页面长什么样

打开后是一屏「桌面」：

| 区域 | 内容 |
| --- | --- |
| 状态栏 | **真实系统时间**、**数据源标签**（可点切换）、在线车辆数、电量 |
| 概览卡 | 一句话结论 + 已完成 / 进行中 / 阻塞 / 未开始 / 离线 计数 + 数据来源与更新时间 |
| 应用区 | 手机式磁贴栅格，每个磁贴是一个可进入的 app |
| 快捷坞 | 开始本轮巡检 / 一键取消 / 按住说话 |

**5 个 app**

| app | 作用 |
| --- | --- |
| 巡检调度台 | 4 车状态、任务清单、派单 / 取消 / 一键取消 |
| **语音助手** | 端侧对话界面，支持巡检控制与问答 |
| 区域与路线 | 4 个区域与固定路线、责任车辆 |
| 巡检记录 | 按轮次回看四区覆盖情况 |
| 系统与网络 | 设备、C1 链路、AI 配置、能力开关 |

---

## 二、立刻看效果（Windows 开发机，0 依赖）

**方式 A：直接双击**

打开 `preview/index.html` 即可，单文件自包含，断网也能用。

**方式 B：本地服务（推荐，便于反复刷新）**

```bash
node tools/build-preview.js     # 由 .ux 源码生成界面
node tools/serve.js 8123        # 起本地静态服务
```

浏览器打开 <http://127.0.0.1:8123/>。

> 顶部按钮可切换 5 个页面；页面里的按钮都能点，
> 「按住说话」、派单、取消等会真实改变数据并即时重绘。

**看板模式**：URL 加 `#kiosk` 隐藏顶部工具栏（正式部署时用）。
`#voice` 之类可直接进入某个 app。

---

## 三、接 M1 真实数据（已打通）

界面不直接跟 M1 说话，而是通过**数据源适配层**。三种模式，点状态栏的数据源标签即可切换：

| 模式 | 说明 |
| --- | --- |
| **演示数据** | `store.js` 端侧预设表，完全离线，不接车也能演示 |
| **M1 数据** | 轮询 `GET /data/state.json`；派单/取消 `POST /api/command` |
| **在线模拟** | 自动推进任务状态，用来验证「数据变→界面变」 |

**M1 侧只有一件事要做：按格式写 `data/state.json`。** 字段见
[`data/README.md`](data/README.md)。界面每 2 秒读一次，自动刷新，不用改代码。

### 不用真机就能验证整条链路

```bash
# 终端 A：起服务（同时提供状态接口与指令接口）
node tools/serve.js 8123

# 终端 B：模拟 M1 持续写状态
node tools/simulate-m1.js
```

浏览器打开 <http://127.0.0.1:8123/>，点状态栏右侧标签切到 **「M1 数据」**，
就能看到任务从「未开始 → 进行中 → 已完成／阻塞」自己走起来。

> ⚠️ **必须经 http 打开**才能接真实数据：浏览器禁止 `file://` 页面发起 `fetch`。
> 用 `file://` 双击打开时界面会自动停在演示数据模式，并给出提示，不会白屏。

---

## 三、部署到 M1

**已在真机验收通过**，结论与设备实测信息见
[`docs/M1验收报告.md`](docs/M1验收报告.md)。

### 一键验收（推荐）

```bash
$env:M1_HOST='192.168.1.104'; $env:M1_USER='sunrise'; $env:M1_PASS='<密码>'

node tools/vnc/run.js "pgrep -af voice_button"       # 通用远程执行（推荐入口）
node tools/vnc/run.js --file tools/vnc/scripts/diag-now.sh   # 语音链路现场体检
node tools/vnc/run.js --put <本地> <远端> / --get <远端> <本地>
node tools/vnc/accept-ssh.js            # 体检：系统/浏览器/网络/内存
node tools/vnc/accept-ssh.js --deploy   # 上传工程 + 部署
node tools/vnc/show.js                  # 在真实 X 会话打开看板并抓屏
node tools/vnc/show.js --url "http://127.0.0.1:8123/?src=file#kiosk"   # 真实数据模式
node tools/vnc/verify-live.js           # 验证真实数据链路（自动刷新）
```

> `tools/vnc/run.js` 是本轮新增的**统一远程执行器**：远端脚本 base64 传输、
> 密码走 `SSH_ASKPASS`（Windows 没有 sshpass），从此不用再为一次诊断写一遍
> SSH 样板。`tools/vnc/scripts/` 下是按用途分好的脚本（体检 / 部署 / 端到端复测 /
> 真机交互验证），都是可直接复用的。
>
> 端到端复测不用人说话：`tools/vnc/scripts/e2e-carcmd.sh` 用 TTS 合成一句话
> 再 `--inject-wav` 注进语音链路，能看到「识别 → 意图 → 查车 → 播报 → 写记录」
> 全链路每一行。

> 关键经验：**M1 上 Firefox 无头渲染不可用**（SWGL 无法映射 framebuffer），
> 必须走真实 X 会话 + `xwd`/`ffmpeg` 抓屏。细节见验收报告第三节。

### 手动部署

```bash
node tools/build-preview.js          # 1. 开发机生成界面
scp -r VelaGuard-Desktop <user>@<m1-ip>:~/   # 2. 拷到 M1
cd ~/VelaGuard-Desktop/linux && chmod +x *.sh && ./start.sh --serve   # 3. 全屏启动
```

确认没问题后 `sudo ./install.sh` 装成开机自启。

---

## 四、工程结构

```
VelaGuard-Desktop/
├── src/                          界面源码（Vela .ux 语法，由脚本编译）
│   ├── pages/Home/index.ux       桌面首页（磁贴栅格）
│   ├── pages/VoiceAssistant/     语音助手
│   ├── pages/Dispatch/           巡检调度台
│   ├── pages/Zones/              区域与路线
│   ├── pages/Records/            巡检记录
│   ├── pages/System/             系统与网络
│   ├── common/store.js           端侧预设表（演示数据源）
│   ├── common/source.js          ★ 数据源适配层（demo / file / sim）
│   └── manifest.json             应用信息与路由表
├── tools/
│   ├── build-preview.js          .ux → 单文件 HTML（核心编译脚本）
│   ├── make-icons.js             生成图标 PNG
│   ├── check.js                  工程自检（静态）
│   ├── test.js                   ★ 运行时测试（无头浏览器，33 项）
│   ├── serve.js                  ★ 看板服务 + 状态/指令接口
│   ├── simulate-m1.js            ★ 模拟 M1 写数据，验证真实链路
│   └── shot.js                   无头截图 + 渲染诊断
├── data/
│   ├── README.md                 ★ state.json 字段规范
│   ├── state.json                M1 侧写入的巡检状态（可选）
│   └── commands.log              界面下发的指令记录
├── preview/index.html            ★ 部署产物（单文件自包含）
├── linux/
│   ├── start.sh                  kiosk 全屏启动（自动探测浏览器）
│   └── install.sh                装成开机自启
└── docs/
    ├── 部署到M1-Linux.md          ★ 主要部署文档
    ├── 技术选型与兼容性.md
    └── 部署到openvela.md          备选：仅当你有 openvela 板子时
```

---

## 五、改哪里

### 接真实巡检数据

只改 M1 侧写的 JSON，**界面不用动**。字段规范见 [`data/README.md`](data/README.md)。

要换数据通道（比如不用轮询文件，改成 WebSocket 或直接读串口），
只需在 `src/common/source.js` 里加一个 adapter，
界面调用的是统一的 `source.get()` / `source.dispatch()`，不关心底层。

### 改演示数据（区域 / 车辆 / 任务）

`src/common/store.js`：

- `ZONES` 区域表（编号即责任划分）
- `CARS` 车辆表（各自独立 IP，避免重复接单）
- `RECORDS` 历史轮次
- `dispatchTask` / `cancelTask` / `cancelAll` / `markDone`

### 加一个 app（磁贴会自动出现）

1. 建 `src/pages/新页面/index.ux`
2. `src/manifest.json` → `router.pages` 加 `"新页面": { "component": "index", "path": "/newpage" }`
3. `src/pages/Home/index.ux` → `appRegistry` 加一条

### 改完界面

```bash
node tools/build-preview.js      # 重新生成
scp preview/index.html <user>@<m1-ip>:~/velaguard/preview/
```

看板刷新即可，不用重装。

---

## 六、自检与测试

```bash
npm test          # 一键跑全部：编译 + 静态自检 + 运行时测试 + 触摸测试
```

也可以分开跑：

```bash
node tools/build-preview.js                    # 由 .ux 生成界面
node --experimental-vm-modules tools/check.js  # 静态自检
node tools/test.js                             # 运行时测试（33 项）
node tools/test-touch.js                       # 触摸测试（13 项）
```

| 测试 | 覆盖内容 |
| --- | --- |
| `check.js` | manifest、路由页面齐全、模板闭合、JS 语法、class 定义、磁贴路由有效 |
| `test.js` | 产物自包含、六页渲染、数据源三态、读外部 JSON 并驱动重绘、指令 HTTP 下发、磁贴跳转、语音指令、派单与一键取消 |
| `test-touch.js` | **真实触摸事件**（CDP `Input.dispatchTouchEvent`）下的点击响应、触摸目标尺寸、滚动 |

浏览器实际渲染诊断 + 截图：

```bash
node tools/serve.js 8123
node tools/shot.js 8123 Home preview/_shot-Home.png
$env:VG_QUERY='src=file'   # 用真实数据模式截图
```

---

## 七、当前状态与后续

**已完成**：5 个 app 的界面与交互、真实数据驱动的汇总与派单、
语音助手（含本地指令兜底）、离线单文件打包、kiosk 启动与开机自启。

**待接入**（界面已预留，只差数据层）：

- M1 的真实巡检数据（当前用 `store.js` 端侧预设表演示）
- U1P 的声光与按键（界面入口已做好：一键取消）
- S3 麦克风（「按住说话」当前走模拟识别，替换 `recognize()` 即可）

**注意**：由于 M1 不支持 openvela，语音助手没有 `@system.velaclaw` 端侧 AI，
**当前以本地指令模式工作**——巡检进度、阻塞原因、一键取消、生成汇总
这些本地就能回答，不依赖大模型。

---

## 八、注意

- **设计基准 1920×1080**（`src/manifest.json` 的 `config.designWidth/designHeight`）。
  M1 + E5 触控屏实测帧缓冲为 1920×1080（说明书标注的 1280×800 不可信），
  界面按同尺寸设计，**1:1 铺满整屏、四边零黑边**，真机证据见 `preview/m1/m1-kiosk.png`。
  M1 的 X 被内核参数锁定在 1920×1080，`xrandr` 改不动，故按屏幕实际比例设计。
- 预览页默认**铺满窗口**；需要像素级 1:1 评审时用 `?scale=1`。
- 界面按 Vela 的盒模型编写并编译到 HTML（`<div>` 默认 flex 列容器、
  `<text>` 行内盒）。改样式时请遵守
  [`docs/技术选型与兼容性.md`](docs/技术选型与兼容性.md) 里的 CSS 子集约束，
  否则浏览器与预期会不一致。
