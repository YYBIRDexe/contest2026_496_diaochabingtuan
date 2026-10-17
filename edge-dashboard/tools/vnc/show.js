'use strict'

/**
 * 在 M1 的真实 X 会话上打开看板并抓屏。
 *
 * 踩过的坑：
 *   - firefox --headless --screenshot 在 RDK X3 上失败（SWGL 无法映射 framebuffer）
 *   - 用 --profile <不存在目录> 会弹 "Profile Missing" 并退出
 *   - PIL 读不了 XWD，需用 ffmpeg 转 PNG
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/show.js [--window] [--url URL]
 */

const fs = require('fs')
const path = require('path')
const os = require('os')
const { spawnSync } = require('child_process')

const HOST = process.env.M1_HOST || '192.168.1.104'
const USER = process.env.M1_USER || 'sunrise'
const PASS = process.env.M1_PASS || ''
const PORT = process.env.M1_PORT || '8123'
const WINDOWED = process.argv.indexOf('--window') >= 0
const urlArg = process.argv.indexOf('--url')
const URL_ = urlArg >= 0 ? process.argv[urlArg + 1] : 'http://127.0.0.1:' + PORT + '/#kiosk'

const ROOT = path.join(__dirname, '..', '..')
const SHOT_DIR = path.join(ROOT, 'preview', 'm1')

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), 'vgsh-' + Date.now() + '.cmd')
      fs.writeFileSync(askpass, '@echo off\r\necho %VG_SSH_PASS%\r\n', 'utf8')
    }
    e.VG_SSH_PASS = PASS
    e.SSH_ASKPASS = askpass
    e.SSH_ASKPASS_REQUIRE = 'force'
    e.DISPLAY = 'localhost:0'
  }
  return e
}

const OPTS = [
  '-o', 'StrictHostKeyChecking=no',
  '-o', 'UserKnownHostsFile=/dev/null',
  '-o', 'ConnectTimeout=10',
  '-o', 'LogLevel=ERROR',
  '-o', 'PreferredAuthentications=password,keyboard-interactive',
  '-o', 'PubkeyAuthentication=no',
  '-o', 'NumberOfPasswordPrompts=1'
]

function sh(title, lines, to) {
  if (title) {
    console.log('\n### ' + title)
  }
  const b64 = Buffer.from(lines.join('\n'), 'utf8').toString('base64')
  const r = spawnSync('ssh', OPTS.concat([USER + '@' + HOST,
    'echo ' + b64 + ' | base64 -d > /tmp/vgsh.sh && bash /tmp/vgsh.sh']), {
    encoding: 'utf8', timeout: (to || 90) * 1000, env: env(), maxBuffer: 8 * 1024 * 1024
  })
  const out = (String(r.stdout || '') + (r.stderr ? '\n[stderr] ' + String(r.stderr) : '')).trim()
  if (title) {
    console.log(out || '(no output)')
    if (r.error && /ETIMEDOUT/i.test(String(r.error.message || ''))) {
      console.log('  >>> TIMEOUT')
    }
  }
  return out
}

function get(remote, local) {
  const r = spawnSync('scp', OPTS.concat([USER + '@' + HOST + ':' + remote, local]),
    { encoding: 'utf8', timeout: 120000, env: env() })
  return { ok: r.status === 0, err: String(r.stderr || '') }
}

/* ------------------------------------------------------------------ */
sh('1. 关掉残留 Firefox、确认服务', [
  'pkill -f "Profile Missing" 2>/dev/null || true',
  'pkill -f firefox 2>/dev/null || true',
  'sleep 3',
  'cd /home/' + USER + '/velaguard',
  'if ! curl -s -o /dev/null http://127.0.0.1:' + PORT + '/preview/index.html; then',
  '  setsid nohup node tools/serve.js ' + PORT + ' >/tmp/vg-serve.log 2>&1 < /dev/null &',
  '  sleep 3',
  'fi',
  'echo "index: $(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:' + PORT + '/preview/index.html)"',
  'ps -eo pid,comm | grep -i firefox | grep -v grep || echo "no firefox running"',
  'free -m | head -2'
], 70)

// 关键修正：不要用 --profile 指向不存在的目录
sh('2. 启动看板（' + (WINDOWED ? '窗口模式' : 'kiosk 全屏') + '）', [
  'export DISPLAY=:0',
  'export XAUTHORITY=$HOME/.Xauthority',
  'cd /home/' + USER + '/velaguard',
  WINDOWED
    ? 'setsid nohup firefox --new-instance --width 1280 --height 800 "' + URL_ + '" >/tmp/vg-ff.log 2>&1 < /dev/null &'
    : 'setsid nohup firefox --new-instance --kiosk "' + URL_ + '" >/tmp/vg-ff.log 2>&1 < /dev/null &',
  'echo "launched: ' + URL_ + '"',
  'sleep 28',
  'echo "--- firefox ---"',
  'ps -eo pid,rss,comm | grep -i firefox | grep -v grep || echo "NOT RUNNING"',
  'echo "--- windows ---"',
  'DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority xdotool search --onlyvisible --name "." getwindowname %@ 2>/dev/null | head -12 || echo "xdotool unavailable"',
  'echo "--- log ---"',
  'grep -vi "Crash Annotation" /tmp/vg-ff.log 2>/dev/null | tail -5'
], 120)

sh('3. 抓屏并转 PNG', [
  'export DISPLAY=:0',
  'export XAUTHORITY=$HOME/.Xauthority',
  'rm -f /tmp/vg.xwd /tmp/vg.png',
  'xwd -root -silent > /tmp/vg.xwd 2>/dev/null && echo "xwd ok $(stat -c%s /tmp/vg.xwd)"',
  'ffmpeg -y -loglevel error -i /tmp/vg.xwd /tmp/vg.png 2>&1 | tail -3',
  'python3 -c "from PIL import Image; im=Image.open(\'/tmp/vg.png\'); print(\'png\', im.size)" 2>/dev/null || echo "png check failed"'
], 120)

console.log('\n### 4. 取回截图')
fs.mkdirSync(SHOT_DIR, { recursive: true })
const dstAbs = path.join(SHOT_DIR, 'm1-kiosk.png')
const g = get('/tmp/vg.png', dstAbs)
if (g.ok) {
  console.log('  ✓ ' + dstAbs + ' (' + fs.statSync(dstAbs).size + ' bytes)')
} else {
  console.log('  ✗ ' + g.err.trim())
}

if (askpass) {
  fs.unlinkSync(askpass)
}
console.log('\n完成。')
