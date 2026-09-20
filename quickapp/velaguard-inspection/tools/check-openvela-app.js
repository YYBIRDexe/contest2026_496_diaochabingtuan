/**
 * 生成产物自检：把 build/openvela-app/app.ux 的脚本部分当 JS 编译一遍
 *
 * 用法：node tools/check-openvela-app.js
 *
 * 为什么需要：app.ux 是"模板 + 内联 bundle"拼出来的，
 * 拼接最典型的失败就是括号不闭合、残留 import/export、占位符没替换。
 * 这些在浏览器预览里**完全测不到**（那份走的是另一条宿主），
 * 所以必须单独自检一次，否则只有到模拟器上才发现是白屏。
 */
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const ROOT = path.resolve(__dirname, '..')
const APP = path.join(ROOT, 'build', 'openvela-app', 'app.ux')

let pass = 0
let fail = 0
function ok(name, cond, extra) {
  if (cond) { pass += 1; console.log('  ok   ' + name) } else {
    fail += 1; console.log('  FAIL ' + name + (extra ? '  → ' + extra : ''))
  }
}

console.log('=== openvela 应用产物自检 ===')

if (!fs.existsSync(APP)) {
  console.log('  FAIL 找不到 ' + APP + '（先跑 tools/build-openvela.js）')
  process.exit(1)
}

const ux = fs.readFileSync(APP, 'utf8')

ok('文件非空', ux.length > 10000, ux.length + ' 字节')
ok('占位符已替换', ux.indexOf('__VELAGUARD_BUNDLE__') < 0)
ok('声明了 velaclaw 依赖', ux.indexOf("import velaclaw from '@system.velaclaw'") >= 0)
ok('有 manifest 里的包名对应入口', ux.indexOf('export default {') >= 0)
ok('暴露了 dispatch 供 onclick 调用', ux.indexOf('globalThis.dispatch') >= 0)
ok('bindActions 会把 data-act 改写成 onclick',
  ux.indexOf('onclick="dispatch(') >= 0)

/* 脚本体里不应残留模块语法（import/export 会直接是语法错误） */
const stray = ux.split('\n').map(function (l, i) {
  if (/^\s*(import|export)\s/.test(l) && l.indexOf("@system.velaclaw") < 0 &&
      l.indexOf('export default {') < 0) {
    return (i + 1) + ': ' + l.trim().slice(0, 70)
  }
  return null
}).filter(Boolean)
ok('bundle 内无残留 import/export', stray.length === 0, stray.join(' | '))

/* 把 import 去掉、export default 换成 module.exports 后，整段当 JS 编译。
   模块级已经求值过 bundle，所以这里能直接读到 VelaGuard 句柄。 */
const body = ux.replace(/^import velaclaw from '@system\.velaclaw'\s*$/m, '')
  .replace(/^export default /m, 'module.exports = ')
const sandbox = {
  module: { exports: {} },
  setTimeout: setTimeout,
  clearTimeout: clearTimeout,
  setInterval: setInterval,
  clearInterval: clearInterval,
  Date: Date,
  Math: Math,
  JSON: JSON,
  Promise: Promise,
  Object: Object,
  Array: Array,
  String: String,
  Number: Number,
  Error: Error,
  RegExp: RegExp,
  console: console,
  globalThis: null
}
sandbox.globalThis = sandbox

try {
  new vm.Script(body, { filename: 'app.ux' })
  ok('脚本部分语法正确', true)
} catch (e) {
  ok('脚本部分语法正确', false, e.message)
  const m = /app\.ux:(\d+)/.exec(e.stack || '')
  if (m) {
    const n = parseInt(m[1], 10)
    const ls = body.split('\n')
    for (let i = Math.max(0, n - 4); i < Math.min(ls.length, n + 2); i += 1) {
      console.log((i + 1 === n ? '     >> ' : '        ') + (i + 1) + ': ' + ls[i].slice(0, 100))
    }
  }
  console.log('')
  console.log('结果：' + pass + ' 通过，' + fail + ' 失败')
  process.exit(1)
}

/* 进一步：真的把 bundle 跑起来，确认 VelaGuard 句柄与页面都在
   （不调用 app.ux 里的 onInit，那需要快应用运行时） */
try {
  vm.createContext(sandbox)
  vm.runInContext(body, sandbox, { filename: 'app.ux' })
  const VG = sandbox.globalThis.VelaGuard || sandbox.VelaGuard
  ok('运行后 VelaGuard 句柄存在', !!VG)
  if (VG) {
    const pageNames = Object.keys(VG.pages)
    /* 七个视图：Home / Dispatch / Map / Zones / Records / Voice / System */
    ok('七个视图都注册了', pageNames.length === 7, pageNames.join(','))
    ok('页面名齐全',
      ['Home', 'Dispatch', 'Map', 'Zones', 'Records', 'System', 'Voice']
        .filter(function (n) { return pageNames.indexOf(n) < 0 }).length === 0,
      pageNames.join(','))
    const tpl = VG.mod('tpl')
    let renderOk = true
    let detail = ''
    pageNames.forEach(function (n) {
      const p = VG.pages[n]
      const errs = []
      const html = tpl.render(p.tpl, p.data({ clock: 'T', allRouteLength: 10.3, __errors: errs }))
      if (html.indexOf('{{') >= 0) { renderOk = false; detail += n + ' 残留模板标签; ' }
      if (errs.length) { renderOk = false; detail += n + ' 求值错误 ' + errs.length + ' 处; ' }
      if (html.length < 500) { renderOk = false; detail += n + ' 渲染过短; ' }
    })
    ok('七个视图在 openvela 产物里都能渲染', renderOk, detail)
    ok('终态：地图渲染出四条路线',
      (function () {
        const m = VG.mod('map')
        const svg = m.renderMap({ zones: VG.store.zoneStates(), tasks: VG.store.vehiclePositions(), width: 680, height: 460 })
        return (svg.match(/<polyline/g) || []).length === 4
      })())
  }
} catch (e) {
  ok('运行 bundle 不抛错', false, e.message)
}

console.log('')
console.log('结果：' + pass + ' 通过，' + fail + ' 失败')
process.exit(fail === 0 ? 0 : 1)
