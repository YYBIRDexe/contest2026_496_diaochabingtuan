'use strict'

/**
 * 判定触摸数据是否进了 M1。
 *
 * 方法：
 *   1. 记录触摸前 X 的输入设备列表 + 指针位置（XFCE 桌面下鼠标指针会随触摸移动）
 *   2. 等待若干秒，期间请用户用手指点屏幕
 *   3. 记录触摸后的状态，对比是否出现新输入设备 / 指针是否移动
 *   4. 两种方式交叉验证：X 级判定 + VNC 抓屏像素对比
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/detect-touch.js [等待秒数]
 */

const fs = require('fs')
const path = require('path')
const os = require('os')
const { spawnSync } = require('child_process')

const HOST = process.env.M1_HOST || '192.168.1.104'
const USER = process.env.M1_USER || 'sunrise'
const PASS = process.env.M1_PASS || ''
const WAIT = Number(process.argv[2] || 30)
const ROOT = path.join(__dirname, '..', '..')

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), 'vgd2-' + Date.now() + '.cmd')
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

function sh(lines, to) {
  const b64 = Buffer.from(lines.join('\n'), 'utf8').toString('base64')
  const r = spawnSync('ssh', OPTS.concat([USER + '@' + HOST,
    'echo ' + b64 + ' | base64 -d > /tmp/vgd2.sh && bash /tmp/vgd2.sh']), {
    encoding: 'utf8', timeout: (to || 60) * 1000, env: env(), maxBuffer: 8 * 1024 * 1024
  })
  return (String(r.stdout || '') + (r.stderr ? '\n[stderr] ' + String(r.stderr) : '')).trim()
}

/* 记录一次快照：输入设备 + 指针位置 + 内核 usb 事件数 */
function snapshot() {
  return sh([
    'export DISPLAY=:0; export XAUTHORITY=$HOME/.Xauthority',
    'echo "INPUT_DEVS=$(xinput list --name-only 2>/dev/null | tr \'\\n\' \'|\')"',
    'echo "POINTER=$(xdotool getmouselocation 2>/dev/null | head -1)"',
    'echo "DEVINPUT=$(ls /dev/input/ 2>/dev/null | tr \'\\n\' \',\')"',
    'echo "DMESG_LINES=$(dmesg 2>/dev/null | wc -l)"'
  ], 40)
}

function grab(name) {
  sh([
    'export DISPLAY=:0; export XAUTHORITY=$HOME/.Xauthority',
    'rm -f /tmp/vgd.xwd /tmp/vgd.png',
    'xwd -root -silent > /tmp/vgd.xwd 2>/dev/null',
    'ffmpeg -y -loglevel error -i /tmp/vgd.xwd /tmp/vgd.png 2>/dev/null'
  ], 60)
  const dir = path.join(ROOT, 'preview', 'm1')
  fs.mkdirSync(dir, { recursive: true })
  const dst = path.join(dir, name)
  const r = spawnSync('scp', OPTS.concat([USER + '@' + HOST + ':/tmp/vgd.png', dst]),
    { encoding: 'utf8', timeout: 120000, env: env() })
  return r.status === 0 && fs.existsSync(dst)
}

function parse(s) {
  const out = {}
  String(s).split('\n').forEach(function (l) {
    const i = l.indexOf('=')
    if (i > 0) {
      out[l.slice(0, i)] = l.slice(i + 1)
    }
  })
  return out
}

/* ------------------------------------------------------------------ */
console.log('=== 触摸检测 ===\n')

console.log('步骤 1：记录触摸前状态')
const before = parse(snapshot())
console.log('  输入设备: ' + (before.INPUT_DEVS || '(无)'))
console.log('  指针位置: ' + (before.POINTER || '(未知)'))
console.log('  /dev/input: ' + (before.DEVINPUT || '(无)'))
console.log('  dmesg 行数: ' + before.DMESG_LINES)

console.log('\n抓取基线截图…')
const okA = grab('touch-before.png')
console.log('  ' + (okA ? '✓ touch-before.png' : '✗ 抓屏失败'))

console.log('\n' + '─'.repeat(60))
console.log('>>> 请现在用手指点屏幕上的「巡检调度台」磁贴（左上第一个大块）')
console.log('>>> 多点几下也行，' + WAIT + ' 秒后自动结束')
console.log('─'.repeat(60) + '\n')

for (let i = WAIT; i > 0; i -= 5) {
  console.log('  倒计时 ' + i + ' 秒…')
  spawnSync('node', ['-e', 'setTimeout(function(){},5000)'], { timeout: 8000 })
}

console.log('\n步骤 2：记录触摸后状态')
const after = parse(snapshot())
console.log('  输入设备: ' + (after.INPUT_DEVS || '(无)'))
console.log('  指针位置: ' + (after.POINTER || '(未知)'))
console.log('  /dev/input: ' + (after.DEVINPUT || '(无)'))
console.log('  dmesg 行数: ' + after.DMESG_LINES)

console.log('\n抓取结果截图…')
const okB = grab('touch-after.png')
console.log('  ' + (okB ? '✓ touch-after.png' : '✗ 抓屏失败'))

console.log('\n=== 判定 ===')
let verdict = []
if (before.INPUT_DEVS !== after.INPUT_DEVS) {
  verdict.push('输入设备列表发生变化 → 触摸设备出现了')
}
if (before.POINTER !== after.POINTER) {
  verdict.push('指针位置变化: ' + before.POINTER + ' → ' + after.POINTER + ' → 触摸能移动指针')
}
if (before.DEVINPUT !== after.DEVINPUT) {
  verdict.push('/dev/input 变化 → 有新输入节点')
}
if (before.DMESG_LINES !== after.DMESG_LINES) {
  verdict.push('内核有新日志（dmesg 行数 ' + before.DMESG_LINES + ' → ' + after.DMESG_LINES + '）')
}

if (verdict.length === 0) {
  console.log('  触摸未进入 M1：输入设备、指针、内核日志均无变化。')
  console.log('  → 触摸数据很可能走的是 Type-C（U2P 侧），不在 M1 上。')
} else {
  verdict.forEach(function (v) { console.log('  · ' + v) })
}
console.log('\n另外请对比 preview/m1/touch-before.png 与 touch-after.png 是否不同。')

if (askpass) { fs.unlinkSync(askpass) }
