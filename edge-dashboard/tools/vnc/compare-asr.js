"use strict"

/**
 * 决定性对比：把「能识别」和「识别不出」的音频在 vosk 前做直接对照。
 *
 * 已知：
 *   /tmp/vb_utt.wav  (2ch/48k)  → 转成 1ch/16k 后 vosk 识别出完整句子 ✓
 *   /tmp/vg_loop.wav (1ch/16k)  → 包络明显是语音，但 vosk 四种方式全返回空 ✗
 *
 * 两者都是 1ch/16k，为何结果不同？需要直接对照：
 *   1. 确认 vb_utt.wav 转换后是否**仍然**能被识别（排除偶然）
 *   2. 对同一个 TTS 源文件，分别用 24k / 16k 喂 vosk
 *   3. 直接把 TTS 源文件（24k）喂 vosk
 *
 * 只要能找到「哪一段音频能稳定识别出汉字」，就能确定识别链路是否可用。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/compare-asr.js
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
      askpass = path.join(os.tmpdir(), "vgca-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgca.sh && bash /tmp/vgca.sh"
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

remote("1. 对照：vb_utt.wav 转换后是否仍能识别（复现之前的成功）", [
  "cd /tmp",
  "python3 - <<'PY'",
  "import os, sys, wave, json, subprocess",
  "sys.path.insert(0, '/home/sunrise/voice_pipeline')",
  "src = '/tmp/vb_utt.wav'",
  "if not os.path.isfile(src):",
  "    print('vb_utt.wav 不存在（管线清理过 /tmp？）'); raise SystemExit",
  "dst = '/tmp/cmp_vb16k.wav'",
  "try:",
  "    import vcmd",
  "    ok = vcmd.to_asr_wav(src, dst, 16000)",
  "except Exception as e:",
  "    ok = False; print('to_asr_wav 失败:', e)",
  "print('转换:', ok, os.path.getsize(dst) if os.path.isfile(dst) else 0, '字节')",
  "if not os.path.isfile(dst): raise SystemExit",
  "from vosk import Model, KaldiRecognizer, SetLogLevel",
  "SetLogLevel(-1)",
  "model = Model('/home/sunrise/vosk-model-small-cn-0.22')",
  "w = wave.open(dst)",
  "rec = KaldiRecognizer(model, w.getframerate())",
  "while True:",
  "    d = w.readframes(4000)",
  "    if len(d) == 0: break",
  "    rec.AcceptWaveform(d)",
  "r = json.loads(rec.FinalResult())",
  "t = (r.get('text') or '').strip()",
  "print('识别结果:', repr(t))",
  "print('→', '可识别' if t else '空')",
  "PY"
], 300)

remote("2. 对照：同一个 TTS 源，用原始 24k 直接喂 vosk", [
  "python3 - <<'PY'",
  "import wave, json, os, glob",
  "from vosk import Model, KaldiRecognizer, SetLogLevel",
  "SetLogLevel(-1)",
  "model = Model('/home/sunrise/vosk-model-small-cn-0.22')",
  "# 取一个较大的 TTS 文件（内容较长的整句）",
  "cands = sorted(glob.glob('/home/sunrise/voice_pipeline/tts_cache/*.wav'), key=os.path.getsize, reverse=True)[:3]",
  "for p in cands:",
  "    w = wave.open(p)",
  "    rate = w.getframerate(); ch = w.getnchannels()",
  "    n = w.getnframes()",
  "    print('%s: %dch %dHz %.2fs %d 字节' % (os.path.basename(p), ch, rate, n/float(rate), os.path.getsize(p)))",
  "    data = w.readframes(n)",
  "    # vosk 只接受单声道 16bit；若是立体声需抽取左声道",
  "    if ch > 1:",
  "        import struct",
  "        s = struct.unpack('<%dh' % (len(data)//2), data)",
  "        s = s[0::ch]",
  "        data = struct.pack('<%dh' % len(s), *s)",
  "    rec = KaldiRecognizer(model, rate)",
  "    for i in range(0, len(data), 4000):",
  "        rec.AcceptWaveform(data[i:i+4000])",
  "    t = (json.loads(rec.FinalResult()).get('text') or '').strip()",
  "    print('   识别:', repr(t))",
  "    print()",
  "PY"
], 300)

remote("3. 关键：把 TTS 源重采样到 16k 再喂 vosk（排除采样率因素）", [
  "python3 - <<'PY'",
  "import wave, json, os, glob, subprocess, audioop, struct",
  "from vosk import Model, KaldiRecognizer, SetLogLevel",
  "SetLogLevel(-1)",
  "model = Model('/home/sunrise/vosk-model-small-cn-0.22')",
  "cands = sorted(glob.glob('/home/sunrise/voice_pipeline/tts_cache/*.wav'), key=os.path.getsize, reverse=True)[:2]",
  "for p in cands:",
  "    w = wave.open(p)",
  "    ch = w.getnchannels(); rate = w.getframerate(); n = w.getnframes()",
  "    data = w.readframes(n)",
  "    if ch > 1:",
  "        data = audioop.tomono(data, 2, 0.5, 0.5)",
  "    if rate != 16000:",
  "        data, _ = audioop.ratecv(data, 2, 1, rate, 16000, None)",
  "    print('%s → 单声道 16000Hz, %d 字节' % (os.path.basename(p), len(data)))",
  "    rec = KaldiRecognizer(model, 16000)",
  "    for i in range(0, len(data), 4000):",
  "        rec.AcceptWaveform(data[i:i+4000])",
  "    t = (json.loads(rec.FinalResult()).get('text') or '').strip()",
  "    print('   识别:', repr(t))",
  "    print()",
  "PY"
], 300)

remote("4. 顺带确认唤醒音频是否还在（厂商自检产出）", [
  "ls -l /tmp/wwloop.raw /tmp/wwdump*.raw 2>/dev/null || echo '(无唤醒原始音频)'",
  "echo",
  "echo '--- /tmp 下所有 wav/raw ---'",
  "ls -la /tmp/*.wav /tmp/*.raw 2>/dev/null | head -15 || echo '(无)'"
], 120)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
