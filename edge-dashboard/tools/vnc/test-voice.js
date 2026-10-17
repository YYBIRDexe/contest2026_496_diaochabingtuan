"use strict"

/**
 * 在 M1 真机上验证「语音助手」页面。
 *
 * 为什么不靠点击模拟：
 *   xdotool 的合成事件在这台设备上不被 Firefox 接收（已实测：指针能移动、
 *   窗口在前台且订阅了输入事件，但页面无任何反应，连 hover 都没有）。
 *   所以改用界面自带的 URL hash 路由：start.sh --page voice 会生成
 *   '#kiosk,voice'，直接进入语音助手页。
 *
 * 验证内容：
 *   1. 语音助手页能正常渲染（截图 + 暗像素判据）
 *   2. 页面里的会话气泡、常用指令、底部输入区是否齐全（内容判据）
 *   3. 数据源模式（velaclaw 不可用时应为本地指令模式）
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/test-voice.js
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || ""
const DIR = process.env.M1_DIR || "/home/" + USER + "/velaguard"
const ROOT = path.join(__dirname, "..", "..")

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgvt-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgvt.sh && bash /tmp/vgvt.sh"
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

function grab(name) {
  remote(null, [
    "export DISPLAY=:0",
    "rm -f /tmp/vgvt.xwd /tmp/vgvt.png",
    "xwd -root -silent > /tmp/vgvt.xwd 2>/dev/null",
    "ffmpeg -y -loglevel error -i /tmp/vgvt.xwd /tmp/vgvt.png 2>/dev/null",
    "echo SIZE=$(stat -c%s /tmp/vgvt.png 2>/dev/null || echo 0)",
    "python3 -c \"from PIL import Image; im=Image.open('/tmp/vgvt.png').convert('L'); px=list(im.getdata()); print('DARK='+str(round(sum(1 for v in px if v<60)/len(px)*100,1)))\" 2>/dev/null || echo DARK=?"
  ], 120)
  const dir = path.join(ROOT, "preview", "m1")
  fs.mkdirSync(dir, { recursive: true })
  const dst = path.join(dir, name)
  const r = spawnSync("scp", OPTS.concat([USER + "@" + HOST + ":/tmp/vgvt.png", dst]),
    { encoding: "utf8", timeout: 120000, env: env() })
  return r.status === 0 && fs.existsSync(dst) ? dst : null
}

/* ------------------------------------------------------------------ */
console.log("=== M1 语音助手真机验证（URL 路由方式）===")

/* 1. 部署最新界面（含 hash 路由修复） */
const up = scpUp(path.join(ROOT, "preview", "index.html"), DIR + "/preview/index.html")
console.log("\n上传界面: " + (up.ok ? "成功" : "失败 " + up.err.trim()))

/* 2. 用 --page voice 启动，直达语音助手页 */
remote("1. 以 --page voice 启动看板", [
  "export DISPLAY=:0",
  "pkill -f firefox 2>/dev/null",
  "sleep 4",
  "cd " + DIR + "/linux",
  "setsid nohup ./start.sh --serve --page voice >/tmp/voice-test.log 2>&1 < /dev/null &",
  "sleep 32",
  "echo '--- 启动日志 ---'",
  "grep -viE 'Crash Annotation' /tmp/voice-test.log | tail -8",
  "echo",
  "echo '--- Firefox 的 URL（应含 #kiosk,voice）---'",
  "ps -eo args | grep [f]irefox | head -1",
  "echo",
  "echo '--- 窗口标题 ---'",
  "for w in $(xdotool search --onlyvisible --class firefox 2>/dev/null | head -1); do",
  "  echo \"TITLE=$(xdotool getwindowname $w 2>/dev/null)\"",
  "done"
], 150)

/* 3. 抓屏验证 */
console.log("\n### 2. 抓屏（语音助手页）")
const shot = grab("voice-page-live.png")
console.log("  " + (shot ? "✓ " + shot : "✗ 失败"))

remote("3. 渲染判据与页面内容", [
  "export DISPLAY=:0",
  "echo '--- 渲染判据 ---'",
  "rm -f /tmp/vc.png /tmp/vc.xwd",
  "xwd -root -silent > /tmp/vc.xwd 2>/dev/null",
  "ffmpeg -y -loglevel error -i /tmp/vc.xwd /tmp/vc.png 2>/dev/null",
  "python3 - <<'PY'",
  "from PIL import Image",
  "im = Image.open('/tmp/vc.png').convert('L')",
  "px = list(im.getdata())",
  "dark = sum(1 for v in px if v < 60) / len(px) * 100",
  "print('暗像素占比', round(dark, 1), '%')",
  "print('判据', 'PASS（深色看板已渲染）' if dark > 50 else 'FAIL（疑似白页）')",
  "PY"
], 120)

/* 4. 检查界面产物里的语音助手关键内容 */
remote("4. 界面产物里的语音助手关键内容", [
  "cd " + DIR,
  "echo '--- 语音助手页相关字符串 ---'",
  "for kw in '语音助手' '按住说话' '本地指令模式' '常用指令' 'velaclaw' '开始本轮巡检'; do",
  "  n=$(grep -o \"$kw\" preview/index.html 2>/dev/null | wc -l)",
  "  echo \"  $kw: $n 次\"",
  "done",
  "echo",
  "echo '--- hash 路由修复是否已部署 ---'",
  "grep -c 'kiosk,voice' preview/index.html 2>/dev/null || echo '(未找到注释，可能已压缩)'",
  "grep -c 'tokens' preview/index.html 2>/dev/null || echo 0"
], 60)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
