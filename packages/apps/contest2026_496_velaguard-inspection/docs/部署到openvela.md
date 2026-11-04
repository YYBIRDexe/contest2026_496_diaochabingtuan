# 把 VelaGuard 巡检快应用部署到 openvela 模拟器

> 目标平台：**openvela Vela Emulator，板级配置 `goldfish-arm64-v8a-ap`**，
> 大赛分支 `dev-ai-contest-2026`。
> 屏幕 **720×1280 竖屏**（AVD 用 `skin.name = xiaomi_smart_screen_10`，virtio-gpu 720×1280），
> 本应用的 `manifest.json` 已按这个尺寸设 `designWidth/designHeight`。

---

## 〇、先说清一件容易误判的事

官方 `goldfish-arm64-v8a-ap` 的 **defconfig 里已经带快应用运行时**，不需要 menuconfig：

```
CONFIG_QUICKAPP=y                 CONFIG_QUICKAPP_VAPP=y
CONFIG_INTERPRETERS_QUICKJS=y     CONFIG_LIB_YOGA=y
CONFIG_FEATURE_FRAMEWORK=y        CONFIG_GRAPHICS_LVGL=y
CONFIG_GOLDFISH_GPU_FB=y          CONFIG_INPUT_GOLDFISH_EVENTS=y
CONFIG_LIBASH=y                   CONFIG_LV_USE_NUTTX_TOUCHSCREEN=y
```

**但 `CONFIG_EXAMPLES_AI_AGENT_VELA=y` 不在默认配置里** —— 端侧 AI 对话要它。
所以固件只需要为"ai_agent"再编一次：

| 你想要的效果 | 固件要不要重编 |
|---|---|
| 看界面、跑巡检四个功能、地图动画 | **不用** |
| 语音页接真端侧 Agent（`@system.velaclaw`） | **要**，见第二节 |

---

## 一、只在现有固件上跑界面（不重编）

在 Windows 上生成产物：

```powershell
cd "F:\xiaomiaiot\02-openvela迁移\openvela-VelaGuard快应用-20260920"
node tools\build-openvela.js
node tools\check-openvela-app.js      # 13 项自检，全绿再往下走
```

产物在 `build\openvela-app\`：`app.ux`（150 KB）+ `manifest.json`。
把这两个文件拷到那台 Ubuntu 上，然后：

```bash
# Ubuntu 侧，在模拟器已启动之后
adb devices                      # 期望看到 emulator-5554
adb connect 127.0.0.1:5555       # 若没看到设备

# ⚠️ 目标路径必须带完整包名，且是**解包后的目录**（rpk 就是 zip）
#    这里我们直接推目录，效果一样
PKG=com.velaguard.inspection
adb push app.ux      /data/app/$PKG/app.ux
adb push manifest.json /data/app/$PKG/manifest.json

# 在**模拟器串口控制台**里启动（不是 adb shell —— arm64 模拟器的 adb shell 会 error: closed）
vapp hap://app/com.velaguard.inspection
```

### 中文字体（不推会白屏或方块）

官方字体包在《快应用开发指南（手动开发）》附件 `font.zip`：

```bash
unzip font.zip -d font
adb push ./font /data/
# 落在 /data/font/
```

> 这是最容易卡住的一步。**先推字体再启动应用**，否则界面上全是方块，
> 很容易误判成"应用没跑起来"。

### 数据目录（有坑，先确认再 push Skill）

源码 `include/agent_config.h` 的默认值是 `/data/agent`，
而 ai_agent 的 goldfish README 与大赛快应用教程写的是 `/data/ai_agent/config/`。
**两者不可能都对**，动手前先在设备上确认：

```text
# 在 ai_agent 的 vela> 提示符里
config_show
list_dir /data
```

以**设备上实际存在的目录**为准，再 push Skill（见第三节）。

---

## 二、要端侧 AI 对话，就把 ai_agent 编进去

在那台 Ubuntu 的 openvela 源码树里：

```bash
cd ~/openvela
./build.sh vendor/openvela/boards/vela/configs/goldfish-arm64-v8a-ap/ --cmake -j$(nproc) menuconfig
```

`menuconfig` 里打开（其余保持默认）：

```
Application Configuration → Packages → Vela AI Agent      → CONFIG_EXAMPLES_AI_AGENT_VELA=y
Feature Framework → system.velaclaw                        → CONFIG_FEATURE_SYSTEM_VELACLAW=y
System Type → IPC → POSIX message queues 大小              → CONFIG_MQ_MAXMSGSIZE=4096
```

`CONFIG_MQ_MAXMSGSIZE=4096` **必须**：快应用与 Agent 之间的通道走 POSIX 消息队列
（`/velaclaw_qapp_in`、`/velaclaw_qapp_out`），消息体是 `"chat_id\ncontent"`，
默认队列大小不够会静默丢消息。

然后重编 + 起模拟器：

```bash
./build.sh vendor/openvela/boards/vela/configs/goldfish-arm64-v8a-ap/ --cmake -j$(nproc)
./emulator.sh cmake_out/vela_goldfish-arm64-v8a-ap/
```

### 配 LLM 后端

在 NSH 提示符（`goldfish-armv8a-ap>`）里：

```text
ai_agent                 ← ⚠️ 必须**前台**运行，加 & 之后 set_llm/ask 会报 command not found
```

提示符变成 `vela>` 后（**参数位有三种形态，别搞混**）：

```text
set_llm https://api.xiaomimimo.com/v1 <model> sk-你的KEY     # URL 形态：第2位是 model，第3位是 key
set_llm deepseek sk-你的KEY                                  # preset 形态：第2位是 key
```

preset 全集：`kimi / qwen / deepseek / glm / openai / claude / mimo / openrouter`。

冒烟：

```text
ask 你好，用一句话介绍你自己
```

判据：先回 `Sent to agent: ...`，随后**异步**出现中文回复。

> 🔴 录屏时这一步会敲出 API Key。需要"已配置"的画面时改用 `config_show`（key 会脱敏成 `sk-x****`）。

### 装上 Skill

```text
install_skill inspection <https-url>          # URL 必须是 https://，name 只允许 a-z0-9-_
read_file /data/agent/skills/inspection.md    # 路径按第一节确认过的目录改
```

或直接 push：

```bash
adb push skills/inspection.md /data/agent/skills/
```

Skill **热加载**（按 文件名+大小+mtime 检测），改完不用重启进程。

### 主动能力（赛题的「主动+执行」得分点）

```text
cron_start            → 期望 "Cron scheduler started."
heartbeat_trigger     → 期望 "Heartbeat: triggered agent check."
```

> ⚠️ `cron_add` / `read_file` **不是 CLI 命令** —— 它们只在 Agent 的**工具表**里，
> 由 LLM 通过 `ask ...` 自己调。在 `vela>` 直接敲 `cron_add` 会 `Unknown command`。
> CLI 里能敲的只有 `cron_start`。
>
> 主动任务的落地方式是**文件驱动**的：写 `/data/agent/HEARTBEAT.md`（心跳每 30 分钟读一次），
> 或用 cron 服务（`/data/agent/cron.json`，最多 16 个任务，10 秒轮询一次）。
> 本项目的四类主动任务声明写在 `openvela-app/skills/inspection.md` 里。

---

## 三、验收清单（照着打勾）

| # | 检查 | 命令 | 期望 |
|---|---|---|---|
| 1 | 平台跑起来了 | `./emulator.sh cmake_out/vela_goldfish-arm64-v8a-ap/` | 出现 `goldfish-armv8a-ap>` |
| 2 | 设备可见 | `adb devices` | `emulator-5554` |
| 3 | 中文字体已推 | `adb shell ls /data/font` | 有字体文件 |
| 4 | 应用已部署 | `adb shell ls /data/app/com.velaguard.inspection` | 有 `app.ux`、`manifest.json` |
| 5 | 应用能启动 | 串口控制台 `vapp hap://app/com.velaguard.inspection` | 出现**手机式桌面**：状态栏时间 + 六个磁贴 |
| 6 | 触摸能用 | 手指/鼠标点「巡检调度台」 | 页面切换 |
| 7 | 巡检能跑 | 点「开始本轮巡检」 | 四张任务卡从待执行 → 进行中 → 已完成 |
| 8 | 地图有动画 | 进「地图与路线」 | 四个小车标记沿线移动，进度条跟着走 |
| 9 | 异常能处置 | 调度台点「2 号车遇障」 | 立刻转阻塞 + 弹出告警，可「改派」/「顺延」 |
| 10 | 阈值主动能复现 | 调度台点「3 号车失联」 | 下一次判定（≤250 ms）即判阻塞，文案含「20 秒」 |
| 11 | 汇总与记忆 | 「收轮归档」→ 再「开始本轮巡检」 | 桌面出现「跨轮次提醒」 |
| 12 | 端侧 AI（需第二节） | 语音页输入「现在四台车都在线吗」 | 标「端侧 Agent」，并显示它调用的工具名 |
| 13 | Skill 生效（需第二节） | `vela> ask 开始巡检` | 按 Skill 派单，回复适合朗读 |

第 12 项**不通过也没关系**：Agent 不可用时语音页会退到**本地指令表**并在状态条上写明，
巡检控制类问句照样答得出来（演示不会因为没配 Key 就卡住）。

---

## 四、调试通道（实测补充，很有用）

### 6.1 🔴 从 SSH 敲不到 NSH —— 用 FIFO 接管输入

如果模拟器是从 SSH 起的（或跑在 Xvfb 上），你会发现**没有任何办法把命令敲进 NSH**。实测全部失败：

| 尝试 | 结果 |
|---|---|
| `adb -s emulator-5554 shell ...` | `error: closed`（arm64 模拟器限制） |
| 模拟器控制台 `event text ...` + `event send EV_KEY` | 注入成功，但日志/屏幕**零回显** |
| `adb forward tcp:2323 tcp:23` + telnet（guest 里 telnetd 在跑） | TCP 能连，**一个字节都不返回** |
| `xdotool`（XTEST 与 `--window` 直投都试过） | Xvfb 无窗口管理器，`_NET_ACTIVE_WINDOW` 不支持 |

**唯一有效的办法：把模拟器的 stdin 接一个命名管道（FIFO）**，然后往里写命令：

```bash
FIFO=/home/ggbird/nsh-fifo
LOG=/home/ggbird/openvela/emulator.log

# 1) 停掉当前模拟器
pkill -9 -f 'qemu-system-aarch64'; pkill -f 'emulator.sh'; sleep 4

# 2) 建 FIFO，**写端必须常开**（fd 3）
rm -f "$FIFO"; mkfifo "$FIFO"
exec 3<> "$FIFO"

# 3) 重启模拟器，stdin 接 FIFO
cd ~/openvela
setsid nohup env DISPLAY=:99 ./emulator.sh cmake_out/vela_goldfish-arm64-v8a-ap/ \
  < "$FIFO" > "$LOG" 2>&1 &
sleep 110        # 等 NSH 起来
grep -qE 'goldfish-armv8a-ap>' "$LOG" && echo "NSH 就绪"

# 4) 敲命令 —— 注意写的是 fd 3 而不是 FIFO 路径
printf 'ps\n' >&3
sleep 3
tail -20 "$LOG" | sed 's/\x1b\[[0-9;]*[A-Za-z]//g'
```

**两个坑（都踩过）：**

- **写端必须常开。** 写端一关，QEMU 的 stdin 就读到 EOF。
  所以用 `exec 3<> "$FIFO"` 保持一个 fd，注入时写 `>&3`；**不要在每次注入时重新 `> $FIFO`**。
- **`-show-kernel` 会把 NSH 的全部输出写进 QEMU 的 stdout** ——
  也就是 `emulator.log`（`/proc/<qemu-pid>/fd/1` 指向它）。
  所以**不需要看屏幕**就能读到命令回显。日志里能直接 grep 到历史命令：
  ```bash
  grep -nE '^goldfish-armv8a-ap>' ~/openvela/emulator.log | tail -20
  ```

### 6.2 在 Xvfb 上抓模拟器画面

模拟器跑在 Xvfb 上时 `xwd -root` 会 `BadMatch`，但**按窗口 ID 抓是可以的**：

```bash
export DISPLAY=:99; unset XAUTHORITY
WID=$(xwininfo -root -children | grep 'Android Emulator' | grep -oE '0x[0-9a-f]+' | head -1)
xwd -id "$WID" -silent -out /tmp/g.xwd
# 转 PNG（PIL；xwd 头里 bytes_per_line 在**第 12 个字段**，不是第 8 个）
python3 -c "
import struct; from PIL import Image
d=open('/tmp/g.xwd','rb').read(); h=struct.unpack('>25I',d[:100])
w,hh,bpl,nc,hsz=h[4],h[5],h[12],h[19],h[0]
raw=d[hsz+nc*12:hsz+nc*12+bpl*hh]
Image.frombytes('RGBA',(w,hh),raw,'raw','BGRA',bpl).convert('RGB').save('/tmp/emu.png')"
```

> `grim` 不行：GNOME 合成器不支持 `wlr-screencopy-unstable-v1`。
> D-Bus 的 `org.gnome.Shell.Screenshot` 也被策略拒绝（`Screenshot is not allowed`）。

### 6.3 中文字体（不推会白屏/方块）

**字体包就在源码树里**，不用去官网找：

```bash
cd ~/openvela
unzip -o docs/zh-cn/contest_2026/quickapp/attachment/font.zip -d /tmp/font
adb -s emulator-5554 push /tmp/font /data/
# 结果：/data/font/font/ 下有 9 个 ttf（MiSans 系列 + simhei）
```

### 6.4 官方 demo 快应用（用于排查，很有用）

源码树里带两个 `.rpk`，是排查"到底是我的应用有问题还是运行时有问题"的对照物：

```bash
# 官方 AI agent demo（就是调 @system.velaclaw 的那个）
unzip -o packages/ai_agent/defconfigs/goldfish-arm64-v8a-ap/com.application.agent.demo.debug.1.0.0.rpk -d /tmp/demo
adb push /tmp/demo/. /data/app/com.application.agent.demo/
# 串口控制台：
vapp hap://app/com.application.agent.demo
```

> ⚠️ **push 时注意尾部的 `/.`**：`adb push /tmp/demo /data/app/` 会建成 `/data/app/demo/`（少了包名那层），
> 结果 `vapp` 找不到应用。必须 `adb push /tmp/demo/. /data/app/<包名>/`。

---

## 五、排错速查

| 现象 | 原因 | 处理 |
|---|---|---|
| 白屏 / 全是方块 | 缺中文字体 | 推 `/data/font/`（第一节） |
| `Can not load manifest.json` | 目录结构不对 | 确认 `/data/app/包名/manifest.json` 存在 |
| `vapp` 找不到应用 | 包名不匹配 | 命令里的包名要与 `manifest.json` 的 `package` 完全一致 |
| `adb shell` 报 `error: closed` | arm64 模拟器限制 | 改用**串口控制台**执行设备内命令 |
| 改了应用不生效 | 旧包残留 | `rm -rf /data/app/包名` 后重新 push |
| 布局全挤成一列 | Yoga / Flex 未启用 | 确认 `CONFIG_LIB_YOGA=y`（默认已开） |
| 按钮点了没反应 | `data-act` 没被改写成 onclick | 看 `build/openvela-app/app.ux` 里有没有 `onclick="dispatch(` |
| 语音页一直"本地指令模式" | `ai_agent` 没跑 / 没配 LLM / 没开 velaclaw | 见第二节；`config_show` 查配置 |
| `ai_agent` 里 `set_llm` 报 command not found | 它是**后台**跑的 | 前台运行（不加 `&`） |
| 模拟器窗口起不来 | 无 `DISPLAY` | 用宿主桌面会话启动：`DISPLAY=:0 XAUTHORITY=<xauth文件> ./emulator.sh ...` |

---

## 六、相关文件

| 文件 | 说明 |
|---|---|
| `tools/build-openvela.js` | 生成 `build/openvela-app/app.ux` + `manifest.json` |
| `tools/check-openvela-app.js` | 产物自检（占位符、残留 import、语法、七视图可渲染） |
| `openvela-app/skills/inspection.md` | 自定义 Skill（赛题必做项，含四类主动任务声明） |
| `docs/模拟器验证命令单.md` | 可直接复制粘贴的命令单（给另一台电脑用） |
