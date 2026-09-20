'use strict'

/**
 * 部署并验证「隐藏鼠标光标」。
 *
 * 修复要点（针对上一版失效）：
 *   X 的光标是**逐窗口**属性。上一版只对根窗口 XDefineCursor，
 *   子窗口（Firefox 内容区、桌面、面板）会覆盖它 —— 指针移上去光标就恢复。
 *   现在改为**递归遍历整棵窗口树**逐窗口设置，并用 --watch 持续跟进新窗口。
 *
 * 验证要点（针对上一版的验证缺陷）：
 *   不能只看截图「没有光标图案」就判定成功 —— 那只能说明指针当时不在画面里。
 *   改为**把指针移到多个窗口上**（Firefox / 桌面 / 面板），逐个抓屏比对，
 *   并检查是否仍有可见光标像素。
 *
 * 用法：
 *   $env:M1_HOST/M1_USER/M1_PASS
 *   node tools/vnc/deploy-cursor.js            # 上传 + 编译 + 应用 + 验证
 *   node tools/vnc/deploy-cursor.js --stop     # 停止常驻进程
 */

const fs = require('fs')
const path = require('path')
const os = require('os')
const { spawnSync } = require('child_process')

const HOST = process.env.M1_HOST || '192.168.1.104'
const USER = process.env.M1_USER || 'sunrise'
const PASS = process.env.M1_PASS || ''
const DIR = process.env.M1_DIR || '/home/' + USER + '/velaguard'
const ROOT = path.join(__dirname, '..', '..')
const MODE = process.argv[2] || ''

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), 'vgdc2-' + Date.now() + '.cmd')
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

function remote(title, lines, timeoutSec) {
  if (title) { console.log('\n### ' + title) }
  const b64 = Buffer.from(lines.join('\n'), 'utf8').toString('base64')
  const cmd = 'echo ' + b64 + ' | base64 -d > /tmp/vgdc2.sh && bash /tmp/vgdc2.sh'
  const r = spawnSync('ssh', OPTS.concat([USER + '@' + HOST, cmd]), {
    encoding: 'utf8',
    timeout: (timeoutSec || 90) * 1000,
    env: env(),
    maxBuffer: 16 * 1024 * 1024
  })
  const out = (String(r.stdout || '') + (r.stderr ? '\n[stderr] ' + String(r.stderr) : '')).trim()
  if (title) { console.log(out || '(no output)') }
  return out
}

function scpUp(local, remotePath) {
  const r = spawnSync('scp', OPTS.concat([local, USER + '@' + HOST + ':' + remotePath]),
    { encoding: 'utf8', timeout: 90000, env: env() })
  return { ok: r.status === 0, err: String(r.stderr || '') }
}

/* ------------------------------------------------------------------ */
if (MODE === '--stop') {
  remote('停止常驻进程', [
    'pkill -f "hide-cursor --watch" 2>/dev/null && echo "已停止" || echo "未在运行"'
  ], 40)
  if (askpass) { fs.unlinkSync(askpass) }
  process.exit(0)
}

console.log('=== 部署隐藏光标（递归窗口树版本）===')

/* 1. 上传源码 */
const src = path.join(ROOT, 'linux', 'hide-cursor.c')
if (!fs.existsSync(src)) {
  console.error('找不到源文件：' + src)
  process.exit(1)
}
remote(null, ['mkdir -p ' + DIR + '/linux'], 40)
const up = scpUp(src, DIR + '/linux/hide-cursor.c')
console.log('\n上传源码: ' + (up.ok ? '成功' : '失败 ' + up.err.trim()))
if (!up.ok) {
  if (askpass) { fs.unlinkSync(askpass) }
  process.exit(1)
}

/* 2. 编译（现在只依赖 libX11） */
remote('1. 编译', [
  'cd ' + DIR + '/linux',
  'rm -f hide-cursor',
  'gcc -O2 -o hide-cursor hide-cursor.c -lX11 2>&1 | head -20',
  'if [ -x ./hide-cursor ]; then',
  '  echo "编译成功，$(stat -c%s hide-cursor) 字节"',
  'else',
  '  echo "!! 编译失败"',
  'fi'
], 120)

/* 3. 确认二进制版本 */
const chk = remote('2. 二进制自检（不连接 X）', [
  'cd ' + DIR + '/linux',
  './hide-cursor --check'
], 60)
if (chk.indexOf('递归窗口树') < 0) {
  console.error('\n!! 二进制不是递归窗口树版本，停止部署。')
  if (askpass) { fs.unlinkSync(askpass) }
  process.exit(1)
}
console.log('\n✓ 已确认是递归窗口树版本')

/* 4. 停止旧常驻，应用新版本并进入常驻 */
remote('3. 应用并常驻（跟进新窗口）', [
  'export DISPLAY=:0',
  'pkill -f "hide-cursor" 2>/dev/null',
  'sleep 1',
  'cd ' + DIR + '/linux',
  'setsid nohup ./hide-cursor --watch >/tmp/hide-cursor.log 2>&1 < /dev/null &',
  'sleep 3',
  'echo "--- 常驻进程 ---"',
  'pgrep -af "hide-cursor --watch" || echo "(未运行)"',
  'echo',
  'echo "--- 日志 ---"',
  'cat /tmp/hide-cursor.log'
], 90)

/* 5. 关键验证：把指针移到多个窗口上，确认都没有可见光标 */
console.log('\n### 4. 验证：指针移到不同窗口后是否仍无光标')

const positions = [
  ['Firefox 内容区', 960, 500],
  ['桌面空白处', 20, 1050],
  ['顶部面板', 960, 15],
  ['Firefox 磁贴', 950, 340]
]

for (const [label, x, y] of positions) {
  const r = remote(null, [
    'export DISPLAY=:0',
    'xdotool mousemove ' + x + ' ' + y,
    'sleep 1.2',
    'echo POS=$(xdotool getmouselocation | sed "s/.*window:\\([0-9]*\\).*/\\1/")',
    'rm -f /tmp/hc.xwd /tmp/hc.png',
    'xwd -root -silent > /tmp/hc.xwd 2>/dev/null',
    'ffmpeg -y -loglevel error -i /tmp/hc.xwd /tmp/hc.png 2>/dev/null',
    'python3 - <<PY',
    'from PIL import Image',
    'im = Image.open("/tmp/hc.png").convert("RGB")',
    'w, h = im.size',
    'cx, cy = ' + x + ', ' + y,
    '# 在指针位置周围 40x40 区域找亮像素（白色光标特征是高亮）',
    'box = im.crop((max(0,cx-20), max(0,cy-20), min(w,cx+20), min(h,cy+20)))',
    'px = list(box.getdata())',
    'bright = sum(1 for p in px if sum(p) > 600)',
    'print("指针附近亮像素:", bright, "/", len(px))',
    'PY'
  ], 120)
  const bright = (r.match(/指针附近亮像素:\s*(\d+)/) || [])[1] || '?'
  const win = (r.match(/POS=(\d+)/) || [])[1] || '?'
  console.log('  ' + label.padEnd(16) + ' 窗口=' + win + '  亮像素=' + bright +
    (Number(bright) < 60 ? '  ✓ 无光标' : '  ✗ 疑似有光标'))
}

/* 6. 记录最终状态 */
remote('5. 最终状态', [
  'export DISPLAY=:0',
  'echo "--- 常驻进程 ---"',
  'pgrep -af "hide-cursor --watch" || echo "(未运行)"',
  'echo',
  'echo "--- 日志 ---"',
  'cat /tmp/hide-cursor.log',
  'echo',
  'echo "--- X 与桌面是否健康 ---"',
  'echo "Xorg=$(pgrep -x Xorg | head -1)"',
  'echo "桌面=$(pgrep -c xfce4-session)"',
  'echo "看板=$(pgrep -c firefox)"'
], 60)

if (askpass) { fs.unlinkSync(askpass) }
console.log('\n完成。')
