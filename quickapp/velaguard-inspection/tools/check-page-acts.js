/**
 * 页面契约检查：模板里用到的每个 data-act 都必须在该页面的 act 表里有实现
 *
 * 用法：node tools/check-page-acts.js
 *
 * 为什么要有这个：
 *   外壳是按 `data-act` 去查**当前页面**的 act 表来派发的。
 *   模板里写了 `data-act="go"` 而 act 表里没有 `go`，结果就是
 *   **按钮点了完全没反应，而且渲染测试一点都看不出来**
 *   （DOM 里 data-act 属性都在，页面看着完全正常）。
 *   首页磁贴跳转就是这么坏的，直到做"真实点击"测试才暴露。
 *   这类错误用静态检查一次就能全挡住，比等运行时发现划算得多。
 */
const fs = require('fs')
const path = require('path')
const esm = require('./esm.js')

const ROOT = path.resolve(__dirname, '..')
const PAGES = path.join(ROOT, 'src', 'pages')

let pass = 0
let fail = 0
function ok(name, cond, extra) {
  if (cond) { pass += 1; console.log('  ok   ' + name) } else {
    fail += 1; console.log('  FAIL ' + name + (extra ? '  → ' + extra : ''))
  }
}

console.log('=== 页面契约检查（模板动作 ↔ act 实现）===')
console.log('')

const files = fs.readdirSync(PAGES).filter(function (f) { return /\.js$/.test(f) })

/* 载入器基准设在 src/：页面里的 import 写的是 '../common/data.js'，
   所以必须从 src 起解析，不能从 pages 起 */
const req = esm.makeLoader(path.join(ROOT, 'src'))

files.forEach(function (f) {
  const name = f.replace(/\.js$/, '')
  const mod = req.value('./pages/' + f)
  const tpl = mod.tpl || ''
  const act = mod.act || {}

  /* 模板里出现的所有 data-act 值 */
  const used = {}
  const re = /data-act="([A-Za-z0-9_]+)"/g
  let m
  while ((m = re.exec(tpl)) !== null) {
    used[m[1]] = true
  }
  const usedList = Object.keys(used).sort()
  const missing = usedList.filter(function (a) { return typeof act[a] !== 'function' })

  /* 反向：act 里实现了但模板没用到（不一定是错，但值得看一眼） */
  const unused = Object.keys(act).filter(function (a) { return !used[a] })

  ok(name + '：模板用到的 ' + usedList.length + ' 个动作都有实现',
    missing.length === 0,
    missing.length ? '缺实现：' + missing.join(', ') : '')

  /* 每个页面都必须能回到桌面或跳页，否则会变成"死页" */
  const canNavigate = typeof act.go === 'function' || typeof act.back === 'function'
  ok(name + '：有导航动作（go 或 back）', canNavigate,
    canNavigate ? '' : '既没有 go 也没有 back，进去就出不来')

  if (unused.length) {
    console.log('       提示：act 里未被模板使用的动作 → ' + unused.join(', '))
  }
})

/* 页面注册与 manifest 的入口一致性 */
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'src', 'manifest.json'), 'utf8'))
ok('manifest 入口指向 index', !!manifest.router.pages.index)
ok('manifest 包名已定', manifest.package === 'com.velaguard.inspection',
  manifest.package)
ok('manifest 设计尺寸 720×1280',
  manifest.config.designWidth === 720 && manifest.config.designHeight === 1280,
  manifest.config.designWidth + '×' + manifest.config.designHeight)
ok('manifest 声明了 velaclaw 能力',
  (manifest.features || []).some(function (x) { return x.name === 'system.velaclaw' }))

console.log('')
console.log('页面数：' + files.length)
console.log('结果：' + pass + ' 通过，' + fail + ' 失败')
process.exit(fail === 0 ? 0 : 1)
