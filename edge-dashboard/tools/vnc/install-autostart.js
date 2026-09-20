"use strict"

/**
 * 在 M1 上安装「开机自启」：写入两个 XDG autostart 项。
 *
 * 为什么不用 install.sh 里的 sudo：
 *   install.sh 的活（复制到 ~/velaguard、写 ~/.config/autostart）全在用户目录，
 *   本来就不需要 root；而 M1 的 sudo 需要密码，远程无法非交互输入。
 *   所以这里直接执行等效的、无特权的安装步骤。
 *
 * 装两个自启动项：
 *   1. velaguard.desktop              → 登录后全屏打开触控看板
 *   2. velaguard-hide-cursor.desktop  → 登录后隐藏鼠标光标
 *
 * 用法：
 *   $env:M1_HOST/M1_USER/M1_PASS
 *   node tools/vnc/install-autostart.js          # 安装
 *   node tools/vnc/install-autostart.js --uninstall
 *   node tools/vnc/install-autostart.js --status
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || ""
const DIR = process.env.M1_DIR || "/home/" + USER + "/velaguard"
const MODE = process.argv[2] || ""

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgas-" + Date.now() + ".cmd")
      fs.writeFileSync(askpass, "@echo off\r\necho %VG_SSH_PASS%\r\n", "utf8")
    }
    e.VG_SSH_PASS = PASS
    e.SSH_ASKPASS = askpass
    e.SSH_ASKPASS_REQUIRE = "force"
    e.DISPLAY = "localhost:0"
  }
  return e
}

const OPTS = [
  "-o", "StrictHostKeyChecking=no",
  "-o", "UserKnownHostsFile=/dev/null",
  "-o", "ConnectTimeout=10",
  "-o", "LogLevel=ERROR",
  "-o", "PreferredAuthentications=password,keyboard-interactive",
  "-o", "PubkeyAuthentication=no",
  "-o", "NumberOfPasswordPrompts=1"
]

function remote(title, lines, timeoutSec) {
  console.log("\n### " + title)
  const b64 = Buffer.from(lines.join("\n"), "utf8").toString("base64")
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgas.sh && bash /tmp/vgas.sh"
  const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST, cmd]), {
    encoding: "utf8",
    timeout: (timeoutSec || 90) * 1000,
    env: env(),
    maxBuffer: 16 * 1024 * 1024
  })
  const out = (String(r.stdout || "") + (r.stderr ? "\n[stderr] " + String(r.stderr) : "")).trim()
  console.log(out || "(no output)")
  return out
}

const DESKTOP_DIR = "$HOME/.config/autostart"
const APP_DESKTOP = DESKTOP_DIR + "/velaguard.desktop"
const CURSOR_DESKTOP = DESKTOP_DIR + "/velaguard-hide-cursor.desktop"

/* ------------------------------------------------------------------ */
if (MODE === "--status") {
  remote("自启动项现状", [
    "echo '--- autostart 目录 ---'",
    "ls -la $HOME/.config/autostart/",
    "echo",
    "echo '--- 看板项内容 ---'",
    "cat " + APP_DESKTOP + " 2>/dev/null || echo '(未安装)'",
    "echo",
    "echo '--- 光标项内容 ---'",
    "cat " + CURSOR_DESKTOP + " 2>/dev/null || echo '(未安装)'",
    "echo",
    "echo '--- 可执行文件是否就位 ---'",
    "ls -l " + DIR + "/linux/start.sh " + DIR + "/linux/hide-cursor 2>/dev/null",
    "echo",
    "echo '--- 界面文件 ---'",
    "ls -l " + DIR + "/preview/index.html 2>/dev/null"
  ], 60)
  if (askpass) { fs.unlinkSync(askpass) }
  process.exit(0)
}

if (MODE === "--uninstall") {
  remote("卸载自启动项", [
    "rm -f " + APP_DESKTOP + " && echo '已移除看板自启动项'",
    "rm -f " + CURSOR_DESKTOP + " && echo '已移除光标自启动项'",
    "echo",
    "ls -la $HOME/.config/autostart/"
  ], 60)
  if (askpass) { fs.unlinkSync(askpass) }
  process.exit(0)
}

/* ---------------- 安装 ---------------- */
console.log("=== 安装开机自启（无需 root）===")

remote("1. 补齐可执行权限", [
  "chmod +x " + DIR + "/linux/start.sh",
  "chmod +x " + DIR + "/linux/hide-cursor 2>/dev/null || true",
  "chmod +x " + DIR + "/linux/install.sh",
  "ls -l " + DIR + "/linux/start.sh " + DIR + "/linux/hide-cursor 2>/dev/null"
], 60)

remote("2. 写入自启动项", [
  "mkdir -p " + DESKTOP_DIR,
  "echo",
  "cat > " + APP_DESKTOP + " <<'EOF'",
  "[Desktop Entry]",
  "Type=Application",
  "Name=VelaGuard 巡检桌面",
  "Comment=多机器人分区巡检调度台（全屏看板）",
  "Exec=" + DIR + "/linux/start.sh --serve",
  "Path=" + DIR,
  "Terminal=false",
  "X-GNOME-Autostart-enabled=true",
  "EOF",
  "echo '已写入 " + APP_DESKTOP + "'",
  "echo",
  "cat > " + CURSOR_DESKTOP + " <<'EOF'",
  "[Desktop Entry]",
  "Type=Application",
  "Name=VelaGuard 隐藏鼠标光标",
  "Comment=触控屏无需鼠标指针",
  "Exec=" + DIR + "/linux/hide-cursor",
  "Path=" + DIR,
  "Terminal=false",
  "X-GNOME-Autostart-enabled=true",
  "EOF",
  "echo '已写入 " + CURSOR_DESKTOP + "'"
], 60)

remote("3. 校验结果", [
  "echo '--- 自启动目录 ---'",
  "ls -la " + DESKTOP_DIR,
  "echo",
  "echo '--- 看板项 ---'",
  "cat " + APP_DESKTOP,
  "echo",
  "echo '--- 光标项 ---'",
  "cat " + CURSOR_DESKTOP,
  "echo",
  "echo '--- 桌面环境是否认识这些项 ---'",
  "command -v xfce4-session >/dev/null && echo 'XFCE 会读取 ~/.config/autostart/（XDG 标准）' || echo '非 XFCE，仍按 XDG 标准生效'"
], 60)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。下次登录桌面会自动全屏进入触控页面并隐藏光标。")
