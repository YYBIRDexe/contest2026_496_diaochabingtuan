"use strict"

/**
 * 验证语音管线健康度与网络瓶颈。
 *
 * 已确认的事实链：
 *   - 管线在跑：wakeword.py + voice_button.py（--cloud-first --vcmd-exec --tts）
 *   - 唤醒词「hi openvela」确实被识别（日志有记录）
 *   - 「请讲」提示音有播放、S3 麦克风录到了 2.12 秒语音
 *   - 唯一卡点：云端预检失败 —— 代理 192.168.1.100:7890 连不上
 *
 * 本次要验证：
 *   1. 代理到底通不通（以及有没有可用的备选代理）
 *   2. 直连是否能出网（不走代理）
 *   3. 管线自带的扬声器自检（check_builtin_beep.py）是否通过
 *   4. 用 FIFO 手动触发一次，看完整链路卡在哪一步
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/verify-pipeline-chain.js
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
      askpass = path.join(os.tmpdir(), "vgpc2-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgpc2.sh && bash /tmp/vgpc2.sh"
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

remote("1. 代理连通性（管线卡在这一步）", [
  "echo '--- 当前代理环境变量 ---'",
  "cat /etc/x3m-proxy.env 2>/dev/null || echo '(无 /etc/x3m-proxy.env)'",
  "env | grep -iE 'proxy' || echo '(环境里无 proxy)'",
  "echo",
  "echo '--- 代理 192.168.1.100:7890 是否可达 ---'",
  "timeout 5 bash -c 'cat < /dev/null > /dev/tcp/192.168.1.100/7890' 2>&1 && echo '✓ 可连接' || echo '✗ 连不上'",
  "echo",
  "echo '--- 本机隧道是否可用（选代理.sh 的兜底方案）---'",
  "ls -l /etc/x3m-proxy.env 2>/dev/null",
  "ss -ltn 2>/dev/null | grep -E '7890|1080|1081' || echo '(本机无代理端口监听)'"
], 150)

remote("2. 直连与代理分别能否出网", [
  "echo '--- 直连（不走代理）---'",
  "timeout 8 curl -4 -s -o /dev/null -w '  直连 dashscope: %{http_code}\\n' https://dashscope.aliyuncs.com 2>&1 || echo '  直连失败'",
  "timeout 8 curl -4 -s -o /dev/null -w '  直连 deepseek: %{http_code}\\n' https://api.deepseek.com 2>&1 || echo '  直连失败'",
  "echo",
  "echo '--- 经代理 ---'",
  "timeout 8 curl -4 -s -x http://192.168.1.100:7890 -o /dev/null -w '  代理 deepseek: %{http_code}\\n' https://api.deepseek.com 2>&1 || echo '  代理失败'",
  "echo",
  "echo '--- 基础网络 ---'",
  "ip -4 addr show eth0 2>/dev/null | grep inet || echo '(无 IPv4)'",
  "ip route | head -3",
  "timeout 5 ping -c 1 -W 2 192.168.1.1 2>&1 | tail -2"
], 180)

remote("3. 管线自带的扬声器自检（厂商提供，最权威）", [
  "cd /home/sunrise/voice_pipeline",
  "echo '--- check_builtin_beep.py ---'",
  "timeout 30 python3 check_builtin_beep.py 2>&1 | head -20 || echo '(执行失败)'"
], 150)

remote("4. 唤醒自检（合成唤醒词→扬声器→麦克风→识别，全自动闭环）", [
  "cd /home/sunrise/voice_pipeline",
  "echo '--- 唤醒自检.py（会出声，可留意听）---'",
  "timeout 60 python3 唤醒自检.py 2>&1 | tail -25 || echo '(执行失败或超时)'"
], 240)

remote("5. FIFO 手动触发一次，看链路各步耗时与卡点", [
  "echo '--- 触发 ---'",
  "date '+%H:%M:%S 触发前'",
  "echo x > /tmp/voice_trigger 2>&1 && echo '已写入 FIFO' || echo 'FIFO 写入失败'",
  "sleep 25",
  "date '+%H:%M:%S 等待后'",
  "echo",
  "echo '--- 唤醒日志新增内容 ---'",
  "tail -25 /tmp/voice_wake.log 2>/dev/null",
  "echo",
  "echo '--- 最新一条识别记录 ---'",
  "tail -1 /tmp/voice_text.jsonl 2>/dev/null || echo '(无记录)'"
], 180)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
