'use strict'

/**
 * 验收最后一步：验证 M1 上的真实数据链路。
 *
 *   1. 在 M1 上后台持续写 data/state.json（模拟巡检推进）
 *   2. 在 M1 的 Firefox 里把数据源切到「M1 数据」（点状态栏标签）
 *   3. 抓屏，确认界面显示的是外部数据而不是内置演示数据
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/verify-live.js
 */

const fs = require('fs')
const path = require('path')
const os = require('os')
const { spawnSync } = require('child_process')

const HOST = process.env.M1_HOST || '192.168.1.104'
const USER = process.env.M1_USER || 'sunrise'
const PASS = process.env.M1_PASS || ''
const PORT = process.env.M1_PORT || '8123'
const DIR = '/home/' + USER + '/velaguard'
const ROOT = path.join(__dirname, '..', '..')
const SHOT_DIR = path.join(ROOT, 'preview', 'm1')

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), 'vglv-' + Date.now() + '.cmd')
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
  if (title) { console.log('\n### ' + title) }
  const b64 = Buffer.from(lines.join('\n'), 'utf8').toString('base64')
  const r = spawnSync('ssh', OPTS.concat([USER + '@' + HOST,
    'echo ' + b64 + ' | base64 -d > /tmp/vglv.sh && bash /tmp/vglv.sh']), {
    encoding: 'utf8', timeout: (to || 90) * 1000, env: env(), maxBuffer: 8 * 1024 * 1024
  })
  const out = (String(r.stdout || '') + (r.stderr ? '\n[stderr] ' + String(r.stderr) : '')).trim()
  if (title) {
    console.log(out || '(no output)')
    if (r.error && /ETIMEDOUT/i.test(String(r.error.message || ''))) { console.log('  >>> TIMEOUT') }
  }
  return out
}

function grab(name) {
  sh(null, [
    'export DISPLAY=:0',
    'export XAUTHORITY=$HOME/.Xauthority',
    'rm -f /tmp/vg.xwd /tmp/vg.png',
    'xwd -root -silent > /tmp/vg.xwd 2>/dev/null',
    'ffmpeg -y -loglevel error -i /tmp/vg.xwd /tmp/vg.png 2>/dev/null',
    'ls -l /tmp/vg.png 2>/dev/null | awk "{print \\$5}"'
  ], 90)
  const dst = path.join(SHOT_DIR, name)
  fs.mkdirSync(SHOT_DIR, { recursive: true })
  const r = spawnSync('scp', OPTS.concat([USER + '@' + HOST + ':/tmp/vg.png', dst]),
    { encoding: 'utf8', timeout: 120000, env: env() })
  if (r.status === 0 && fs.existsSync(dst)) {
    console.log('  ✓ ' + name + ' (' + fs.statSync(dst).size + ' bytes)')
    return true
  }
  console.log('  ✗ 抓屏失败: ' + String(r.stderr || '').trim())
  return false
}

/* ------------------------------------------------------------------ */
sh('1. 启动数据模拟器（M1 本机持续写 state.json）', [
  'pkill -f simulate-m1 2>/dev/null || true',
  'sleep 1',
  'cd ' + DIR,
  'setsid nohup node tools/simulate-m1.js 2000 >/tmp/vg-sim.log 2>&1 < /dev/null &',
  'sleep 8',
  'echo "--- sim log ---"',
  'tail -6 /tmp/vg-sim.log',
  'echo "--- state.json ---"',
  'ls -l ' + DIR + '/data/state.json 2>/dev/null || echo "NO state.json"',
  'curl -s http://127.0.0.1:' + PORT + '/data/state.json | head -c 300'
], 90)

console.log('\n### 2. 抓屏：切换前的状态栏')
grab('live-before.png')

sh('3. 点击状态栏数据源标签，切到「M1 数据」', [
  'export DISPLAY=:0',
  'export XAUTHORITY=$HOME/.Xauthority',
  'if command -v xdotool >/dev/null 2>&1; then',
  '  W=$(xdotool search --name "VelaGuard" | head -1)',
  '  echo "window=$W"',
  '  # 远端屏幕 1920x1080，设计宽 1280，缩放约 1.5；数据源标签在桌面右上区域',
  '  xdotool mousemove 1180 55 click 1',
  '  echo "clicked (1180,55)"',
  '  sleep 4',
  '  xdotool mousemove 1180 55 click 1',
  '  echo "clicked again (cycle to next source)"',
  '  sleep 4',
  'else',
  '  echo "xdotool 不可用，无法自动点击"',
  'fi'
], 90)

console.log('\n### 4. 抓屏：切换后')
grab('live-after.png')

sh('5. 状态汇总', [
  'echo "--- 模拟器还在写吗 ---"',
  'ps -eo pid,args | grep "[s]imulate-m1" || echo "模拟器已停止"',
  'echo "--- state.json ---"',
  'cat ' + DIR + '/data/state.json 2>/dev/null | head -c 400',
  'echo ""',
  'echo "--- firefox ---"',
  'ps -eo pid,rss,comm | grep -i firefox | grep -v grep || echo "no firefox"',
  'free -m | head -2'
], 60)

if (askpass) { fs.unlinkSync(askpass) }
console.log('\n完成。')
