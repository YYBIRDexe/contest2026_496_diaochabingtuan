"use strict"

/**
 * 验证「开机自启」是否真的能拉起看板。
 *
 * 说明：无法靠读文件证明自启动有效，必须实际执行自启动项里的命令。
 * 登录桌面时 XDG autostart 就是执行 .desktop 里 Exec= 那行，
 * 所以这里直接执行同一行命令，效果等价。
 *
 * 同时把界面恢复到首页（默认启动形态），避免停在语音助手页。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/test-autostart.js
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
      askpass = path.join(os.tmpdir(), "vgas2-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgas2.sh && bash /tmp/vgas2.sh"
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

function grab(name) {
  remote(null, [
    "export DISPLAY=:0",
    "rm -f /tmp/vgas2.xwd /tmp/vgas2.png",
    "xwd -root -silent > /tmp/vgas2.xwd 2>/dev/null",
    "ffmpeg -y -loglevel error -i /tmp/vgas2.xwd /tmp/vgas2.png 2>/dev/null",
    "echo SIZE=$(stat -c%s /tmp/vgas2.png 2>/dev/null || echo 0)",
    "python3 -c \"from PIL import Image; im=Image.open('/tmp/vgas2.png').convert('L'); px=list(im.getdata()); print('DARK='+str(round(sum(1 for v in px if v<60)/len(px)*100,1)))\" 2>/dev/null || echo DARK=?"
  ], 120)
  const dir = path.join(ROOT, "preview", "m1")
  fs.mkdirSync(dir, { recursive: true })
  const dst = path.join(dir, name)
  const r = spawnSync("scp", OPTS.concat([USER + "@" + HOST + ":/tmp/vgas2.png", dst]),
    { encoding: "utf8", timeout: 120000, env: env() })
  return r.status === 0 && fs.existsSync(dst) ? dst : null
}

/* ------------------------------------------------------------------ */
console.log("=== 验证开机自启 ===")

/* 1. 读出两个自启动项里真正要执行的命令 */
remote("1. 自启动项的 Exec 命令", [
  "echo '--- velaguard.desktop ---'",
  "grep '^Exec=' $HOME/.config/autostart/velaguard.desktop",
  "echo",
  "echo '--- velaguard-hide-cursor.desktop ---'",
  "grep '^Exec=' $HOME/.config/autostart/velaguard-hide-cursor.desktop",
  "echo",
  "echo '--- x3m-campus.desktop（应为 Hidden=true）---'",
  "grep -E '^(Hidden|Exec)=' $HOME/.config/autostart/x3m-campus.desktop"
], 60)

/* 2. 清场：关掉现有 Firefox，模拟「刚登录桌面」的状态 */
remote("2. 清场（关掉现有 Firefox 与看板）", [
  "export DISPLAY=:0",
  "pkill -f firefox 2>/dev/null",
  "pkill -f 'serve.js' 2>/dev/null",
  "sleep 4",
  "echo '--- 确认已清空 ---'",
  "pgrep -af firefox || echo '(无 firefox)'",
  "pgrep -af serve.js || echo '(无 serve)'",
  "echo",
  "echo '--- 桌面仍在（模拟已登录）---'",
  "pgrep -c xfce4-session"
], 90)

/* 3. 执行自启动项里的命令（等价于登录时 XDG autostart 的动作） */
remote("3. 执行自启动命令（模拟登录）", [
  "export DISPLAY=:0",
  "cd " + DIR,
  "setsid nohup " + DIR + "/linux/start.sh --serve >/tmp/autostart-test.log 2>&1 < /dev/null &",
  "sleep 34",
  "echo '--- 启动日志 ---'",
  "grep -viE 'Crash Annotation' /tmp/autostart-test.log | tail -10",
  "echo",
  "echo '--- 看板是否起来 ---'",
  "ps -eo args | grep [f]irefox | head -1 || echo '(未启动)'",
  "echo",
  "echo '--- 数据服务 ---'",
  "pgrep -af serve.js | head -1 || echo '(未运行)'",
  "echo",
  "echo '--- 窗口标题 ---'",
  "for w in $(xdotool search --onlyvisible --class firefox 2>/dev/null | head -1); do",
  "  echo \"TITLE=$(xdotool getwindowname $w 2>/dev/null)\"",
  "done"
], 150)

/* 4. 验证渲染 */
console.log("\n### 4. 抓屏验证")
const shot = grab("autostart-verified.png")
console.log("  " + (shot ? "✓ " + shot : "✗ 抓屏失败"))

remote("5. 最终判据", [
  "export DISPLAY=:0",
  "rm -f /tmp/av.png /tmp/av.xwd",
  "xwd -root -silent > /tmp/av.xwd 2>/dev/null",
  "ffmpeg -y -loglevel error -i /tmp/av.xwd /tmp/av.png 2>/dev/null",
  "python3 - <<'PY'",
  "from PIL import Image",
  "im = Image.open('/tmp/av.png').convert('L')",
  "px = list(im.getdata())",
  "dark = sum(1 for v in px if v < 60) / len(px) * 100",
  "print('暗像素', round(dark, 1), '%')",
  "print('结论:', 'PASS —— 自启动命令能正常拉起看板' if dark > 50 else 'FAIL —— 未渲染')",
  "PY"
], 120)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
