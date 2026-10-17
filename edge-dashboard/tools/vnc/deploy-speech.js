"use strict"

/**
 * 部署并实测 speech-bridge 语音服务。
 *
 * 期望结果（基于前置诊断）：
 *   /api/health  → model=true（vosk 中文模型可加载）、source=录音源名
 *   /api/beep    → ok=true（播放链路已实测可用）
 *   /api/record  → silent=true（麦克风采不到声音，属硬件问题）
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/deploy-speech.js
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || ""
const DIR = process.env.M1_DIR || "/home/" + USER + "/velaguard"
const PORT = process.env.M1_SPEECH_PORT || "8124"
const ROOT = path.join(__dirname, "..", "..")

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgsp-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgsp.sh && bash /tmp/vgsp.sh"
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

function scpUp(local, remotePath) {
  const r = spawnSync("scp", OPTS.concat([local, USER + "@" + HOST + ":" + remotePath]),
    { encoding: "utf8", timeout: 90000, env: env() })
  return { ok: r.status === 0, err: String(r.stderr || "") }
}

/* ------------------------------------------------------------------ */
console.log("=== 部署 speech-bridge 语音服务 ===")

const up = scpUp(path.join(ROOT, "linux", "speech-bridge.py"), DIR + "/linux/speech-bridge.py")
console.log("\n上传 speech-bridge.py: " + (up.ok ? "成功" : "失败 " + up.err.trim()))

remote("1. 启动服务", [
  "chmod +x " + DIR + "/linux/speech-bridge.py",
  "pkill -f 'speech-bridge.py' 2>/dev/null",
  "sleep 1",
  "cd " + DIR + "/linux",
  "setsid nohup python3 speech-bridge.py --port " + PORT + " >/tmp/speech.log 2>&1 < /dev/null &",
  "sleep 4",
  "echo '--- 进程 ---'",
  "pgrep -af 'speech-bridge.py' || echo '(未运行)'",
  "echo",
  "echo '--- 启动日志 ---'",
  "cat /tmp/speech.log"
], 120)

remote("2. /api/health 探活（首次会加载模型，较慢）", [
  "echo '--- 请求 ---'",
  "curl -s --max-time 120 http://127.0.0.1:" + PORT + "/api/health",
  "echo"
], 180)

remote("3. /api/beep 提示音（播放链路）", [
  "echo '--- 请求 ---'",
  "curl -s --max-time 20 -X POST -H 'Content-Type: application/json' -d '{\"kind\":\"ready\"}' http://127.0.0.1:" + PORT + "/api/beep",
  "echo"
], 60)

remote("4. /api/record 录音识别（预期 silent=true）", [
  "echo '--- 请求（录音 3 秒）---'",
  "curl -s --max-time 60 -X POST -H 'Content-Type: application/json' -d '{\"seconds\":3}' http://127.0.0.1:" + PORT + "/api/record",
  "echo",
  "echo",
  "echo '--- 服务日志尾部 ---'",
  "tail -5 /tmp/speech.log"
], 120)

remote("5. 确认可被局域网访问（看板从 127.0.0.1 调用即可）", [
  "ss -ltn 2>/dev/null | grep " + PORT + " || netstat -ltn 2>/dev/null | grep " + PORT + " || echo '(查不到监听)'"
], 60)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
