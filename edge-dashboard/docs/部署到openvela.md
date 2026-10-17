# 部署到 openvela（模拟器 / 开发板）

> **注意：这是备选方案，当前不适用。**
>
> M1 实训箱**不支持 openvela**，.rpk 快应用无法在其上运行。
> 本工程当前的实际部署方式是 **M1 的 Linux + 浏览器全屏看板**，
> 见 [部署到M1-Linux.md](部署到M1-Linux.md)。
>
> 保留本文档的原因：如果你后续拿到**确实支持 openvela 的开发板**
> （小米官方 AIoT 开发板、或自行编译 openvela 的板子），
> 这份步骤可以直接复用——src/ 下的界面源码本来就是 Vela 快应用工程。

---

本文给出把这套快应用推到 openvela 上的完整步骤与排错。
命令基于 openvela 官方《快应用开发指南（手动开发）》与《快应用调用 velaclaw 教程》。

---

## 〇、两条路径先分清

| | AIoT-IDE 内置模拟器 | openvela 模拟器 / 真机 |
| --- | --- | --- |
| 用途 | 开发阶段快速预览调试 | 验证真实 openvela 行为 |
| 获取 | 装 AIoT-IDE 即可 | 需在 **Ubuntu** 拉源码编译 |
| 你的情况 | 快速看效果走这条 | 你的虚拟机 Ubuntu 走这条 |

> 你已有 Ubuntu 虚拟机，所以真机路径可行。
> 注意：openvela 编译链只能在 Linux 下跑，Windows 侧无法交叉编译。

---

## 一、拉源码并编译（Ubuntu 侧）

```bash
# 1. 按官方快速入门装好依赖并 repo init（大赛环境用 dev-ai-contest-2026 分支）
repo init -u https://github.com/open-vela/manifests.git -b dev-ai-contest-2026

# 2. 拉代码
repo sync -c -j8

# 3. 配置（以 goldfish arm64 模拟器为例）
./build.sh vendor/openvela/boards/vela/configs/goldfish-arm64-v8a-ap --cmake -j8 menuconfig

# 4. 编译
./build.sh vendor/openvela/boards/vela/configs/goldfish-arm64-v8a-ap --cmake -j8
```

Windows 与 Ubuntu 虚拟机之间共享目录、或用 `scp` / `git` 把本工程传过去均可。

---

## 二、必须打开的配置项

### 1. 快应用运行环境（`menuconfig`）

```
CONFIG_FEATURE_FRAMEWORK=y       # Feature Framework
CONFIG_INTERPRETERS_QUICKJS=y    # QuickJS 解释器
CONFIG_LIBASH=y
CONFIG_LIBUV_EXTENSION=y
CONFIG_LIB_YOGA=y                # Flexbox 排版（关键：本工程大量用 flex 布局）
CONFIG_LV_USE_QRCODE=y
CONFIG_LV_USE_VECTOR_GRAPHIC=y
CONFIG_PROTOBUF_C=y
CONFIG_QUICKAPP=y                # 快应用框架
CONFIG_QUICKAPP_VAPP=y           # 独立运行模式
CONFIG_QUICKAPP_LOG_LEVEL=0      # 0=DEBUG，调试期建议打开
CONFIG_SYSLOG_CONSOLE=y
CONFIG_UTILS_CURL=y
```

### 2. 语音助手所需（`@system.velaclaw`）

```
CONFIG_EXAMPLES_AI_AGENT_VELA=y
CONFIG_FEATURE_SYSTEM_VELACLAW=y
CONFIG_MQ_MAXMSGSIZE=4096
```

改完配置后建议 `savedefconfig` 存一份：

```bash
./build.sh vendor/openvela/boards/vela/configs/goldfish-arm64-v8a-ap --cmake -j8 savedefconfig
```

---

## 三、打包成 rpk

### 方式 A：AIoT-IDE（推荐）

1. 「文件 → 打开项目」选中 `VelaGuard-Desktop`
2. 点 banner 栏「打包」→ 生成 `dist/velaguard-desktop.debug.<版本>.rpk`
3. 参赛 / 交付用「发布」生成签名后再打包，得到 `*.release.rpk`

> `debug.rpk` 只用于开发调试，正式提交请用 `release.rpk`。

### 方式 B：命令行

```bash
npm run build          # 若使用官方 toolkit
# 产物在 dist/ 下
```

### 本仓库的图标资源

图标由脚本生成，改了配色后重新生成即可：

```bash
node tools/make-icons.js
```

---

## 四、部署到 openvela 模拟器

```bash
# 1. 启动模拟器（会占用当前终端持续输出日志）
./emulator.sh cmake_out/vela_goldfish-arm64-v8a-ap/

# 2. 另开一个终端确认设备
adb devices        # 通常为 emulator-5554
```

### 1. 推中文字体（**必做**）

官方字体包下载：见《快应用开发指南（手动开发）》附件 `font.zip`。

```bash
unzip font.zip -d font
adb -s emulator-5554 push ./font /data/
```

字体落在 `/data/font/`。不推的话中文会白屏或乱码。

### 2. 解压并推送应用

rpk 本质是 zip 包，**目标路径必须带完整包名**，否则 `manifest.json` 会散落在
`/data/app/` 下导致 `Can not load manifest.json`。

```bash
# 包名与 src/manifest.json 的 package 字段一致：com.velaguard.desktop
unzip velaguard-desktop.debug.1.0.0.rpk -d com.velaguard.desktop

# 注意目标路径写成 /data/app/包名
adb -s emulator-5554 push com.velaguard.desktop /data/app/com.velaguard.desktop
```

确认最终结构为 `/data/app/com.velaguard.desktop/manifest.json`。

### 3. 启动应用

在**模拟器的串口控制台**（`emulator.sh` 所在终端）输入：

```
vapp hap://app/com.velaguard.desktop
```

> arm64 模拟器的 adb 只支持 push/pull，
> `adb shell vapp ...` 会返回 `error: closed`，必须在串口控制台执行。

### 4. 让语音助手可用（可选）

```bash
# 前台启动 ai_agent 并配置大模型
ai_agent
```

出现 `vela>` 提示符后：

```bash
# Token Plan 套餐用户（tp- 开头）
set_llm https://token-plan-cn.xiaomimimo.com/v1 <model> tp-你的套餐KEY

# 按量付费用户（sk- 开头）
set_llm https://api.xiaomimimo.com/v1 <model> sk-你的API_KEY

# 需要联网问答（天气、新闻）再配 Tavily
set_tavily_key <your_tavily_key>
```

`Ctrl+C` 退出，然后后台启动：

```bash
ai_agent &
vapp hap://app/com.velaguard.desktop
```

**不配置也能用**：语音助手会自动降级为「本地指令模式」，
巡检进度、阻塞原因、一键取消、生成汇总等指令本地即可回答。

---

## 五、部署到开发板

以带屏幕的开发板为例（如润芯微 7 寸 MIPI 屏 R528S3-Gemini-S1）：

### 1. 编译固件

```bash
./build.sh vendor/allwinnertech/boards/r528/r528s3-gemini-s1/configs/nsh/ -j8 distclean
./build.sh vendor/allwinnertech/boards/r528/r528s3-gemini-s1/configs/nsh/ -j8
```

### 2. 预置字体与应用

```bash
# 字体
cp ./font/* vendor/allwinnertech/lichee/board/common/data/res/fonts/

# 应用：解压后放进资源目录
mkdir -p vendor/allwinnertech/lichee/board/common/data/res/app
unzip velaguard-desktop.release.1.0.0.rpk -d com.velaguard.desktop
cp -r com.velaguard.desktop vendor/allwinnertech/lichee/board/common/data/res/app/
```

### 3. 打包固件

```bash
cd vendor/allwinnertech/lichee/
source envsetup.sh
lunch_nuttx          # 选择对应板型
pack                 # 只打包，不用重编内核
```

### 4. 烧录后在 nsh 里启动

```bash
cp -r /resource/app/com.velaguard.desktop /data/app/com.velaguard.desktop
vapp hap://app/com.velaguard.desktop
```

> NuttX nsh 的 `cp` 不支持通配符，必须写完整路径。

---

## 六、接外接触控显示器

本工程按 **1280×800** 设计基准（`src/manifest.json` → `config.designWidth`）。

- 屏幕分辨率不同 → 改 `designWidth` 即可，页面用 flex 布局自适应，
  没有写死坐标。
- 触摸输入由 openvela 显示驱动层处理，快应用侧无需额外代码；
  只要系统的触摸驱动正常，`onclick` 事件就能收到。
- 若触摸无响应，先确认开发板 defconfig 里的显示与触摸驱动已开启，
  再确认 LVGL 的输入设备已注册（这是系统层问题，不是应用层问题）。

---

## 七、排错速查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `Can not load manifest.json` | 应用目录结构不对 | 确认 `/data/app/包名/manifest.json` 存在 |
| `vapp` 找不到应用 | 包名不匹配 | 命令中的包名必须与 `package` 字段完全一致 |
| 白屏 / 中文乱码 | 缺中文字体 | 推字体到 `/data/font/` |
| `adb shell` 报 `error: closed` | arm64 模拟器限制 | 改用串口控制台执行设备内命令 |
| 改了应用不生效 | 旧包残留 | `rm -rf /data/app/com.velaguard.desktop` 后重新 push / cp |
| 语音助手无回复 | ai_agent 未运行 | 确认 `ai_agent &` 已启动且 `set_llm` 配置成功 |
| 联网类问答失败 | 未配 Tavily | `set_tavily_key <key>` |
| 布局全挤成一列 | Yoga / Flex 未启用 | 确认 `CONFIG_LIB_YOGA=y` |
| `cp -r` 报错 | nsh cp 限制 | 用完整路径，不用通配符 |

---

## 八、提交参赛代码（如需要）

提交到 `open-vela/packages_apps` 的 `dev-ai-contest-2026` 分支：

1. fork 仓库并切到 `dev-ai-contest-2026`
2. 在对应设备形态目录（如 `wearable/`）下新建应用目录
3. 放入**源码工程**（`src/`、`package.json` 等）**与** `release.rpk`
4. 发起 Pull Request

> 注意区分：`packages_apps` 是参赛提交目标（跑在 openvela 模拟器）；
> `packages_fe_examples` 只在 AIoT-IDE 内置模拟器里跑，仅供学习。
