# 部署到 M1（Linux）+ 外接触控显示器

目标形态：**M1 实训箱上的 Linux（Horizon X3M / Ubuntu）驱动外接触控显示器，
跑一个全屏的 VelaGuard 巡检桌面看板。**

界面就是一个**单文件 HTML**（`preview/index.html`，已内联全部数据与图标），
所以部署只有一件事：把它拷到 M1，用浏览器全屏打开。

不需要网络、不需要本地服务器、不需要编译工具链。

---

## 一、为什么是「浏览器全屏」而不是别的

| 方案 | 结论 |
| --- | --- |
| **浏览器 kiosk 全屏（采用）** | 零构建、离线可用、触控原生支持、改界面只需换一个文件 |
| LVGL / Qt 原生 | 要交叉编译工具链，改一行要重编译重部署，成本高 |
| Electron | 要装 Node 运行时（几百 MB），设备离线装不动 |
| 快应用 .rpk | **不可用**——需要 openvela 运行时，M1 没有 |

设备本身有 Linux 和桌面环境，浏览器是现成的显示层，直接用最省事。

---

## 二、三步部署

### 1. 在开发机生成界面文件

```bash
node tools/build-preview.js
```

产物：`preview/index.html`（约 100 KB，单文件自包含）。

### 2. 把整个工程目录拷到 M1

```bash
# 在开发机上（把 <m1-ip> 换成 M1 的地址）
scp -r VelaGuard-Desktop <user>@<m1-ip>:~/

# 或者用 U 盘拷
```

### 3. 在 M1 上安装并启动

```bash
cd ~/VelaGuard-Desktop/linux
chmod +x install.sh start.sh

./start.sh --windowed   # 先窗口模式试跑，确认界面正常
./start.sh --serve      # ★ 正式运行：本机起数据服务 + 全屏看板（可接真实数据）
./start.sh              # 只看界面：file:// 打开，零依赖，但只有演示数据
./start.sh --page voice # 直接进入语音助手页

sudo ./install.sh       # 确认没问题后，装成开机自启
```

> **`--serve` 与不带参数的区别**：
> 浏览器禁止 `file://` 页面发起 `fetch`，所以**要接 M1 的真实巡检数据就必须用
> `--serve`**（或 `--url` 指向别处已起好的服务）。只用演示数据的话，
> 不带参数即可，连 node 都不需要。

`install.sh` 会把文件放到 `~/velaguard`，并写入
`~/.config/autostart/velaguard.desktop`，之后登录桌面就自动全屏启动。

> 若要用真实数据，请把 `install.sh` 生成的 desktop 文件里的
> `Exec=` 改成带 `--serve` 的形式：
> `Exec=/home/<用户名>/velaguard/linux/start.sh --serve`

---

## 三、接 M1 的真实巡检数据

界面每 2 秒轮询一次 `GET /data/state.json`。**M1 侧只要按格式写这个 JSON**，
界面就会自动跟着变，不需要改界面代码。

字段规范见 [`../data/README.md`](../data/README.md)（含完整示例与五个状态值）。

### M1 侧最小实现（Python）

```python
import json, time, os

STATE = "/home/pi/velaguard/data/state.json"

def write_state(zones, cars):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"zones": zones, "cars": cars}, f, ensure_ascii=False)
    os.replace(tmp, STATE)      # 原子替换，避免界面读到半截 JSON

while True:
    write_state(collect_zones(), collect_cars())   # 换成你的采集逻辑
    time.sleep(1)
```

### 接收界面下发的指令

界面上的派单 / 取消会 `POST /api/command`。
`tools/serve.js` 会把指令追加写到 `data/commands.log`，
M1 侧可以轮询这个文件作为最简实现：

```bash
tail -f ~/velaguard/data/commands.log
# {"action":"dispatch","zoneId":"Z4","at":1758192000000}
```

也可以自己实现一个等价的 HTTP 接口，然后把
`src/common/source.js` 里的 `commandUrl` 指过去。

### 不用真机先验证链路

```bash
# 开发机上
node tools/serve.js 8123
node tools/simulate-m1.js
```

浏览器打开 <http://127.0.0.1:8123/>，点状态栏标签切到「M1 数据」，
就能看到任务自己走起来。

### 在界面上确认链路状态

桌面状态栏右侧有**数据源标签**：

- 绿色「M1 数据」= 正在读真实数据
- 红色「M1 数据 · 断连」= 接口读不到（文件被删或服务停了）
- 灰色「演示数据」= 当前用的是内置预设表

点它可以在三种数据源之间轮换，用来快速判断问题出在链路还是界面。

---

## 四、start.sh 做了什么

- **自动探测浏览器**：按顺序找 `chromium` / `chromium-browser` /
  `google-chrome` / `firefox` / `epiphany`，找到哪个用哪个
- **kiosk 全屏**：Chromium 系用 `--kiosk`，Firefox 用 `--kiosk`
- **禁止息屏**：`xset s off`、`xset -dpms`，避免看板自己黑屏
- **隐藏鼠标指针**：检测到 `unclutter` 就启用（触控屏上留个箭头很丑）
- **直接 file:// 打开**：不依赖网络与本地服务

---

## 五、浏览器从哪来（离线场景）

这是**唯一可能卡住的地方**：M1 上如果没有浏览器，就得装一个。
设备断网时不能 `apt install`，三种办法：

### 办法 A：确认系统是否自带

Ubuntu 桌面版通常自带 Firefox；服务器版没有图形界面也没有浏览器。
先查一下：

```bash
which chromium chromium-browser google-chrome firefox epiphany
```

有输出就直接能用。

### 办法 B：离线装 .deb

1. 在有网的机器上，按 M1 的架构（Horizon X3M 是 **aarch64/arm64**）下载：

   ```bash
   # 在有网的 arm64 机器或容器里
   apt-get download chromium-browser
   ```

2. 把 `.deb` 和它的依赖一起拷到 M1：

   ```bash
   sudo dpkg -i *.deb
   sudo apt-get -f install     # 若缺依赖且有本地源
   ```

### 办法 C：自己编译 / 用轻量浏览器

设备资源紧张时可考虑 `epiphany-browser`（GNOME Web，依赖少）或
`falkon`、`midori` 这类轻量 WebKit 浏览器。

> 如果最终发现这颗芯片跑桌面浏览器太重，可以考虑退一步：
> 把界面渲染成静态图片序列由轻量 GUI 展示——但那样就失去交互了，
> 属于下策，先试浏览器方案。

---

## 六、接屏幕与触摸

### 分辨率：1920×1080（已按屏幕实际比例设计）

**界面设计基准为 1920×1080**，与 M1 实测帧缓冲一致，1:1 铺满整屏、四边零黑边。

> ⚠️ **说明书标注的 1280×800 不可信。** 实测依据：
> - 内核：`FBDEV(0): Virtual size is 1920x1080 (pitch 1920)`，只有一个内建模式
> - X：`minimum 1920x1080 / maximum 1920x1080`，fbdev 是哑驱动，无法增删模式
> - 显示通路：`hobot_hdmi` + `hobot_hdmi_lt8618`（Lontai LT8618 HDMI 发送芯片）
> - 交叉验证：界面以 1920×1080 渲染时文字锐利；若面板真是 1280×800 会被缩到 67% 而明显发虚
>
> 改输出分辨率需动内核引导参数（`video=hobot:x3sdb-hdmi`）或显示 DTS，
> 有把屏幕搞黑的风险，因此改为**按屏幕实际比例设计界面**。

验证当前分辨率：

```bash
DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority xrandr | grep connected
```

真机效果见 `preview/m1/m1-kiosk.png`；填充是否满可用确定性判据复核：

```bash
powershell -File tools/vnc/check-fill.ps1 -Src preview/m1/m1-kiosk.png
# VERDICT: FILLED -- no letterboxing
```

### 显示与触摸

- **显示**：RDK X3 / Horizon X3M 支持 HDMI 输出，接外接显示器即可
  （[RDK X3 显示文档](https://developer.d-robotics.cc/rdk_doc/Advanced_development/hardware_development/rdk_x3_module/display/)）
- **触摸**：USB 触控屏在 Linux 下通常免驱（识别为 HID 触摸设备），
  浏览器会直接收到触摸事件，无需额外配置
- 界面用**纯 flex 自适应**，没有写死坐标；换分辨率只会等比缩放，不会错位

验证触摸是否被识别：

```bash
ls /dev/input/            # 应能看到 event* 设备
DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority xinput list   # X 会话下看输入设备
```

---

## 七、开机全屏（无桌面登录）

如果设备配置成**不自动登录桌面**，`.config/autostart` 不会触发。
两种处理：

### 方式一：打开自动登录（简单）

系统设置 → 用户 → 自动登录；或在 `/etc/gdm3/custom.conf` 里
设置 `AutomaticLoginEnable=true` 与 `AutomaticLogin=<用户名>`。

### 方式二：systemd 服务 + 自动登录到 X

写入 `/etc/systemd/system/velaguard.service`：

```ini
[Unit]
Description=VelaGuard 巡检桌面看板
After=graphical.target

[Service]
Type=simple
User=<用户名>
Environment=DISPLAY=:0
ExecStart=/home/<用户名>/velaguard/linux/start.sh
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now velaguard
```

---

## 八、常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `当前没有图形会话` | 在纯 SSH 下运行了。需在桌面会话里跑，或 `export DISPLAY=:0` |
| `没有找到可用的浏览器` | 见第四节，装一个浏览器 |
| 界面显示但点不动 | 触摸未被识别，`xinput list` 确认；或换成鼠标先验证界面本身 |
| 看板自己黑屏 | `xset s off; xset -dpms; xset s noblank` |
| 有鼠标箭头 | `sudo apt install unclutter`，start.sh 会自动使用 |
| 布局挤成一列 | 浏览器太旧不支持 flex gap/wrap；换较新的 Chromium |
| 开机没自动起 | 见第六节，多半是没自动登录桌面 |
| 改了界面没生效 | 重新 `node tools/build-preview.js` 并覆盖 M1 上的 `preview/index.html` |
| 全屏后上下有黑边 | 屏幕比例与 1280×800 不同，改 `designWidth` 重新生成 |

---

## 九、改了界面怎么更新

在开发机上改 `src/pages/*/index.ux` 或 `src/common/store.js`，然后：

```bash
node tools/build-preview.js
scp preview/index.html <user>@<m1-ip>:~/velaguard/preview/
```

看板刷新一下（或重启浏览器）即可，**不需要重新安装**。
