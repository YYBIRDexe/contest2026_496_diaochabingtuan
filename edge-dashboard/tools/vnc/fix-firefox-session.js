"use strict"

/**
 * 在 M1 上启动 VelaGuard 看板，并修复 Firefox 的会话恢复弹窗。
 *
 * 背景：用 pkill 结束 Firefox 后，下次启动会弹
 *   "Sorry. We're having trouble getting your pages back."
 * 并停在对话框上，导致看板不显示。
 * 解决：在 Firefox 配置目录写 user.js 关掉会话恢复与崩溃提示。
 *
 * 为什么优先选择「用户选定的 profile」而不是每次新建临时 profile：
 *   start.sh 不带 -profile，Firefox 用的是默认 profile。
 *   所以把 prefs 写进默认 profile 才能让 start.sh 干净启动。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/fix-firefox-session.js
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
      askpass = path.join(os.tmpdir(), "vgff-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgff.sh && bash /tmp/vgff.sh"
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

function grab(name) {
  remote(null, [
    "export DISPLAY=:0",
    "rm -f /tmp/vgff.xwd /tmp/vgff.png",
    "xwd -root -silent > /tmp/vgff.xwd 2>/dev/null",
    "ffmpeg -y -loglevel error -i /tmp/vgff.xwd /tmp/vgff.png 2>/dev/null",
    "echo shot-done"
  ], 120)
  const dir = path.join(ROOT, "preview", "m1")
  fs.mkdirSync(dir, { recursive: true })
  const dst = path.join(dir, name)
  const r = spawnSync("scp", OPTS.concat([USER + "@" + HOST + ":/tmp/vgff.png", dst]),
    { encoding: "utf8", timeout: 120000, env: env() })
  if (r.status === 0 && fs.existsSync(dst)) {
    console.log("  ✓ " + name + " (" + fs.statSync(dst).size + " bytes)")
    return true
  }
  console.log("  ✗ 抓屏失败: " + String(r.stderr || "").trim())
  return false
}

/* ------------------------------------------------------------------ */
console.log("=== 修复 Firefox 会话恢复弹窗并重启看板 ===")

/* 1. 找出默认 profile 目录 */
const prof = remote("1. 定位 Firefox profile", [
  "echo '--- profiles.ini ---'",
  "cat $HOME/.mozilla/firefox/profiles.ini 2>/dev/null || echo '(无 profiles.ini)'",
  "echo",
  "echo '--- profile 目录 ---'",
  "ls -d $HOME/.mozilla/firefox/*/ 2>/dev/null"
], 60)

/* 2. 写入 user.js 关闭会话恢复 */
remote("2. 写入 user.js（关闭会话恢复与崩溃提示）", [
  "PROFILE=$HOME/.mozilla/firefox/mil0n1oy.default-release",
  "if [ ! -d \"$PROFILE\" ]; then",
  "  PROFILE=$(ls -d $HOME/.mozilla/firefox/*.default-release 2>/dev/null | head -1)",
  "fi",
  "if [ -z \"$PROFILE\" ] || [ ! -d \"$PROFILE\" ]; then",
  "  PROFILE=$(grep -oP 'Path=\\K.*' $HOME/.mozilla/firefox/profiles.ini 2>/dev/null | head -1)",
  "  [ -n \"$PROFILE\" ] && PROFILE=$HOME/.mozilla/firefox/$PROFILE",
  "fi",
  "echo \"目标 profile: $PROFILE\"",
  "echo",
  "cat > \"$PROFILE/user.js\" <<'EOF'",
  "// 由 VelaGuard 部署脚本写入：让 kiosk 看板每次干净启动",
  "// 关闭会话恢复 —— 否则异常退出后会弹「恢复上次会话」对话框挡住看板",
  "user_pref(\"browser.sessionstore.resume_from_crash\", false);",
  "user_pref(\"browser.sessionstore.max_resumed_crashes\", 0);",
  "user_pref(\"browser.sessionstore.enabled\", false);",
  "user_pref(\"browser.startup.page\", 0);",
  "// 关闭「上次未正常关闭」提示条",
  "user_pref(\"browser.tabs.warnOnClose\", false);",
  "user_pref(\"browser.tabs.warnOnCloseOtherTabs\", false);",
  "user_pref(\"browser.warnOnQuit\", false);",
  "// 关闭退出确认",
  "user_pref(\"browser.showQuitWarning\", false);",
  "user_pref(\"browser.tabs.closeWindowWithLastTab\", true);",
  "EOF",
  "echo 'user.js 已写入:'",
  "cat \"$PROFILE/user.js\""
], 60)

/* 3. 清理会话恢复文件，避免残留状态 */
remote("3. 清理会话恢复残留文件", [
  "PROFILE=$(ls -d $HOME/.mozilla/firefox/*.default-release 2>/dev/null | head -1)",
  "[ -n \"$PROFILE\" ] || PROFILE=$HOME/.mozilla/firefox/mil0n1oy.default-release",
  "echo \"profile: $PROFILE\"",
  "echo",
  "echo '--- 清理前 ---'",
  "ls -la \"$PROFILE/sessionstore-backups\" 2>/dev/null | head -5 || echo '(无备份目录)'",
  "rm -f \"$PROFILE/sessionstore.jsonlz4\" 2>/dev/null",
  "rm -rf \"$PROFILE/sessionstore-backups\" 2>/dev/null",
  "echo",
  "echo '--- 清理后 ---'",
  "ls \"$PROFILE/sessionstore.jsonlz4\" 2>/dev/null || echo '(sessionstore 已清除)'"
], 60)

/* 4. 重启看板 */
remote("4. 重启看板", [
  "export DISPLAY=:0",
  "pkill -f firefox 2>/dev/null",
  "sleep 4",
  "echo '--- 确认已退出 ---'",
  "pgrep -af firefox || echo '(已全部退出)'",
  "echo",
  "cd " + DIR + "/linux",
  "./start.sh --serve >/tmp/velaguard-start.log 2>&1 &",
  "sleep 32",
  "echo '--- Firefox 进程 ---'",
  "pgrep -af firefox | head -2 || echo '(未启动)'",
  "echo",
  "echo '--- 打开的 URL ---'",
  "ps -eo args | grep [f]irefox | head -1",
  "echo",
  "echo '--- 服务 ---'",
  "curl -s -o /dev/null -w 'index=%{http_code}\\n' http://127.0.0.1:" + PORT + "/preview/index.html",
  "echo",
  "echo '--- 内存 ---'",
  "free -m | head -2"
], 150)

console.log("\n### 5. 抓屏验证")
grab("dashboard-final.png")

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
