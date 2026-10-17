"use strict"

/**
 * 精确定位 vosk 离线识别「有时能出字、有时为空」的原因。
 *
 * 已知矛盾：
 *   ✓ vosk 对 /tmp/vb_utt.wav（2ch/48k → 转 1ch/16k）识别出了完整句子
 *   ✗ vosk 对 /tmp/vg_loop.wav（1ch/16k，峰值 16886 的清晰音频）返回空
 *
 * 且 wakeword.py 用同一个中文模型能稳定识别「小陈同志」（厂商文档记为 8/8）。
 *
 * 可能原因：
 *   a) 音频内容确实不是语音（比如只是杂音/蜂鸣）
 *   b) 我在分析脚本里读帧顺序有 bug
 *   c) 模型/识别器参数用法不对
 *
 * 做法：用唤醒音频（与 wakeword.py 一致的 RAW 格式）+ 多种方式交叉验证。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/diag-vosk.js
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
      askpass = path.join(os.tmpdir(), "vgdv-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgdv.sh && bash /tmp/vgdv.sh"
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

remote("1. 分析闭环录音的音频特征（判断是否真是语音）", [
  "python3 - <<'PY'",
  "import wave, struct, os",
  "for p in ['/tmp/vg_loop.wav', '/tmp/vb_utt.wav']:",
  "    if not os.path.isfile(p):",
  "        print(p, '不存在'); continue",
  "    w = wave.open(p)",
  "    n = w.getnframes(); rate = w.getframerate(); ch = w.getnchannels()",
  "    d = w.readframes(n)",
  "    s = struct.unpack('<%dh' % (len(d)//2), d)",
  "    if ch > 1: s = s[0::ch]",
  "    peak = max(abs(x) for x in s) if s else 0",
  "    avg = sum(abs(x) for x in s)//len(s) if s else 0",
  "    # 逐 0.5 秒的峰值包络，看是否有人声的起伏",
  "    step = rate // 2",
  "    env = []",
  "    for i in range(0, min(len(s), step*12), step):",
  "        seg = s[i:i+step]",
  "        env.append(max(abs(x) for x in seg) if seg else 0)",
  "    print('%s: %dch %dHz %.2fs 峰值%d 平均%d' % (p, ch, rate, n/float(rate), peak, avg))",
  "    print('   包络(每0.5秒):', env)",
  "    print()",
  "PY"
], 200)

remote("2. 用 wakeword.py 的完全相同的解码方式测唤醒音频", [
  "python3 - <<'PY'",
  "import json, os, sys",
  "sys.path.insert(0, '/home/sunrise/voice_pipeline')",
  "from vosk import Model, KaldiRecognizer, SetLogLevel",
  "SetLogLevel(-1)",
  "model = Model('/home/sunrise/vosk-model-small-cn-0.22')",
  "print('模型加载完成')",
  "print()",
  "# 用厂商自检生成的唤醒音频 /tmp/wwloop.raw（16k 单声道 raw）",
  "p = '/tmp/wwloop.raw'",
  "if os.path.isfile(p):",
  "    data = open(p, 'rb').read()",
  "    print('/tmp/wwloop.raw 大小', len(data), '字节 =', len(data)//2, '采样')",
  "    rec = KaldiRecognizer(model, 16000)",
  "    rec.AcceptWaveform(data)",
  "    r = json.loads(rec.FinalResult())",
  "    print('普通解码结果:', repr(r.get('text','')))",
  "    print()",
  "    # 约束解码（wakeword.py 的做法）",
  "    g = json.dumps(['小 陈 同 志', '小 陈', '陈 同 志', '[unk]'], ensure_ascii=False)",
  "    rec2 = KaldiRecognizer(model, 16000, g)",
  "    rec2.AcceptWaveform(data)",
  "    r2 = json.loads(rec2.FinalResult())",
  "    print('约束解码结果:', repr(r2.get('text','')))",
  "else:",
  "    print('/tmp/wwloop.raw 不存在（唤醒自检没跑成功过）')",
  "PY"
], 300)

remote("3. 交叉验证：对 vg_loop.wav 用多种参数组合解码", [
  "python3 - <<'PY'",
  "import wave, json, os",
  "from vosk import Model, KaldiRecognizer, SetLogLevel",
  "SetLogLevel(-1)",
  "model = Model('/home/sunrise/vosk-model-small-cn-0.22')",
  "p = '/tmp/vg_loop.wav'",
  "if not os.path.isfile(p):",
  "    print('文件不存在'); raise SystemExit",
  "w = wave.open(p)",
  "rate = w.getframerate()",
  "data = w.readframes(w.getnframes())",
  "print('音频: %d 字节, 采样率 %d' % (len(data), rate))",
  "print()",
  "# 方式 A：一次性喂入",
  "rec = KaldiRecognizer(model, rate)",
  "rec.AcceptWaveform(data)",
  "a = json.loads(rec.FinalResult()).get('text','')",
  "print('A 一次性喂入      :', repr(a))",
  "# 方式 B：分块喂入",
  "rec2 = KaldiRecognizer(model, rate)",
  "for i in range(0, len(data), 4000):",
  "    rec2.AcceptWaveform(data[i:i+4000])",
  "b = json.loads(rec2.FinalResult()).get('text','')",
  "print('B 分块喂入        :', repr(b))",
  "# 方式 C：强制 16000 声明",
  "rec3 = KaldiRecognizer(model, 16000)",
  "for i in range(0, len(data), 4000):",
  "    rec3.AcceptWaveform(data[i:i+4000])",
  "c = json.loads(rec3.FinalResult()).get('text','')",
  "print('C 声明 16000      :', repr(c))",
  "# 方式 D：带约束词表（限定巡检领域词）",
  "g = json.dumps(['开 始 本 轮 巡 检', '现 在 哪 些 区 域 没 查 完', '小 陈 同 志', '[unk]'], ensure_ascii=False)",
  "rec4 = KaldiRecognizer(model, rate, g)",
  "for i in range(0, len(data), 4000):",
  "    rec4.AcceptWaveform(data[i:i+4000])",
  "d = json.loads(rec4.FinalResult()).get('text','')",
  "print('D 约束词表        :', repr(d))",
  "print()",
  "print('说明：D 若命中，说明这段音频确实是这些词之一，只是自由解码认不出。')",
  "PY"
], 300)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
