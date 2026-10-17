'use strict'

/**
 * 部署「触屏优化」到 M1：界面（禁文字选中）+ start.sh（会话内隐藏光标）。
 *
 * 关键点：隐藏光标必须在**图形会话内**启动才能拿到有效的 X 授权。
 * SSH 会话拿不到（Xorg 用 -auth /var/run/lightdm/root/:0，属 root），
 * 所以不能靠 SSH 常驻，只能由 start.sh / 自启动项在会话内拉起。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/deploy-touch-fix.js
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

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), 'vgtf-' + Date.now() + '.cmd')
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
  const cmd = 'echo ' + b64 + ' | base64 -d > /tmp/vgtf.sh && bash /tmp/vgtf.sh'
  const r = spawnSync('ssh', OPTS.concat([USER + '@' + HOST, cmd]), {
    encoding: 'utf8', timeout: (timeoutSec || 120) * 1000, env: env(),
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
console.log('=== 部署触屏优化 ===')

remote(null, ['mkdir -p ' + DIR + '/preview ' + DIR + '/linux'], 40)

const files = [
  ['preview/index.html', DIR + '/preview/index.html'],
  ['linux/start.sh', DIR + '/linux/start.sh'],
  ['linux/hide-cursor.c', DIR + '/linux/hide-cursor.c']
]
for (const [local, dst] of files) {
  const abs = path.join(ROOT, local)
  if (!fs.existsSync(abs)) {
    console.log('  跳过（本地缺失）: ' + local)
    continue
  }
  const r = scpUp(abs, dst)
  console.log('  ' + (r.ok ? '✓' : '✗') + ' ' + local + (r.ok ? '' : '  ' + r.err.trim()))
}

remote('1. start.sh 语法校验 + 赋可执行', [
  'chmod +x ' + DIR + '/linux/start.sh',
  'bash -n ' + DIR + '/linux/start.sh && echo "start.sh 语法正确" || echo "!! start.sh 语法错误"',
  'echo "--- 隐藏光标相关片段 ---"',
  'grep -n "hide-cursor\\|unclutter" ' + DIR + '/linux/start.sh | head -12'
], 60)

remote('2. 确认 hide-cursor 已编译且可用', [
  'BIN=' + DIR + '/linux/hide-cursor',
  'if [ -x "$BIN" ]; then',
  '  echo "hide-cursor 已就绪 ($(stat -c%s "$BIN") 字节)"',
  'else',
  '  echo "!! hide-cursor 未编译，正在编译…"',
  '  cd ' + DIR + '/linux',
  '  X11LIB=$(ls /usr/lib/aarch64-linux-gnu/libX11.so 2>/dev/null | head -1)',
  '  XFIXESLIB=$(ls /usr/lib/aarch64-linux-gnu/libXfixes.so* 2>/dev/null | head -1)',
  '  if [ -n "$XFIXESLIB" ]; then',
  '    gcc -O2 -o hide-cursor hide-cursor.c "$X11LIB" "$XFIXESLIB" && echo "编译成功（含 Xfixes）"',
  '  else',
  '    gcc -O2 -DNO_XFIXES -o hide-cursor hide-cursor.c "$X11LIB" && echo "编译成功（纯 X11）"',
  '  fi',
  'fi'
], 120)

remote('3. 验证界面里的防选中样式已生效', [
  'cd ' + DIR,
  'echo "--- 检查产物里是否含 user-select: none ---"',
  'grep -c "user-select: none" preview/index.html 2>/dev/null || echo 0',
  'echo "--- 检查是否含 contextmenu 拦截 ---"',
  'grep -c "contextmenu" preview/index.html 2>/dev/null || echo 0',
  'echo "--- 检查是否含 selectstart 拦截 ---"',
  'grep -c "selectstart" preview/index.html 2>/dev/null || echo 0',
  'echo "--- 数据服务是否在跑 ---"',
  'ps -eo pid,args | grep "[s]erve.js" || echo "(未运行)"',
  'echo "--- 界面可访问性 ---"',
  'curl -s -o /dev/null -w "HTTP %{http_code}" http://127.0.0.1:8123/preview/index.html; echo'
], 60)

remote('4. 当前图形会话状态（决定光标方案能否生效）', [
  'echo "--- X 会话 ---"',
  'ps -eo user,pid,args | grep "[X]org" | head -2',
  'echo "--- 是否已登录桌面 ---"',
  'if pgrep -f "xfce4-session" >/dev/null 2>&1; then echo "桌面已登录"; else echo "!! 桌面未登录（当前在 LightDM 登录界面）"; fi',
  'echo "--- 当前 SSH 能否访问 X（预期：不能，正常）---"',
  'DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority xdpyinfo 2>&1 | head -1',
  'echo "--- 看板是否在跑 ---"',
  'ps -eo pid,args | grep "[f]irefox --new-instance" | head -2 || echo "(Firefox 未运行)"'
], 60)

if (askpass) { fs.unlinkSync(askpass) }
console.log('\n完成。')
