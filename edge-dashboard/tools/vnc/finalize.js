"use strict"

/**
 * 部署修复后的 start.sh，正式启动看板，并恢复开机自启。
 *
 * 修复内容：start.sh 原先无条件加 --allow-file-access-from-files，
 * 该参数在 http:// 模式下会让 Firefox 显示纯白页（实测确认）。
 * 现改为仅在 file:// 模式下添加。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/finalize.js
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || ""
const DIR = process.env.M1_DIR || "/home/" + USER + "/velaguard"
const PORT = process.env.M1_PORT || "8123"
const ROOT = path.join(__dirname, "..", "..")

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgfn-" + Date.now() + ".cmd")
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
  if (title) { console.log("\n### " + title) }
  const b64 = Buffer.from(lines.join("\n"), "utf8").toString("base64")
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgfn.sh && bash /tmp/vgfn.sh"
  const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST, cmd]), {
    encoding: "utf8",
    timeout: (timeoutSec || 120) * 1000,
    env: env(),
    maxBuffer: 16 * 1024 * 1024
  })
  const out = (String(r.stdout || "") + (r.stderr ? "\n[stderr] " + String(r.stderr) : "")).trim()
  if (title) { console.log(out || "(no output)") }
  return out
}

function scpUp(local, remotePath) {
  const r = spawnSync("scp", OPTS.concat([local, USER + "@" + HOST + ":" + remotePath]),
    { encoding: "utf8", timeout: 90000, env: env() })
  return { ok: r.status === 0, err: String(r.stderr || "") }
}

/* ------------------------------------------------------------------ */
console.log("=== 部署修复并正式启动 ===")

/* 1. 上传修复后的 start.sh */
const up = scpUp(path.join(ROOT, "linux", "start.sh"), DIR + "/linux/start.sh")
console.log("上传 start.sh: " + (up.ok ? "成功" : "失败 " + up.err.trim()))
if (!up.ok) {
  if (askpass) { fs.unlinkSync(askpass) }
  process.exit(1)
}

remote("1. 校验修复点", [
  "chmod +x " + DIR + "/linux/start.sh",
  "bash -n " + DIR + "/linux/start.sh && echo '语法正确' || echo '!! 语法错误'",
  "echo",
  "echo '--- 参数拼装片段 ---'",
  "grep -n -A4 'ARGS=()' " + DIR + "/linux/start.sh | head -12"
], 60)

/* 2. 关旧 Firefox 并用 start.sh 启动 */
remote("2. 启动看板", [
  "export DISPLAY=:0",
  "pkill -f firefox 2>/dev/null",
  "sleep 4",
  "cd " + DIR + "/linux",
  "setsid nohup ./start.sh --serve >/tmp/velaguard-start.log 2>&1 < /dev/null &",
  "sleep 32",
  "echo '--- Firefox 命令行（应无 --allow-file-access-from-files）---'",
  "ps -eo args | grep [f]irefox | head -1",
  "echo",
  "echo '--- 窗口标题（应为 VelaGuard…）---'",
  "for w in $(xdotool search --onlyvisible --class firefox 2>/dev/null | head -1); do",
  "  echo \"TITLE=$(xdotool getwindowname $w 2>/dev/null)\"",
  "done"
], 150)

/* 3. 抓屏验证 */
console.log("\n### 3. 抓屏验证")
const v = remote(null, [
  "export DISPLAY=:0",
  "rm -f /tmp/vgfn.xwd /tmp/vgfn.png",
  "xwd -root -silent > /tmp/vgfn.xwd 2>/dev/null",
  "ffmpeg -y -loglevel error -i /tmp/vgfn.xwd /tmp/vgfn.png 2>/dev/null",
  "echo SIZE=$(stat -c%s /tmp/vgfn.png 2>/dev/null || echo 0)",
  "python3 -c \"from PIL import Image; im=Image.open('/tmp/vgfn.png').convert('L'); px=list(im.getdata()); print('DARK='+str(round(sum(1 for v in px if v<60)/len(px)*100,1)))\" 2>/dev/null || echo DARK=?"
], 120)

const size = (v.match(/SIZE=(\d+)/) || [])[1] || "0"
const dark = (v.match(/DARK=([\d.]+)/) || [])[1] || "?"
const ok = Number(dark) > 50
console.log("  PNG=" + size + "B  暗像素=" + dark + "%  " + (ok ? "✓ 看板正常" : "✗ 仍是白页"))

const dir = path.join(ROOT, "preview", "m1")
fs.mkdirSync(dir, { recursive: true })
const dst = path.join(dir, "final-dashboard.png")
const g = spawnSync("scp", OPTS.concat([USER + "@" + HOST + ":/tmp/vgfn.png", dst]),
  { encoding: "utf8", timeout: 120000, env: env() })
if (g.status === 0 && fs.existsSync(dst)) {
  console.log("  ✓ final-dashboard.png")
}

/* 4. 恢复自启动 */
if (ok) {
  remote("4. 恢复开机自启", [
    "mkdir -p $HOME/.config/autostart",
    "cat > $HOME/.config/autostart/velaguard.desktop <<'EOF'",
    "[Desktop Entry]",
    "Type=Application",
    "Name=VelaGuard 巡检桌面",
    "Comment=多机器人分区巡检调度台（全屏看板）",
    "Exec=" + DIR + "/linux/start.sh --serve",
    "Path=" + DIR,
    "Terminal=false",
    "X-GNOME-Autostart-enabled=true",
    "EOF",
    "cat > $HOME/.config/autostart/velaguard-hide-cursor.desktop <<'EOF'",
    "[Desktop Entry]",
    "Type=Application",
    "Name=VelaGuard 隐藏鼠标光标",
    "Exec=" + DIR + "/linux/hide-cursor",
    "Terminal=false",
    "X-GNOME-Autostart-enabled=true",
    "EOF",
    "echo '自启动项:'",
    "ls -1 $HOME/.config/autostart/",
    "echo",
    "echo '--- 校园网自启动是否已禁用 ---'",
    "grep -l 'Hidden=true' $HOME/.config/autostart/x3m-campus.desktop 2>/dev/null && echo '已禁用 ✓' || echo '!! 未禁用'"
  ], 60)
}

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
