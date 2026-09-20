"use strict"

/**
 * 探明设备上已有的语音管线 /home/sunrise/voice_pipeline/。
 *
 * 这是本轮最重要的发现：设备上已经装了完整的语音链路并正在运行：
 *   voice_button.py  --trigger fifo --fifo /tmp/voice_trigger
 *                    --agent-backend command --agent-cmd .../llm_intent.py
 *                    --cloud-first --vcmd-exec --tts --tts-prompt
 *   wakeword.py      --fifo /tmp/voice_trigger --lang en     （常驻占用麦克风）
 *
 * 也就是说「按住说话」很可能应当复用这套管线，而不是我另起炉灶。
 * 而且 --lang en 解释了用户喊「hi openvela」的由来。
 *
 * 同时清理我上一轮脚本遗留的 miFactorytest_main（timeout 没杀干净）。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/probe-voice-pipeline.js
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
      askpass = path.join(os.tmpdir(), "vgvp-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgvp.sh && bash /tmp/vgvp.sh"
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

remote("1. 先清掉我上轮遗留的工厂测试进程", [
  "echo '--- 清理前 ---'",
  "ps -eo pid,args | grep -E '[m]iFactory' || echo '(无)'",
  "echo",
  "pkill -9 -f miFactorytest 2>/dev/null",
  "sleep 1",
  "echo '--- 清理后 ---'",
  "ps -eo pid,args | grep -E '[m]iFactory' || echo '(已清空)'",
  "echo",
  "echo '注意：那个 miFactorytest_main 是我的 timeout 没杀干净留下的，不是设备自启的。'"
], 120)

remote("2. voice_pipeline 目录结构", [
  "echo '--- 目录 ---'",
  "ls -la /home/sunrise/voice_pipeline/ 2>/dev/null || echo '(不存在)'",
  "echo",
  "echo '--- 是否有 README / 说明 ---'",
  "for f in /home/sunrise/voice_pipeline/*.md /home/sunrise/voice_pipeline/README*; do",
  "  [ -f \"$f\" ] && { echo \"===== $f =====\"; head -60 \"$f\"; }",
  "done 2>/dev/null || echo '(无说明文件)'"
], 150)

remote("3. 管线当前运行状态与日志", [
  "echo '--- 相关进程 ---'",
  "ps -eo pid,etime,args | grep -E '[v]oice_pipeline' || echo '(未运行)'",
  "echo",
  "echo '--- 唤醒词检测的原始录音参数（它占着麦克风）---'",
  "ps -eo pid,args | grep '[a]record' || echo '(无 arecord)'",
  "echo",
  "echo '--- fifo 是否就绪 ---'",
  "ls -l /tmp/voice_trigger 2>/dev/null || echo '(无 fifo)'",
  "echo",
  "echo '--- 日志文件 ---'",
  "ls -la /tmp/*voice* /tmp/*wake* /home/sunrise/voice_pipeline/*.log 2>/dev/null | head -10 || echo '(无日志)'"
], 150)

remote("4. 唤醒词与意图识别配置（找 hi openvela 的出处）", [
  "echo '--- 搜唤醒词配置 ---'",
  "grep -rn -iE 'openvela|wake|keyword|hi ' /home/sunrise/voice_pipeline/*.py 2>/dev/null | head -20 || echo '(无匹配)'",
  "echo",
  "echo '--- 唤醒词模型文件 ---'",
  "find /home/sunrise/voice_pipeline -maxdepth 2 -type f \\( -name '*.ppn' -o -name '*.umdl' -o -name '*.pv' -o -name '*.bin' -o -name '*.onnx' \\) 2>/dev/null | head -10 || echo '(无模型文件)'"
], 180)

remote("5. 看 wakeword.py 的头尾（了解它怎么读麦克风）", [
  "echo '===== wakeword.py 前 60 行 ====='",
  "head -60 /home/sunrise/voice_pipeline/wakeword.py 2>/dev/null || echo '(读不到)'",
  "echo",
  "echo '===== 它用到的录音参数 ====='",
  "grep -n -E 'arecord|16000|channels|S16|hw:|plughw|default' /home/sunrise/voice_pipeline/wakeword.py 2>/dev/null | head -15 || echo '(无匹配)'"
], 150)

remote("6. 看 voice_button.py 的触发方式（界面该怎么接）", [
  "echo '===== 关键参数解析 ====='",
  "grep -n -E 'add_argument|fifo|trigger|agent|tts' /home/sunrise/voice_pipeline/voice_button.py 2>/dev/null | head -30 || echo '(读不到)'",
  "echo",
  "echo '===== llm_intent.py 是否存在 ====='",
  "ls -l /home/sunrise/voice_pipeline/llm_intent.py 2>/dev/null || echo '(不存在)'"
], 150)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
