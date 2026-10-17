"use strict"

/**
 * 摸清设备上现成语音管线的正确用法，为「界面接入」做准备。
 *
 * 关键事实（已确认）：
 *   - 唤醒词「小陈同志」（中文）/「hi openvela」（英文，en_hit_rate.py 里实测过）
 *   - 触发方式：向 FIFO /tmp/voice_trigger 写一行即可
 *   - voice_button.py 是助手主体，负责录音→ASR→意图→下发→TTS 回报
 *   - 唤醒/助手的麦克风独占冲突已有成熟解法（stop_recorder）
 *
 * 本次要拿到：
 *   1. 启动脚本（重启语音.sh / 语音助手.sh）的完整内容 —— 这是正确的启动方式
 *   2. 当前进程的完整参数（--cloud-first 等），判断是否依赖外网
 *   3. /tmp/voice_wake.log 与 /tmp/voice_text.jsonl —— 看它实际听到了什么
 *   4. llm_intent.py 的行为（--cloud-first 意味着无网时会失败）
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/probe-pipeline-usage.js
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
      askpass = path.join(os.tmpdir(), "vgpu-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgpu.sh && bash /tmp/vgpu.sh"
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

remote("1. 启动脚本内容（这是正确用法）", [
  "for f in 重启语音.sh 语音助手.sh 守护启动.sh start_voice.sh start_listen.sh; do",
  "  p=/home/sunrise/voice_pipeline/$f",
  "  if [ -f \"$p\" ]; then",
  "    echo \"===== $f =====\"",
  "    cat \"$p\"",
  "    echo",
  "  fi",
  "done"
], 150)

remote("2. 唤醒与助手日志（看它实际听到/回复了什么）", [
  "echo '===== /tmp/voice_wake.log 尾部 40 行 ====='",
  "tail -40 /tmp/voice_wake.log 2>/dev/null || echo '(无)'",
  "echo",
  "echo '===== /tmp/voice_text.jsonl ====='",
  "cat /tmp/voice_text.jsonl 2>/dev/null | tail -10 || echo '(无)'"
], 150)

remote("3. 是否存在助手日志（语音助手的 stdout）", [
  "ls -la /tmp/*.log 2>/dev/null | head -20",
  "echo",
  "echo '--- 找含有请讲/识别/网络不通的日志 ---'",
  "grep -rl '网络不通' /tmp /home/sunrise/voice_pipeline/*.py 2>/dev/null | head -8 || echo '(未找到)'"
], 120)

remote("4. llm_intent.py 的联网行为（判断无网时怎么降级）", [
  "echo '===== llm_intent.py 全文 ====='",
  "cat /home/sunrise/voice_pipeline/llm_intent.py 2>/dev/null || echo '(读不到)'"
], 150)

remote("5. 关键：助手是否支持「手动触发」（不靠唤醒词）", [
  "echo '--- voice_button.py 的 trigger 选项 ---'",
  "grep -n -A2 -E \"add_argument\\('--trigger'|add_argument\\('--once'|add_argument\\('--fifo'\" /home/sunrise/voice_pipeline/voice_button.py 2>/dev/null | head -20",
  "echo",
  "echo '--- 是否支持 http 触发（便于界面接入）---'",
  "grep -n -iE 'http|socket|listen|server|port' /home/sunrise/voice_pipeline/voice_button.py 2>/dev/null | head -15 || echo '(不支持 http)'",
  "echo",
  "echo '--- 触发来源类型全集 ---'",
  "grep -n -E \"trigger ===|trigger ==|'fifo'|'key'|'gpio'|'stdin'\" /home/sunrise/voice_pipeline/voice_button.py 2>/dev/null | head -15 || echo '(读不到)'"
], 150)

remote("6. 验证 FIFO 触发是否可用（安全：只是写一行）", [
  "echo '--- fifo 状态 ---'",
  "ls -l /tmp/voice_trigger 2>/dev/null",
  "echo",
  "echo '--- 当前助手进程是否在等触发 ---'",
  "ps -eo pid,etime,args | grep '[v]oice_button' || echo '(助手未运行)'",
  "echo",
  "echo '--- 提示：此处不实际写入，避免贸然触发助手 ---'",
  "echo '    （需要时用: echo go > /tmp/voice_trigger）'"
], 120)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
