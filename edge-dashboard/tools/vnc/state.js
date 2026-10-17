'use strict'

/**
 * 诊断 M1 的 X 会话状态：会话稳定性、X 授权、看板与光标进程。
 *
 * 用途：X 授权会随会话重启失效，本工具判断当前能否从 SSH 应用光标设置，
 * 以及桌面是否处于登录状态。
 *
 * 实现约定（避免踩坑）：
 *   - 远端脚本一律 base64 编码后传输，不经过任何引号拼装
 *   - 脚本里只用简单命令，不写正则、不写嵌套引号
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/state.js
 */

const fs = require('fs')
const path = require('path')
const os = require('os')
const { spawnSync } = require('child_process')

const HOST = process.env.M1_HOST || '192.168.1.104'
const USER = process.env.M1_USER || 'sunrise'
const PASS = process.env.M1_PASS || ''
const DIR = process.env.M1_DIR || '/home/' + USER + '/velaguard'

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), 'vgs4-' + Date.now() + '.cmd')
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
  console.log('\n### ' + title)
  const b64 = Buffer.from(lines.join('\n'), 'utf8').toString('base64')
  const cmd = 'echo ' + b64 + ' | base64 -d > /tmp/vgs4.sh && bash /tmp/vgs4.sh'
  const r = spawnSync('ssh', OPTS.concat([USER + '@' + HOST, cmd]), {
    encoding: 'utf8',
    timeout: (timeoutSec || 60) * 1000,
    env: env(),
    maxBuffer: 16 * 1024 * 1024
  })
  const out = (String(r.stdout || '') + (r.stderr ? '\n[stderr] ' + String(r.stderr) : '')).trim()
  console.log(out || '(no output)')
  return out
}

/* 1. 会话时长 ------------------------------------------------------ */
remote('1. 系统与 X 会话时长', [
  'date "+当前时间: %Y-%m-%d %H:%M:%S"',
  'uptime -p',
  'echo',
  'echo "Xorg 进程:"',
  'ps -eo pid,etime,comm | grep Xorg',
  'echo',
  'echo "xfce4-session（桌面）:"',
  'ps -eo pid,etime,comm | grep xfce4-session',
  'echo',
  'echo "lightdm-gtk-greeter（在跑=停在登录界面）:"',
  'ps -eo pid,etime,comm | grep lightdm-gtk',
  'echo "(以上为空即表示已登录桌面)"'
], 90)

/* 2. 授权状态 ------------------------------------------------------ */
remote('2. X 授权状态', [
  'echo "~/.Xauthority:"',
  'ls -la $HOME/.Xauthority',
  'echo',
  'echo "cookie 内容:"',
  'xauth -f $HOME/.Xauthority list',
  'echo',
  'echo "Xorg 使用的 auth 文件:"',
  'ps -eo args | grep Xorg | head -1',
  'echo',
  'echo "实测连接 X:（1=可连 0=不可连）"',
  'DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority xdpyinfo >/dev/null 2>&1',
  'echo "result=$?"',
  'echo',
  'echo "错误信息（若失败）:"',
  'DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority xdpyinfo 2>&1 | head -1'
], 60)

/* 3. 会话列表 ------------------------------------------------------ */
remote('3. 会话列表', [
  'loginctl list-sessions',
  'echo',
  'who'
], 60)

/* 4. 运行中的组件 -------------------------------------------------- */
remote('4. 看板 / 服务 / 光标', [
  'echo "数据服务:"',
  'pgrep -af serve.js',
  'echo',
  'echo "看板 Firefox:"',
  'pgrep -af firefox',
  'echo',
  'echo "hide-cursor 进程（一次性模式无进程属正常）:"',
  'pgrep -af hide-cursor',
  'echo',
  'echo "安装目录 ' + DIR + '/linux:"',
  'ls -1 ' + DIR + '/linux',
  'echo',
  'echo "自启动项:"',
  'ls -1 $HOME/.config/autostart/'
], 60)

if (askpass) { fs.unlinkSync(askpass) }
console.log('\n完成。')
