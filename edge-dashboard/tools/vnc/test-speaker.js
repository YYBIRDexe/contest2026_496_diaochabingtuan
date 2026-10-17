"use strict"

/**
 * 播放一段持续、易辨认的测试音，供人工确认 E5 屏是否有扬声器。
 *
 * 背景：提示音已改走 ALSA 硬件设备（plughw:0,1）并返回成功，
 * 但硬件上是否存在扬声器无法从软件判断 —— 只有人耳能确认。
 * 所以放一段有节奏的"三连音"，让用户直接听。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/test-speaker.js
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
      askpass = path.join(os.tmpdir(), "vgts-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgts.sh && bash /tmp/vgts.sh"
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

/* ------------------------------------------------------------------ */
console.log("=== 播放测试音（请听 E5 屏）===")

remote("1. 生成 6 秒三连音测试文件", [
  "python3 - <<'PY'",
  "import wave, struct, math",
  "rate = 16000",
  "path = '/tmp/vg-speaker-test.wav'",
  "w = wave.open(path, 'w')",
  "w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)",
  "frames = bytearray()",
  "# 三组：每组 3 声 660Hz 短音，组间停顿更久，便于辨认",
  "for group in range(3):",
  "    for beep in range(3):",
  "        n = int(rate * 0.22)",
  "        fade = int(rate * 0.02)",
  "        for i in range(n):",
  "            env = 1.0",
  "            if i < fade: env = i / fade",
  "            elif i > n - fade: env = (n - i) / fade",
  "            v = int(20000 * env * math.sin(2 * math.pi * 660 * i / rate))",
  "            frames += struct.pack('<h', v)",
  "        sil = int(rate * 0.18)",
  "        for i in range(sil):",
  "            frames += struct.pack('<h', 0)",
  "    sil2 = int(rate * 0.7)",
  "    for i in range(sil2):",
  "        frames += struct.pack('<h', 0)",
  "w.writeframes(bytes(frames))",
  "w.close()",
  "import os",
  "print('已生成', path, os.path.getsize(path), '字节')",
  "PY"
], 120)

remote("2. 经 ALSA 硬件设备播放（plughw:0,1）", [
  "echo '--- aplay plughw:0,1 ---'",
  "aplay -D plughw:0,1 /tmp/vg-speaker-test.wav 2>&1 | head -5",
  "echo \"退出码=$?\"",
  "echo",
  "echo '--- 播放时设备是否被占用过（看 hw_params）---'",
  "cat /proc/asound/card0/pcm1p/sub0/hw_params 2>/dev/null || echo '(读不到，播放已结束属正常)'",
  "echo",
  "echo '--- CS4344 控件状态 ---'",
  "amixer -c 0 sget 'CS4344 Control' 2>&1 | head -8 || echo '(无该控件)'"
], 180)

remote("3. 对比：经 PulseAudio 播放（预期听不到，因只有 auto_null）", [
  "echo '--- paplay（走 auto_null 空设备）---'",
  "paplay /tmp/vg-speaker-test.wav 2>&1 | head -3",
  "echo \"退出码=$?\"",
  "echo",
  "echo '说明：退出码 0 但声音进的是 Dummy Output，听不到 —— 这正是之前的 bug。'"
], 180)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。请告知是否听到三组「滴滴滴」的声音。")
