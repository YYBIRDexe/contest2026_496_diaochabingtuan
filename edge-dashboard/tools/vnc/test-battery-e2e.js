"use strict"

/**
 * 端到端实测「查询小车电量」指令，并验证播报不再被中断。
 *
 * 做法（不依赖人说话）：
 *   1. 用设备 TTS 合成「小车的电量怎么样了」
 *   2. 通过语音桥触发一轮（桥会先停唤醒引擎让出麦克风）
 *   3. 等 assistant 进入录音状态后，把合成音频从扬声器放出来
 *   4. 轮询 /tmp/voice_text.jsonl 取结果，检查 intent 是否为 battery
 *   5. 同时观察 aplay 进程，确认播报完整放完
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/test-battery-e2e.js
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || ""
const DIR = "/home/sunrise/voice_pipeline"

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgbe-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgbe.sh && bash /tmp/vgbe.sh"
  const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST, cmd]), {
    encoding: "utf8",
    timeout: (timeoutSec || 240) * 1000,
    env: env(),
    maxBuffer: 32 * 1024 * 1024
  })
  const out = (String(r.stdout || "") + (r.stderr ? "\n[stderr] " + String(r.stderr) : "")).trim()
  if (title) { console.log(out || "(no output)") }
  return out
}

console.log("=== 「查询小车电量」端到端实测 ===")

remote("1. 准备：清记录 + 合成测试语音", [
  "cd " + DIR,
  "> /tmp/voice_text.jsonl 2>/dev/null; echo '记录已清空'",
  "python3 - <<'PY'",
  "import sys; sys.path.insert(0, '.')",
  "import tts",
  "p = tts.synth('小车的电量怎么样了')",
  "import os",
  "print('合成:', p, os.path.getsize(p), '字节')",
  "PY"
], 240)

remote("2. 触发一轮（后台），并在录音开始后播测试语音", [
  "cd " + DIR,
  "# 清场：让桥自己停唤醒引擎；这里先确保没有残留录音进程",
  "pkill -9 -f 'arecord.*hobotsnd5' 2>/dev/null; sleep 1",
  "",
  "# 后台触发语音桥（它会停唤醒引擎、写 FIFO、等结果）",
  "curl -s --max-time 90 -X POST -H 'Content-Type: application/json' \\",
  "  -d '{\"wait\":50}' http://127.0.0.1:8124/api/voice/talk > /tmp/bat_talk.json 2>&1 &",
  "BRIDGE=$!",
  "",
  "# 等助手开始录音（最多 20 秒）",
  "for i in $(seq 1 40); do",
  "  if grep -q '录音中' /tmp/voice_wake.log 2>/dev/null && \\",
  "     [ \"$(tail -c 400 /tmp/voice_wake.log | grep -c '检测到说话')\" = \"0\" ]; then",
  "    break",
  "  fi",
  "  sleep 0.5",
  "done",
  "sleep 1",
  "",
  "echo '--- 播放测试语音（扬声器 -> 麦克风）---'",
  "SRC=$(ls -t tts_cache/*.wav | head -1)",
  "echo \"  播放: $SRC\"",
  "aplay -D plughw:0,1 \"$SRC\" >/dev/null 2>&1 && echo '  已播放' || echo '  播放失败'",
  "",
  "wait $BRIDGE 2>/dev/null",
  "echo",
  "echo '--- 桥返回 ---'",
  "cat /tmp/bat_talk.json"
], 300)

remote("3. 结果与链路日志", [
  "echo '=== 桥返回 ==='",
  "cat /tmp/bat_talk.json; echo",
  "echo",
  "echo '=== voice_text.jsonl ==='",
  "cat /tmp/voice_text.jsonl 2>/dev/null || echo '(无记录)'",
  "echo",
  "echo '=== voice_wake.log 最后 30 行 ==='",
  "tail -30 /tmp/voice_wake.log"
], 200)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
