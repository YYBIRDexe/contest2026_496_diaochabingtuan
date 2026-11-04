/**
 * 一键跑全部测试与自检
 *
 * 用法：node tools/run-tests.js
 *
 * 顺序刻意如此：先纯逻辑、再模板、再界面、最后产物自检。
 * 前面的挂了，后面的错误信息会被淹没——所以**第一个失败就停**，除非加 --keep-going。
 */
const path = require('path')
const { execFileSync } = require('child_process')

const ROOT = path.resolve(__dirname, '..')
const KEEP = process.argv.indexOf('--keep-going') >= 0

const STEPS = [
  { name: '端侧预设表 + 任务状态机', cmd: 'test-store.js', hint: '方案二功能一~四的逻辑' },
  { name: '模板引擎', cmd: 'test-tpl.js', hint: '七个视图共用的渲染层' },
  { name: '页面契约（模板动作 ↔ act 实现）', cmd: 'check-page-acts.js', hint: '防"按钮点了没反应"' },
  { name: '路线合规校验', cmd: 'gen-waypoints.js', args: ['--check'], hint: '单步 ≤1m / 单条 ≤3.5m / 在图内' },
  { name: '界面冒烟（真实浏览器 + 真实点击）', cmd: 'test-ui.js', hint: '渲染 / 交互 / 地图动画' },
  { name: 'openvela 产物生成', cmd: 'build-openvela.js', hint: 'app.ux + manifest.json' },
  { name: 'openvela 产物自检', cmd: 'check-openvela-app.js', hint: '语法 / 视图 / 地图' }
]

let failed = 0
const results = []

STEPS.forEach(function (s, i) {
  const label = '[' + (i + 1) + '/' + STEPS.length + '] ' + s.name
  console.log('')
  console.log('================ ' + label + ' ================')
  console.log('（' + s.hint + '）')
  console.log('')
  const args = [path.join(__dirname, s.cmd)].concat(s.args || [])
  let code = 0
  let out = ''
  try {
    out = execFileSync(process.execPath, args, {
      encoding: 'utf8',
      maxBuffer: 40 * 1024 * 1024,
      stdio: ['ignore', 'pipe', 'pipe']
    })
  } catch (e) {
    code = e.status === undefined ? 1 : e.status
    out = (e.stdout || '') + (e.stderr || '')
  }
  process.stdout.write(out)
  results.push({ name: s.name, code: code })
  if (code !== 0) {
    failed += 1
    console.log('')
    console.log('❌ 这一步失败：' + s.name)
    if (!KEEP) {
      console.log('（已停止；加 --keep-going 可跑完全部）')
    }
  }
  return code === 0 || KEEP
})

console.log('')
console.log('================ 汇总 ================')
results.forEach(function (r) {
  console.log((r.code === 0 ? '  ✅ ' : '  ❌ ') + r.name)
})
console.log('')
if (failed === 0) {
  console.log('全部通过。')
  console.log('')
  console.log('下一步：')
  console.log('  · 想在 Windows 上看界面：node tools/preview-server.js  → http://127.0.0.1:8177')
  console.log('  · 想部署到模拟器：见 docs/部署到openvela.md 与 docs/模拟器验证命令单.md')
} else {
  console.log(failed + ' 步失败。')
}
process.exit(failed === 0 ? 0 : 1)
