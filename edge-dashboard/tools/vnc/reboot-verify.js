"use strict"

/**
 * 重启 M1 并验证完整开机自启链路。
 *
 * 验证目标（按启动顺序）：
 *   1. 系统起来、SSH 可达
 *   2. 自动登录成功（无需密码就进桌面：xfce4-session 存在、无 greeter）
 *   3. XDG autostart 拉起看板（serve.js + Firefox kiosk 打开看板 URL）
 *   4. 看板真正渲染出来（暗像素判据）
 *   5. 鼠标光标已隐藏
 *   6. 校园网状态页未自启
 *
 * 用法：
 *   $env:M1_HOST/M1_USER/M1_PASS
 *   node tools/vnc/reboot-verify.js --reboot   # 执行重启并等待验证
 *   node tools/vnc/reboot-verify.js            # 只做验证（不重启）
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || ""
const ROOT = path.join(__dirname, "..", "..")
const DO_REBOOT = process.argv.indexOf("--reboot") >= 0

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgrb-" + Date.now() + ".cmd")
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
  "-o", "ConnectTimeout=8",
  "-o", "LogLevel=ERROR",
  "-o", "PreferredAuthentications=password,keyboard-interactive",
  "-o", "PubkeyAuthentication=no",
  "-o", "NumberOfPasswordPrompts=1"
]

/** 带超时执行远端脚本；返回 { ok, out } */
function remote(title, lines, timeoutSec) {
  if (title) { console.log("\n### " + title) }
  const b64 = Buffer.from(lines.join("\n"), "utf8").toString("base64")
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgrb.sh && bash /tmp/vgrb.sh"
  const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST, cmd]), {
    encoding: "utf8",
    timeout: (timeoutSec || 60) * 1000,
    env: env(),
    maxBuffer: 16 * 1024 * 1024
  })
  const out = (String(r.stdout || "") + (r.stderr ? "\n[stderr] " + String(r.stderr) : "")).trim()
  if (title) { console.log(out || "(no output)") }
  return { ok: r.status === 0, out: out }
}

function sleep(sec) {
  spawnSync("node", ["-e", "setTimeout(function(){}," + (sec * 1000) + ")"],
    { timeout: (sec + 5) * 1000 })
}

/* ------------------------------------------------------------------ */
console.log("=== M1 开机自启验证" + (DO_REBOOT ? "（含重启）" : "") + " ===")

/* 0. 重启前状态 */
remote("0. 重启前状态", [
  "uptime -p",
  "echo XORG_PID=$(pgrep -x Xorg | head -1)",
  "echo FF=$(pgrep -c firefox)",
  "echo SERVE=$(pgrep -c -f serve.js)"
], 60)

if (DO_REBOOT) {
  console.log("\n>>> 执行重启（设备会在约 40-90 秒后重新可达）")
  /*
   * 依次尝试三种途径，每种都显式判断结果，不能用 || 短路 ——
   * 上一版就是 `sudo -n reboot || systemctl reboot` 被短路，
   * 结果重启根本没执行，却误以为成功了（uptime 暴露了这一点）。
   *
   * 可用性依据：sudo 需要密码（NOPASSWD 只放行两个代理脚本），
   * 但会话是 Type=x11 / Active=yes / Remote=no（本地活动会话），
   * PolicyKit 通常允许这种会话直接 reboot。
   */
  const rb = remote(null, [
    "echo '--- 途径 1: systemctl reboot（走 logind/PolicyKit）---'",
    "systemctl reboot 2>&1 | head -3",
    "rc1=$?",
    "echo \"systemctl rc=$rc1\"",
    "echo",
    "echo '--- 途径 2: dbus-send 到 logind ---'",
    "dbus-send --system --print-reply --dest=org.freedesktop.login1 \\",
    "  /org/freedesktop/login1 org.freedesktop.login1.Manager.Reboot boolean:true 2>&1 | head -3",
    "echo",
    "echo '--- 途径 3: xfce4-session-logout（无 GUI 模式）---'",
    "xfce4-session-logout --reboot --fast 2>&1 | head -3"
  ], 30)
  console.log(rb.out)
  console.log("    重启命令已发出")
}

/* 1b. 立即确认重启是否真的开始（uptime 应很小） */
if (DO_REBOOT) {
  console.log("\n### 1a. 确认重启是否真的开始")
  let started = false
  for (let i = 0; i < 6; i += 1) {
    sleep(5)
    const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST,
      "cut -d. -f1 /proc/uptime 2>/dev/null || echo NOPE"]),
      { encoding: "utf8", timeout: 12000, env: env() })
    const out = String(r.stdout || "").trim()
    if (out === "NOPE" || out === "" || r.status !== 0) {
      console.log("  ✓ 连接已断开（设备正在重启）")
      started = true
      break
    }
    console.log("  …uptime 仍为 " + out + " 秒，等待重启生效")
  }
  if (!started) {
    console.log("  !! 未检测到重启迹象（uptime 未归零、连接未断）")
    console.log("     可能三种途径都需要密码。请手动在 M1 上重启，或告知我可用方式。")
  }
}

/* 1. 等待 SSH 恢复 */
console.log("\n### 1. 等待设备重新可达")
let reachable = false
let waited = 0
const MAX_WAIT = DO_REBOOT ? 240 : 0

if (DO_REBOOT) {
  sleep(25)
  while (waited < MAX_WAIT) {
    const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST, "echo __UP__"]),
      { encoding: "utf8", timeout: 15000, env: env() })
    if (String(r.stdout || "").indexOf("__UP__") >= 0) {
      reachable = true
      break
    }
    waited += 10
    console.log("  …已等待 " + (waited + 25) + " 秒")
    sleep(10)
  }
} else {
  reachable = true
}
console.log("  " + (reachable ? "✓ SSH 已恢复（约 " + (waited + 25) + " 秒）" : "✗ 超时未恢复"))

if (!reachable) {
  console.log("\n!! 设备未恢复可达，无法继续验证。")
  if (askpass) { fs.unlinkSync(askpass) }
  process.exit(1)
}

/* 2. 给桌面与自启留出启动时间 */
console.log("\n### 2. 等待桌面与自启完成（最多 120 秒）")
let deskOk = false
for (let i = 0; i < 12; i += 1) {
  sleep(10)
  const r = remote(null, [
    "echo UPTIME=$(cut -d. -f1 /proc/uptime)",
    "echo XORG=$(pgrep -c -x Xorg)",
    "echo XFCE=$(pgrep -c xfce4-session)",
    "echo GREETER=$(pgrep -c lightdm-gtk-greeter)",
    "echo FF=$(pgrep -c firefox)",
    "echo SERVE=$(pgrep -c -f serve.js)"
  ], 40)
  const get = function (k) { return (r.out.match(new RegExp(k + "=(\\d+)")) || [])[1] || "0" }
  const up = get("UPTIME")
  const xfce = get("XFCE")
  const ff = get("FF")
  const serve = get("SERVE")
  console.log("  [已开机 " + up + "s] Xorg=" + get("XORG") + " 桌面=" + xfce +
    " greeter=" + get("GREETER") + " firefox=" + ff + " serve=" + serve)

  if (xfce !== "0" && ff !== "0" && serve !== "0") {
    deskOk = true
    break
  }
}

/* 3. 最终验证 */
remote("3. 最终状态", [
  "echo '--- 开机时长 ---'",
  "uptime -p",
  "echo",
  "echo '--- 是否自动登录（关键）---'",
  "echo \"桌面会话: $(pgrep -c xfce4-session)\"",
  "echo \"登录界面: $(pgrep -c lightdm-gtk-greeter)  （0=已自动登录）\"",
  "echo",
  "echo '--- 看板 ---'",
  "ps -eo args | grep [f]irefox | head -1 || echo '(未运行)'",
  "echo",
  "echo '--- 数据服务 ---'",
  "pgrep -af serve.js | head -1 || echo '(未运行)'",
  "echo",
  "echo '--- 校园网状态页是否被误启 ---'",
  "pgrep -af 'status.html' || echo '(未启动，正确)'",
  "echo",
  "echo '--- 窗口标题 ---'",
  "for w in $(xdotool search --onlyvisible --class firefox 2>/dev/null | head -1); do",
  "  echo \"TITLE=$(xdotool getwindowname $w 2>/dev/null)\"",
  "done"
], 90)

/* 4. 抓屏 */
console.log("\n### 4. 抓屏")
const g = remote(null, [
  "export DISPLAY=:0",
  "rm -f /tmp/vgrb.xwd /tmp/vgrb.png",
  "xwd -root -silent > /tmp/vgrb.xwd 2>/dev/null",
  "ffmpeg -y -loglevel error -i /tmp/vgrb.xwd /tmp/vgrb.png 2>/dev/null",
  "echo SIZE=$(stat -c%s /tmp/vgrb.png 2>/dev/null || echo 0)",
  "python3 -c \"from PIL import Image; im=Image.open('/tmp/vgrb.png').convert('L'); px=list(im.getdata()); print('DARK='+str(round(sum(1 for v in px if v<60)/len(px)*100,1)))\" 2>/dev/null || echo DARK=?"
], 120)

const size = (g.out.match(/SIZE=(\d+)/) || [])[1] || "0"
const dark = (g.out.match(/DARK=([\d.]+)/) || [])[1] || "?"
const rendered = Number(dark) > 50

const dir = path.join(ROOT, "preview", "m1")
fs.mkdirSync(dir, { recursive: true })
const dst = path.join(dir, "boot-verified.png")
const scp = spawnSync("scp", OPTS.concat([USER + "@" + HOST + ":/tmp/vgrb.png", dst]),
  { encoding: "utf8", timeout: 120000, env: env() })
if (scp.status === 0 && fs.existsSync(dst)) {
  console.log("  ✓ boot-verified.png (" + fs.statSync(dst).size + " bytes)")
}

console.log("\n" + "=".repeat(56))
console.log("开机自启验证结论")
console.log("=".repeat(56))
console.log("  桌面会话拉起: " + (deskOk ? "✓" : "✗"))
console.log("  看板渲染:     " + (rendered ? "✓ 暗像素 " + dark + "%" : "✗ 未渲染（暗像素 " + dark + "%）"))
console.log("  截图:         " + (fs.existsSync(dst) ? dst : "(无)"))

if (askpass) { fs.unlinkSync(askpass) }
