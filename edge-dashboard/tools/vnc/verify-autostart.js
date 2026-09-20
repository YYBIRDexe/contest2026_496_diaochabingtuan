"use strict"

/**
 * 核实 M1 上自启动项的真实状态（逐个文件打印内容）。
 *
 * 上一版汇总用 `grep -c` 在 set -e 下误判，把启用项报成「已禁用」，
 * 所以这里改为直接打印文件内容，不做推断。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/verify-autostart.js
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
      askpass = path.join(os.tmpdir(), "vgva-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgva.sh && bash /tmp/vgva.sh"
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

remote("用户级自启动项（逐个打印，不做推断）", [
  "echo '--- 文件列表 ---'",
  "ls -1 $HOME/.config/autostart/",
  "echo",
  "echo '--- 内容 ---'",
  "for f in $HOME/.config/autostart/velaguard.desktop $HOME/.config/autostart/velaguard-hide-cursor.desktop $HOME/.config/autostart/x3m-campus.desktop; do",
  "  if [ -f \"$f\" ]; then",
  "    echo \"===== $f =====\"",
  "    cat \"$f\"",
  "    echo",
  "  else",
  "    echo \"===== $f （不存在）=====\"",
  "  fi",
  "done"
], 60)

remote("系统级校园网自启（应仍存在但被用户级覆盖）", [
  "echo '--- /etc/xdg/autostart/x3m-campus.desktop ---'",
  "cat /etc/xdg/autostart/x3m-campus.desktop 2>/dev/null || echo '(不存在)'",
  "echo",
  "echo '--- 当前是否有校园网 Firefox ---'",
  "pgrep -af 'status.html' || echo '(无，说明自启已生效禁用)'"
], 60)

remote("运行中的组件", [
  "echo '--- 看板 ---'",
  "ps -eo args | grep [f]irefox | head -1 || echo '(未运行)'",
  "echo",
  "echo '--- 数据服务 ---'",
  "pgrep -af serve.js | head -1 || echo '(未运行)'",
  "echo",
  "echo '--- hide-cursor 残留 ---'",
  "pgrep -af hide-cursor || echo '(无常驻进程，正确)'",
  "echo",
  "echo '--- 图形会话 ---'",
  "ps -eo pid,etime,comm | grep -E 'Xorg|xfce4-session'"
], 60)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
