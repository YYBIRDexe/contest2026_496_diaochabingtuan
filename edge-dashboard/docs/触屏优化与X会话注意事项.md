# 触屏优化与 X 会话注意事项

记录两处触屏体验优化的做法，以及一个**导致 X 服务器崩溃的严重教训**。
换人维护前务必看第二节。

---

## 一、两个优化

### 1. 长按不选中文字、不出现蓝色高亮

纯前端问题，用 CSS 解决（在 `tools/build-preview.js` 生成的产物里）：

```css
* {
  -webkit-user-select: none;   /* 长按拖拽不再选中文字 */
  user-select: none;
  -webkit-touch-callout: none; /* 长按不弹系统菜单 */
  -webkit-tap-highlight-color: transparent; /* 点按不闪灰块 */
  -webkit-user-drag: none;
  overscroll-behavior: none;   /* 禁止下拉刷新/橡皮筋 */
  touch-action: manipulation;  /* 去掉双击缩放的 300ms 延迟 */
}
```

再加两个事件拦截作为双保险（防止个别浏览器不遵守 CSS）：

```js
document.addEventListener('contextmenu', e => e.preventDefault())
document.addEventListener('selectstart', e => e.preventDefault())
document.addEventListener('dragstart',   e => e.preventDefault())
```

界面里的文字都是展示性内容（标签、数值、状态），不需要选中复制，所以全局禁用是安全的。

### 2. 隐藏鼠标光标

触控屏不需要指针。目标设备**没有 unclutter，且无外网装不了**，
所以自带一个用 gcc 编译的极小 X11 程序：`linux/hide-cursor.c`。

#### ⚠️ 关键：X 的光标是「逐窗口」属性

**这是第一版失败的根因** —— 用户反馈「鼠标光标并没有消失」。

第一版只对**根窗口**调用 `XDefineCursor`，以为子窗口会继承。
实际上子窗口（Firefox 内容区、xfce4-panel、桌面）各自定义或覆盖光标，
**指针一移到浏览器上，光标就恢复可见**。

正确做法：**递归遍历整棵窗口树**，给每个窗口都设透明光标：

```c
static void apply_tree(Display *dpy, Window w)
{
    XDefineCursor(dpy, w, g_invisible);
    Window r, parent, *children = NULL;
    unsigned int n = 0;
    if (XQueryTree(dpy, w, &r, &parent, &children, &n)) {
        for (unsigned int i = 0; i < n; i++) {
            apply_tree(dpy, children[i]);
        }
        if (children) { XFree(children); }
    }
}
```

实测一次可覆盖 **88~110 个窗口**。

并且必须加 `--watch` 常驻：浏览器新建窗口、面板重绘都会产生
**没有透明光标的新窗口**，所以每秒重扫一遍补齐。

```bash
./hide-cursor --watch
```

#### 幂等处理

自启动目录里有一项 `hide-cursor --watch`（保证看板没起时光标也隐藏），
`start.sh` 也会拉起它 —— 两边同时动作会产生**两个常驻进程**。
所以 `start.sh` 里先检查是否已有实例：

```bash
if pgrep -f "hide-cursor --watch" >/dev/null 2>&1; then
  echo "透明光标已在运行（复用现有进程）"
elif [[ -x "${HIDE_CURSOR}" ]]; then
  "${HIDE_CURSOR}" --watch >/tmp/hide-cursor.log 2>&1 &
  ...
fi
```

#### 编译

```bash
gcc -O2 -o hide-cursor hide-cursor.c -lX11
```

> 设备只装了 `libX11.so` 与 `libXfixes.so.3`，**没有 `libXfixes.so`
> 这个开发用符号链接**（未装 -dev 包且无外网）。本程序只用 X11 核心协议，
> 所以不再依赖 libXfixes。

---

## 二之一、⚠️ 验证方法本身也会骗人（两次假通过）

这两次教训比 bug 本身更值得记，因为它们**看起来都通过了**。

### 假通过 1：把「截图里没看到光标」当成「光标已隐藏」

截图上没有光标图案，**只能说明当时指针恰好不在画面里**，
完全不能证明光标被隐藏（指针可能只是停在了画面外或某个角落）。
第一版就是这么"验证通过"的，实际用户一看光标还在。

### 假通过 2：用「指针附近亮像素数」判断

改成检查指针周围 40×40 区域的亮像素，结果恒为 0，看似完美。但有两处漏洞：

- **深色光标在深色背景上不产生亮像素**，检测不到
- **光标可能超出采样框**

### 正确做法：本设备上无法程序化验证，只能人工确认

试过四种方法，**全部不可靠**，记录下来避免以后重走弯路：

| 方法 | 为什么不可靠 |
| --- | --- |
| 看截图里有没有光标图案 | 只能说明指针当时不在画面里 |
| 数指针附近亮像素 | 深色光标在深色背景上不产生亮像素；光标可能超出采样框 |
| **差分法**（A 点/B 点抓图比对） | **实测证伪**：故意把光标设成正常箭头时，两次 `xwd` 抓图差分**仍为 0** |
| 读 `XFixesGetCursorImage` | `XFixesCursorImage` 结构靠手工推断，实测字段恒读到 0 |

**根因：这台设备上任何抓屏手段都取不到光标像素。**
`xwd` 取不到；改用 `ffmpeg -f x11grab -draw_mouse 1`（本应主动把光标画进画面）
做对照实验，**同样测不出差异** —— 连"故意设成可见光标"都检测不到。

结论：**「光标是否可见」在本设备上无法程序化验证，必须由人在物理屏上确认。**
不要再花时间造验证工具了，直接问用户。

---

## 二之二、光标隐藏需要两层，缺一不可

### 第一层：X 系统光标

`hide-cursor` 递归给整棵窗口树设 1×1 透明光标（详见上一节）。

### 第二层：浏览器自绘光标

X 层设置完成后用户仍反馈"光标还在"，说明**浏览器会在页面内自绘光标**
（Firefox 在触屏/kiosk 场景下会这么做）。`XDefineCursor` 管不到它，
必须在界面层再加一道：

```css
* { cursor: none !important; }
```

同时把 JS 里给可点击元素设的 `cursor='pointer'` 一并改掉 ——
否则那一处会重新露出光标：

```js
if (attrs['data-act']) {
  dom.style.cursor = 'none'   // 原先误设为 'pointer'
}
```

检查产物确认两处都干净：

```bash
grep -c 'cursor: none !important' preview/index.html   # 应为 1
grep -c 'cursor: *pointer'        preview/index.html   # 应为 0
```

---

## 二、⚠️ 严重教训：一个会让 Xorg 段错误的调用

### 现象

调用下面这行后，**X 服务器立即段错误崩溃，整个桌面会话被带死**：

```c
XFixesSetWindowShapeRegion(dpy, root, SHAPE_CURSOR, 0, 0, None);
```

日志证据：

```
Fatal server error:
[ 1367.462] (EE) Caught signal 11 (Segmentation fault). Server aborting
```

时间线（客户端调用与崩溃时间完全吻合）：

| 时刻 | 事件 |
| --- | --- |
| 12:40:5x | 执行 `hide-cursor` |
| 12:40:56 | Xorg 段错误，`Xorg.0.log` 轮转 |
| 12:40:57 | `xfce4-session`、`Thunar` 报 `Fatal IO error 11` |
| 12:41:00 | Xorg 已重启（新 PID，etime 00:31） |

### 原因

传 `None`(0) 作为 region 参数是**非法值**。本设备的 Xorg（1.20.4 + hobot fbdev
驱动）在该扩展的实现里没有校验这个参数，直接解引用空指针 → 段错误。

### 修复（已验证通过）

**隐藏光标根本不需要那个调用**，`XDefineCursor` 就够了（X11 核心协议，
任何服务端都安全）。所以：

- 默认**完全不走** XFixes 路径
- 保留 `--xfixes` 显式开关，但默认关闭
- 新增 `--check` 模式：**不连接 X**，只报告编译配置，
  用于确认手上的二进制到底是哪个版本

```bash
./hide-cursor --check
# hide-cursor 版本: 安全路径（纯 XDefineCursor）
# XFixes 代码: 已编译，但默认不启用（需 --xfixes）
```

**真机验证结果**（`tools/vnc/verify-cursor.js`）：

| 检查项 | 修复前 | 修复后 |
| --- | --- | --- |
| 执行退出码 | 1（误报失败） | **0** |
| 执行后 Xorg PID | **变化（崩溃重启）** | **10110 未变** |
| 执行后桌面会话 | **消失** | **存活** |
| Xorg 段错误 | 新增 1 条 | **无新增** |

截图确认：`preview/m1/cursor-verified.png` 上已看不到鼠标光标。

### 排查中犯的两个错（都要避免）

1. **没先确认二进制是不是最新版**就反复执行，导致 X 反复崩溃，
   一度误判为"系统不稳定/内存不足"。实际内存充足（可用 1291MB，
   swap 2G 未用，无 OOM），崩因就是这个程序。
   → 所以加了 `--check`，**改代码后必须先确认二进制版本**。

2. **验证脚本的判活逻辑写错**：用正则从 `ps` 输出提取 PID 失败，
   返回 `?`，于是 `? === ?` 被判为"X 存活"，**假通过**。
   → 现已改为显式 `KEY=VALUE` 标记提取，并在无法连 X 时**直接拒绝测试**
   而不是给出通过结论。

---

## 二之二、「老要输密码登录」的排查结论

用户反馈频繁被要求登录。实测排除与确认如下：

| 可能原因 | 实测结果 |
| --- | --- |
| 屏保/锁屏要求重新登录 | **排除**：`light-locker`、`xfce4-screensaver`、`xscreensaver`、`xautolock` **一个都没装** |
| 挂起后锁屏 | **排除**：`lock-screen-suspend-hibernate=false` |
| 会话启动失败 | **排除**：用户确认输入密码后能正常进入桌面 |
| **X 崩溃把会话踢掉** | **确认**：`Xorg.0.log.old` 里有 1 次段错误（就是 hide-cursor 造成的） |
| **自动登录未生效** | **确认**：配置里有 `autologin-user=sunrise` + `autologin-user-timeout=0`，但实际停在 greeter |

自动登录配置位置：

```
/etc/lightdm/lightdm.conf.d/22-hobot-autologin.conf
  autologin-user=sunrise
  autologin-user-timeout=0
  user-session=xfce

/etc/lightdm/lightdm.conf.d/11-hobot.conf
  user-session=ubuntu      ← ⚠️ 系统里没有 ubuntu.desktop
                              /usr/share/xsessions/ 只有 xfce.desktop 和 xubuntu.desktop
```

**待办**：自动登录为何未生效还没定位（需要 root 读
`/var/log/lightdm/lightdm.log`，当前不可读）。
可先尝试把用户加入免密登录组：

```bash
sudo gpasswd -a sunrise nopasswdlogin
```

另外注意：`sunrise` 当前只属于 `sudo` 组。

---

## 三、运行 hide-cursor 的正确时机

**必须在图形会话内运行**，因为 Xorg 的授权文件是
`-auth /var/run/lightdm/root/:0`（属 root），SSH 会话拿不到；
只有用户**登录桌面后** `~/.Xauthority` 才有效。

已在 `linux/start.sh` 里集成：启动看板时顺带隐藏光标，并打印结果。

```bash
~/velaguard/linux/start.sh --serve
```

要开机自动隐藏，可在 `~/.config/autostart/` 放一个桌面项：

```ini
[Desktop Entry]
Type=Application
Name=VelaGuard 隐藏鼠标光标
Exec=/home/sunrise/velaguard/linux/hide-cursor
Terminal=false
X-GNOME-Autostart-enabled=true
```

`tools/vnc/install-autostart.js` 可以免 root 写入这个项
（M1 的 sudo 需要密码，而写 `~/.config/autostart/` 本来就不需要 root）。

---

## 三之二、⚠️ `--allow-file-access-from-files` 会让 Firefox 显示纯白页

这是 kiosk 启动排查中最费时的一个坑，单独记下来。

### 现象

同一条命令，只差一个参数，结果完全不同：

| 命令 | 窗口标题 | 结果 |
| --- | --- | --- |
| `firefox --kiosk http://127.0.0.1:8123/#kiosk` | `VelaGuard 巡检桌面 · 浏览器预览 — Mozilla Firefox` | **✓ 看板正常**（暗像素 96%） |
| `firefox --allow-file-access-from-files --kiosk http://127.0.0.1:8123/#kiosk` | `Mozilla Firefox` | **✗ 纯白页**（暗像素 0%，PNG 仅 10KB） |

### 判据

两个指标都能一眼分辨，建议以后都用它们验证：

- **窗口标题**：加载成功会变成页面标题；白页时停在 `Mozilla Firefox`
- **PNG 体积 / 暗像素占比**：看板是深色界面 → 100KB+、暗像素 90%+；
  白页 → 约 10KB、暗像素 0%

`tools/vnc/wait-dashboard.js` 已内置这两个判据。

> 注意别用「非白像素」当判据 —— 白像素的 R+G+B 也大于阈值，
> 会把纯白页判成"已渲染"（这个错误我犯过，导致假通过）。

### 原因与修复

该参数是给 `file://` 模式放宽同源限制用的，在 `http://` 模式下反而会
破坏页面加载。`start.sh` 原先无条件添加，现已改为**仅在 `file://` 时**添加：

```bash
ARGS=()
case "${URL}" in
  file://*) ARGS+=(--allow-file-access-from-files) ;;
esac
```

### 另一个坑：Firefox 的会话恢复对话框

用 `pkill` 强杀 Firefox 后，下次启动会弹
"Sorry. We're having trouble getting your pages back."，
停在对话框上不显示看板。修复方式是在 profile 目录写 `user.js`：

```js
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.sessionstore.max_resumed_crashes", 0);
user_pref("browser.sessionstore.enabled", false);
user_pref("browser.startup.page", 0);
```

`tools/vnc/fix-firefox-session.js` 会自动完成。

### 还要注意：已运行的 Firefox 会吞掉 kiosk

若已有 Firefox 实例在跑，`firefox --kiosk <URL>` **只会在现有窗口开个新标签**，
不会进入 kiosk 全屏。所以启动前必须先 `pkill -f firefox`。

---

## 三之三、关闭「校园网状态页」开机自启（免 root）

该页由系统级自启动项拉起：

```
/etc/xdg/autostart/x3m-campus.desktop
  Exec=/usr/bin/python3 /opt/x3m-campus/campus.py
```

按 XDG 标准，**用户级同名文件优先级更高**，所以不必改 root 文件、
也不必输入 M1 的 sudo 密码：

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/x3m-campus.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=校园网状态
Exec=/usr/bin/python3 /opt/x3m-campus/campus.py
Hidden=true
X-GNOME-Autostart-enabled=false
EOF
```

注意区分三个东西，不要误伤：

| 组件 | 作用 | 建议 |
| --- | --- | --- |
| `/etc/xdg/autostart/x3m-campus.desktop` | 登录后弹出 Firefox 状态页 | **已禁用**（占 385MB，与看板抢内存） |
| `x3m-campus.service` | 后台采集网络状态（9.8MB） | 保留，不影响看板 |
| `x3m-net-autoconnect.service` | 保证 eth0 拿到 IP | 保留，禁用可能断网 |

---

## 四、相关工具

| 工具 | 用途 |
| --- | --- |
| `tools/vnc/verify-cursor.js` | **安全验证**隐藏光标：先 `--check` 确认版本，执行后复查 Xorg PID 与桌面会话是否存活 |
| `tools/vnc/deploy-cursor.js` | 上传源码 + 编译 + 应用 |
| `tools/vnc/install-autostart.js` | 免 root 写入/卸载自启动项 |
| `tools/vnc/dbg-crash-cause.js` | 确认 X 是否段错误崩溃及时间点 |
| `tools/vnc/state.js` | 会话/授权状态速查 |
