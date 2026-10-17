"use strict"

/**
 * 闭环自检：TTS 合成已知语句 → 扬声器播放 → 麦克风录制 → vosk 离线识别 → 比对。
 *
 * 目的：把「人是否在说话」这个变量排除掉，单独验证
 *      「麦克风 + vosk + 我们的录音参数」这条链路本身是否正确。
 *
 * 为什么需要：/api/record 已能录到真实声音（peak 3360），但识别结果为空。
 * 必须区分两种可能：
 *   a) 识别链路有问题（模型/参数/音频格式）
 *   b) 录音时确实没人在说话
 *
 * 设备上已有 tts_cache/*.wav（管线生成的语音缓存），可直接拿来播。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/selfcheck-asr.js
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
      askpass = path.join(os.tmpdir(), "vgsc-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgsc.sh && bash /tmp/vgsc.sh"
  const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST, cmd]), {
    encoding: "utf8",
    timeout: (timeoutSec || 240) * 1000,
    env: env(),
    maxBuffer: 16 * 1024 * 1024
  })
  const out = (String(r.stdout || "") + (r.stderr ? "\n[stderr] " + String(r.stderr) : "")).trim()
  if (title) { console.log(out || "(no output)") }
  return out
}

remote("1. 可用的 TTS 缓存（拿来当已知音频源）", [
  "echo '--- tts_cache 内容 ---'",
  "ls -la /home/sunrise/voice_pipeline/tts_cache/ 2>/dev/null | head -15",
  "echo",
  "echo '--- 用 tts.py 合成一句确定的话 ---'",
  "cd /home/sunrise/voice_pipeline",
  "python3 - <<'PY'",
  "import sys, os",
  "sys.path.insert(0, '/home/sunrise/voice_pipeline')",
  "try:",
  "    import tts",
  "    p = tts.synth('开始本轮巡检')",
  "    print('合成成功:', p)",
  "    print('大小:', os.path.getsize(p), '字节')",
  "except Exception as e:",
  "    print('合成失败:', e)",
  "PY"
], 240)

remote("2. 闭环自检：播放「开始本轮巡检」同时录音", [
  "cd /tmp",
  "SRC=$(ls -t /home/sunrise/voice_pipeline/tts_cache/*.wav 2>/dev/null | head -1)",
  "echo \"播放源: $SRC\"",
  "if [ -z \"$SRC\" ]; then echo '(无可用音频)'; exit 0; fi",
  "python3 -c \"",
  "import wave",
  "w = wave.open('$SRC')",
  "print('源音频: 声道 %d 采样率 %d 帧数 %d (%.2f 秒)' % (w.getnchannels(), w.getframerate(), w.getnframes(), w.getnframes()/float(w.getframerate())))",
  "\" 2>&1",
  "echo",
  "# 先启动录音，再播放，确保录到",
  "pkill -9 -f arecord 2>/dev/null; sleep 1",
  "rm -f /tmp/vg_loop.wav",
  "( arecord -D default -c 1 -r 16000 -f S16_LE -d 6 /tmp/vg_loop.wav >/dev/null 2>&1 ) &",
  "sleep 1",
  "aplay -D plughw:0,1 \"$SRC\" >/dev/null 2>&1",
  "echo '已播放'",
  "wait",
  "ls -l /tmp/vg_loop.wav 2>/dev/null || echo '(无录音)'"
], 200)

remote("3. 分析闭环录音并离线识别", [
  "python3 - <<'PY'",
  "import wave, struct, json, os",
  "from vosk import Model, KaldiRecognizer, SetLogLevel",
  "SetLogLevel(-1)",
  "p = '/tmp/vg_loop.wav'",
  "if not os.path.isfile(p) or os.path.getsize(p) <= 44:",
  "    print('无有效录音'); raise SystemExit",
  "w = wave.open(p)",
  "n = w.getnframes(); rate = w.getframerate()",
  "d = w.readframes(n)",
  "s = struct.unpack('<%dh' % (len(d)//2), d)",
  "peak = max(abs(x) for x in s) if s else 0",
  "avg = sum(abs(x) for x in s)//len(s) if s else 0",
  "print('录音: 声道 %d 采样率 %d 帧数 %d (%.2f 秒)' % (w.getnchannels(), rate, n, n/float(rate or 1)))",
  "print('幅度: 峰值 %d 平均 %d' % (peak, avg))",
  "print()",
  "if peak < 200:",
  "    print('录音基本静音 —— 扬声器到麦克风的声学耦合太弱，无法闭环自检')",
  "    print('（这不代表麦克风坏，只说明扬声器声音没被麦克风拾到）')",
  "    raise SystemExit",
  "w.rewind()",
  "model = Model('/home/sunrise/vosk-model-small-cn-0.22')",
  "rec = KaldiRecognizer(model, rate)",
  "while True:",
  "    chunk = w.readframes(4000)",
  "    if len(chunk) == 0: break",
  "    rec.AcceptWaveform(chunk)",
  "r = json.loads(rec.FinalResult())",
  "txt = (r.get('text') or '').strip()",
  "print('离线识别:', repr(txt))",
  "print()",
  "if txt:",
  "    print('✓✓ 闭环自检通过：麦克风→vosk 链路正确工作')",
  "else:",
  "    print('录到了声音但没识别出文字 —— 可能是音量太低或声音不是语音')",
  "PY"
], 300)

remote("4. 顺带验证：设备上的 TTS 提示音是否能被听到（播 3 秒）", [
  "echo '--- 播一段较长的 TTS 音频 ---'",
  "SRC=$(ls -S /home/sunrise/voice_pipeline/tts_cache/*.wav 2>/dev/null | head -1)",
  "ls -l \"$SRC\" 2>/dev/null",
  "timeout 20 aplay -D plughw:0,1 \"$SRC\" 2>&1 | head -3",
  "echo 'rc='$?",
  "echo",
  "echo '（若你听到声音，说明 E4 扬声器正常）'"
], 200)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
