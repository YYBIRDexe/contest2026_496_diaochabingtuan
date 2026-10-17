"use strict"

/**
 * 检查 M1 当前分辨率与图形会话状态（只读）。
 *
 * 实现要点：
 *   - 远端脚本行的 JS 字符串一律用双引号，内部只用单引号 → 避开引号转义坑
 *   - 脚本里不写 $ 变量，避免外层 shell 抢先展开
 *     （X 客户端默认读 ~/.Xauthority，无需显式传 XAUTHORITY）
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/resolution.js
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || ""

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgres-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgres.sh && bash /tmp/vgres.sh"
  const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST, cmd]), {
    encoding: "utf8",
    timeout: (timeoutSec || 60) * 1000,
    env: env(),
    maxBuffer: 16 * 1024 * 1024
  })
  const out = (String(r.stdout || "") + (r.stderr ? "\n[stderr] " + String(r.stderr) : "")).trim()
  console.log(out || "(no output)")
  return out
}

remote("1. 图形会话进程", [
  "date '+现在: %H:%M:%S'",
  "echo",
  "ps -eo pid,etime,comm | grep -E 'Xorg|xfce4-session|lightdm-gtk'",
  "echo",
  "echo '（xfce4-session 在 = 已登录桌面；lightdm-gtk 在 = 停在登录界面）'"
], 60)

remote("2. 当前分辨率（DISPLAY=:0，默认读 ~/.Xauthority）", [
  "export DISPLAY=:0",
  "echo '--- xdpyinfo 屏幕尺寸 ---'",
  "xdpyinfo 2>&1 | grep -m1 dimensions || echo '(无法连接 X)'",
  "echo",
  "echo '--- xrandr 模式 ---'",
  "xrandr 2>&1 | head -6"
], 60)

remote("3. 帧缓冲尺寸（内核侧真实值）", [
  "echo '--- /sys/class/graphics ---'",
  "ls /sys/class/graphics/ 2>/dev/null",
  "echo",
  "echo '--- fb0 虚拟尺寸 ---'",
  "cat /sys/class/graphics/fb0/virtual_size 2>/dev/null || echo '(不可读)'",
  "echo '--- fb0 名称 ---'",
  "cat /sys/class/graphics/fb0/name 2>/dev/null || echo '(不可读)'",
  "echo",
  "echo '--- Xorg 日志里的分辨率 ---'",
  "grep -m3 -iE 'Virtual size|Built-in mode|current' /var/log/Xorg.0.log 2>/dev/null || echo '(无)'"
], 60)

remote("4. 运行中的组件", [
  "echo '--- 数据服务 ---'",
  "pgrep -af serve.js || echo '(未运行)'",
  "echo '--- Firefox ---'",
  "pgrep -af firefox || echo '(未运行)'",
  "echo '--- hide-cursor ---'",
  "pgrep -af hide-cursor || echo '(无进程，一次性模式属正常)'"
], 60)

if (askpass) { fs.unlinkSync(askpass) }
