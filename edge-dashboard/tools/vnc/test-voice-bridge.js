"use strict"

/**
 * 验证语音桥的新端点，并完整实测一次「界面按钮 → 设备语音链路」。
 *
 * 新增端点：
 *   GET  /api/voice/state  查设备语音服务进程状态
 *   POST /api/voice/talk   触发设备一轮完整语音交互并等结果
 *
 * 关键点：触发前桥会先停掉唤醒引擎（它常驻占用麦克风），
 * 否则手动触发必然以「麦克风被占用」失败。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/test-voice-bridge.js
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || ""
const PORT = process.env.M1_SPEECH_PORT || "8124"

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgvb-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgvb.sh && bash /tmp/vgvb.sh"
  const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST, cmd]), {
    encoding: "utf8",
    timeout: (timeoutSec || 180) * 1000,
    env: env(),
    maxBuffer: 16 * 1024 * 1024
  })
  const out = (String(r.stdout || "") + (r.stderr ? "\n[stderr] " + String(r.stderr) : "")).trim()
  if (title) { console.log(out || "(no output)") }
  return out
}

/* ------------------------------------------------------------------ */
console.log("=== 验证语音桥新端点 ===")

remote("1. 服务在跑吗", [
  "pgrep -af 'speech-bridge.py' || echo '(未运行)'",
  "echo",
  "echo '--- 监听端口 ---'",
  "ss -ltn 2>/dev/null | grep " + PORT + " || echo '(未监听)'"
], 60)

remote("2. GET /api/voice/state", [
  "echo '--- 请求 ---'",
  "curl -s --max-time 30 http://127.0.0.1:" + PORT + "/api/voice/state",
  "echo"
], 90)

remote("3. 触发前：设备侧语音进程状态", [
  "ps -eo pid,etime,args | grep -E '[v]oice_button|[w]akeword|[a]record' | head -5 || echo '(无)'"
], 90)

remote("4. POST /api/voice/talk（会先停唤醒引擎腾麦克风，再触发）", [
  "echo '--- 请求（最长等 45 秒）---'",
  "time curl -s --max-time 90 -X POST -H 'Content-Type: application/json' \\",
  "  -d '{\"wait\":40}' http://127.0.0.1:" + PORT + "/api/voice/talk",
  "echo"
], 180)

remote("5. 触发后：唤醒引擎是否已恢复", [
  "sleep 8",
  "echo '--- 进程 ---'",
  "ps -eo pid,etime,args | grep -E '[v]oice_button|[w]akeword|[a]record' | head -5 || echo '(无)'",
  "echo",
  "echo '--- 服务状态 ---'",
  "systemctl is-active voice-assistant.service",
  "echo",
  "echo '--- 唤醒日志尾部 ---'",
  "tail -14 /tmp/voice_wake.log"
], 150)

remote("6. 语音记录（应有新条目）", [
  "echo '--- /tmp/voice_text.jsonl 最后 3 条 ---'",
  "tail -3 /tmp/voice_text.jsonl 2>/dev/null || echo '(无记录)'"
], 90)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
