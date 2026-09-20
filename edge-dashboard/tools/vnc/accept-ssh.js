'use strict'

/**
 * M1 SSH 验收：上传工程 → 远端体检 → 抓真实渲染截图回传。
 *
 * 凭据从环境变量读取（不写进命令行，避免出现在进程列表）：
 *   $env:M1_HOST='192.168.1.104'
 *   $env:M1_USER='sunrise'
 *   $env:M1_PASS='sunrise'
 *   node tools/vnc/accept-ssh.js            # 只体检
 *   node tools/vnc/accept-ssh.js --deploy   # 体检 + 上传 + 抓图
 *
 * 可选：
 *   M1_DIR   远端安装目录（默认 ~/velaguard）
 *   M1_PORT  看板端口（默认 8123）
 */

const fs = require('fs')
const path = require('path')
const os = require('os')
const { spawnSync } = require('child_process')

const HOST = process.env.M1_HOST || '192.168.1.104'
const USER = process.env.M1_USER || 'sunrise'
const PASS = process.env.M1_PASS || ''
// scp 不解析 ~ 或 $HOME，所以用绝对路径；可用 M1_DIR 覆盖
let DIR = process.env.M1_DIR || '/home/' + USER + '/velaguard'
const PORT = process.env.M1_PORT || '8123'
const DEPLOY = process.argv.indexOf('--deploy') >= 0

const ROOT = path.join(__dirname, '..', '..')
const SHOT_DIR = path.join(ROOT, 'preview', 'm1')

/* ---------- askpass：密码经环境变量注入，不落到命令行 ---------- */
let askpassPath = null
function ensureAskpass() {
  if (askpassPath || !PASS) {
    return
  }
  askpassPath = path.join(os.tmpdir(), 'vg-askpass-' + Date.now() + '.cmd')
  fs.writeFileSync(askpassPath, '@echo off\r\necho %VG_SSH_PASS%\r\n', 'utf8')
}

function sshOpts() {
  const o = [
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'UserKnownHostsFile=/dev/null',
    '-o', 'ConnectTimeout=10',
    '-o', 'LogLevel=ERROR'
  ]
  if (PASS) {
    ensureAskpass()
    o.push('-o', 'PreferredAuthentications=password,keyboard-interactive')
    o.push('-o', 'PubkeyAuthentication=no')
    o.push('-o', 'NumberOfPasswordPrompts=1')
  }
  return o
}

function runEnv() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    e.VG_SSH_PASS = PASS
    e.SSH_ASKPASS = askpassPath
    e.SSH_ASKPASS_REQUIRE = 'force'
    e.DISPLAY = e.DISPLAY || 'localhost:0'
  }
  return e
}

function run(cmd, args, timeout) {
  const r = spawnSync(cmd, args, {
    encoding: 'utf8',
    timeout: timeout || 240000,
    env: runEnv(),
    maxBuffer: 32 * 1024 * 1024
  })
  return {
    ok: r.status === 0,
    status: r.status,
    stdout: String(r.stdout || ''),
    stderr: String(r.stderr || ''),
    error: r.error
  }
}

function ssh(remoteCmd, timeout) {
  return run('ssh', sshOpts().concat([USER + '@' + HOST, remoteCmd]), timeout)
}

function banner(t) {
  console.log('\n' + '='.repeat(66))
  console.log(t)
  console.log('='.repeat(66))
}

/* ------------------------------------------------------------------ */
function main() {
  banner('1. SSH 连通性')
  const ping = ssh('echo __OK__; hostname; uname -srm; id -un')
  if (!ping.ok) {
    console.error('SSH 失败：' + (ping.stderr.trim() || ping.error || ('exit ' + ping.status)))
    process.exit(1)
  }
  console.log(ping.stdout.trim().split('\n').map(function (l) { return '  ' + l }).join('\n'))

  /* ---------------- 2. 体检 ---------------- */
  banner('2. 环境体检')
  const probe = [
    'echo "--- OS ---"',
    'cat /etc/os-release 2>/dev/null | grep -E "^(PRETTY_NAME|VERSION)=" ',
    'echo "--- ARCH/RAM ---"',
    'uname -m; free -h 2>/dev/null | awk "/^Mem:/{print \\$2\\" total, \\"\\$7\\" available\\"}"',
    'echo "--- DISPLAY ---"',
    'echo "DISPLAY=$DISPLAY WAYLAND=$WAYLAND_DISPLAY"',
    'echo "--- SCREEN ---"',
    'xrandr 2>/dev/null | grep -E " connected|^\\s+[0-9]+x[0-9]+" | head -10 || echo "xrandr unavailable"',
    'echo "--- BROWSER ---"',
    'for b in chromium chromium-browser google-chrome google-chrome-stable firefox epiphany-browser epiphany midori falkon qutebrowser; do command -v $b >/dev/null 2>&1 && echo "FOUND $b: $($b --version 2>/dev/null | head -1)"; done',
    'echo "(end browser scan)"',
    'echo "--- ELECTRON / VSCODE ---"',
    'command -v code >/dev/null 2>&1 && echo "code: $(command -v code)" || echo "code: not in PATH"',
    'ls -d /usr/share/code 2>/dev/null && echo "/usr/share/code exists"',
    'ls /usr/share/code/resources/app/node_modules/electron/dist/electron 2>/dev/null && echo "electron binary present"',
    'echo "--- PYTHON ---"',
    'python3 --version 2>/dev/null || echo "no python3"',
    'python3 -c "import gi; gi.require_version(chr(71)+chr(116)+chr(107), chr(51)+chr(46)+chr(48)); print(\\"gtk3 ok\\")" 2>/dev/null || echo "gtk3 python binding: no"',
    'echo "--- NODE ---"',
    'command -v node >/dev/null 2>&1 && node --version || echo "no node"',
    'echo "--- NET ---"',
    'timeout 5 curl -s -o /dev/null -w "apt-repo-http=%{http_code}\\n" http://archive.ubuntu.com 2>/dev/null || echo "no internet (archive.ubuntu.com unreachable)"',
    'echo "--- APP DIR ---"',
    'ls -la $HOME/velaguard 2>/dev/null | head -5 || echo "no ~/velaguard"'
  ].join('; ')

  const pr = ssh(probe)
  console.log(pr.stdout.trim() || '(no output)')
  if (pr.stderr.trim()) {
    console.log('--- stderr ---\n' + pr.stderr.trim())
  }

  /* ---------------- 3. 部署 ---------------- */
  if (!DEPLOY) {
    banner('完成（未部署；加 --deploy 参数可上传并抓图）')
    return
  }

  banner('3. 上传工程（经 ASCII 暂存目录，避免中文路径）')
  const stage = path.join(os.tmpdir(), 'vg-stage')
  fs.rmSync(stage, { recursive: true, force: true })
  fs.mkdirSync(path.join(stage, 'linux'), { recursive: true })
  fs.mkdirSync(path.join(stage, 'preview'), { recursive: true })
  fs.mkdirSync(path.join(stage, 'data'), { recursive: true })

  const stageMap = [
    ['preview/index.html', 'preview/index.html'],
    ['data/README.md', 'data/README.md'],
    ['linux/accept.sh', 'linux/accept.sh']
  ]
  for (const [src, dst] of stageMap) {
    const s = path.join(ROOT, src)
    if (fs.existsSync(s)) {
      fs.copyFileSync(s, path.join(stage, dst))
    }
  }
  // tools 里只需要服务端脚本
  fs.mkdirSync(path.join(stage, 'tools'), { recursive: true })
  for (const f of ['serve.js', 'simulate-m1.js']) {
    const s = path.join(ROOT, 'tools', f)
    if (fs.existsSync(s)) {
      fs.copyFileSync(s, path.join(stage, 'tools', f))
    }
  }
  console.log('  暂存目录：' + stage)

  ssh('mkdir -p ' + DIR + '/preview ' + DIR + '/tools ' + DIR + '/data ' + DIR + '/linux ' + DIR + '/shots')

  const scpBase = sshOpts()
  const r1 = run('scp', scpBase.concat(['-r', stage + '/.', USER + '@' + HOST + ':' + DIR + '/']))
  console.log('  ' + (r1.ok ? '✓ 上传完成' : '✗ 上传失败: ' + r1.stderr.trim()))

  /* ---------------- 4. 远端验收 ---------------- */
  banner('4. 远端体检与部署')
  const acc = ssh('chmod +x ' + DIR + '/linux/accept.sh && ' + DIR + '/linux/accept.sh ' + DIR)
  console.log(acc.stdout.trim() || '(no output)')
  if (acc.stderr.trim()) {
    console.log('--- stderr ---\n' + acc.stderr.trim())
  }

  /* ---------------- 5. 取回截图 ---------------- */
  banner('5. 取回截图')
  fs.mkdirSync(SHOT_DIR, { recursive: true })
  const r2 = run('scp', scpBase.concat([
    USER + '@' + HOST + ':' + DIR + '/shots/kiosk-1280x800.png',
    path.join(SHOT_DIR, 'kiosk-1280x800.png')
  ]))
  if (r2.ok && fs.existsSync(path.join(SHOT_DIR, 'kiosk-1280x800.png'))) {
    const p = path.join(SHOT_DIR, 'kiosk-1280x800.png')
    console.log('  ✓ ' + p + ' (' + fs.statSync(p).size + ' bytes)')
  } else {
    console.log('  ✗ 取回失败：' + (r2.stderr.trim() || '远端可能未生成截图'))
  }

  banner('完成')
}

main()
