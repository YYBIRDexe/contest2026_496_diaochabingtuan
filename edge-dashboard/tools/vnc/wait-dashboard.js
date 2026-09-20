"use strict"

/**
 * 等待并验证 M1 看板是否真正渲染出来（抓屏 + JPEG 质量判据）。
 *
 * 判据：纯白页面的 PNG 极小（几 KB）；看板是深色复杂界面，PNG 会明显更大。
 * 所以用截图的字节数 + 颜色采样来判断是否渲染成功。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/wait-dashboard.js [等待秒数]
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || ""
const WAIT = Number(process.argv[2] || 45)
const ROOT = path.join(__dirname, "..", "..")

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgwd-" + Date.now() + ".cmd")
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

function remote(lines, timeoutSec) {
  const b64 = Buffer.from(lines.join("\n"), "utf8").toString("base64")
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgwd.sh && bash /tmp/vgwd.sh"
  const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST, cmd]), {
    encoding: "utf8",
    timeout: (timeoutSec || 90) * 1000,
    env: env(),
    maxBuffer: 16 * 1024 * 1024
  })
  return (String(r.stdout || "") + (r.stderr ? "\n[stderr] " + String(r.stderr) : "")).trim()
}

function grabAndMeasure(name) {
  const info = remote([
    "export DISPLAY=:0",
    "rm -f /tmp/vgwd.xwd /tmp/vgwd.png",
    "xwd -root -silent > /tmp/vgwd.xwd 2>/dev/null",
    "ffmpeg -y -loglevel error -i /tmp/vgwd.xwd /tmp/vgwd.png 2>/dev/null",
    "echo SIZE=$(stat -c%s /tmp/vgwd.png 2>/dev/null || echo 0)",
    "echo BRIGHT=$(python3 -c \"from PIL import Image; im=Image.open('/tmp/vgwd.png').convert('L'); px=list(im.getdata()); print(sum(1 for v in px if v>200))\" 2>/dev/null || echo 0)",
    "echo DARK=$(python3 -c \"from PIL import Image; im=Image.open('/tmp/vgwd.png').convert('L'); px=list(im.getdata()); print(sum(1 for v in px if v<60))\" 2>/dev/null || echo 0)"
  ], 120)
  const size = Number((info.match(/SIZE=(\d+)/) || [])[1] || 0)
  const bright = Number((info.match(/BRIGHT=(\d+)/) || [])[1] || 0)
  const dark = Number((info.match(/DARK=(\d+)/) || [])[1] || 0)

  const dir = path.join(ROOT, "preview", "m1")
  fs.mkdirSync(dir, { recursive: true })
  const dst = path.join(dir, name)
  const r = spawnSync("scp", OPTS.concat([USER + "@" + HOST + ":/tmp/vgwd.png", dst]),
    { encoding: "utf8", timeout: 120000, env: env() })
  const ok = r.status === 0 && fs.existsSync(dst)
  return { size: size, bright: bright, dark: dark, ok: ok, path: dst }
}

/* ------------------------------------------------------------------ */
console.log("=== 验证看板渲染（每 15 秒抓一次，最多 " + WAIT + " 秒）===")
console.log("判据：深色看板 → 大量暗像素且 PNG 明显大于白页；白页 → 绝大多数为亮像素")

let success = false
let last = null
for (let waited = 0; waited < WAIT; waited += 15) {
  spawnSync("node", ["-e", "setTimeout(function(){},15000)"], { timeout: 20000 })
  const t = waited + 15

  const state = remote([
    "echo FF=$(pgrep -c firefox)",
    "echo DESKTOP=$(pgrep -c xfce4-session)",
    "echo XORG=$(pgrep -x Xorg | head -1)"
  ], 60)
  const ff = (state.match(/FF=(\d+)/) || [])[1] || "0"
  const desk = (state.match(/DESKTOP=(\d+)/) || [])[1] || "0"

  const m = grabAndMeasure("dashboard-final.png")
  last = m

  /*
   * 判据说明（上一版用过「非白像素」，把纯白页也算成 200 万，是错的）：
   *   看板是深色界面（#0b1220 背景）→ 暗像素占绝大多数、PNG 100KB+
   *   白页（Firefox 错误页/空白页）→ 亮像素占绝大多数、PNG 约 10KB
   * 所以同时看「暗像素占比」和「PNG 尺寸」，两者都满足才算渲染成功。
   */
  const total = 1920 * 1080
  const darkRatio = m.dark / total
  const rendered = darkRatio > 0.5 && m.size > 50000
  console.log("  [" + t + "s] firefox=" + ff + " 桌面=" + desk +
    "  png=" + m.size + "B  暗像素=" + (darkRatio * 100).toFixed(1) + "%" +
    (rendered ? "  ✓ 已渲染（深色看板）" : "  （疑似白页/错误页）"))

  if (rendered) {
    success = true
    break
  }
  if (ff === "0" || desk === "0") {
    console.log("  !! Firefox 或桌面已退出，停止等待")
    break
  }
}

console.log("\n" + "─".repeat(55))
if (success) {
  console.log("✓ 看板已正常渲染")
  console.log("  截图: " + (last ? last.path : ""))
} else {
  console.log("✗ 看板未渲染出来")
  const diag = remote([
    "echo '--- start.sh 日志 ---'",
    "tail -15 /tmp/velaguard-start.log 2>/dev/null || echo '(无)'",
    "echo",
    "echo '--- Firefox 控制台错误（若有）---'",
    "tail -8 /tmp/velaguard-start.log 2>/dev/null | grep -i error || echo '(无 error)'"
  ], 60)
  console.log(diag)
}

if (askpass) { fs.unlinkSync(askpass) }
