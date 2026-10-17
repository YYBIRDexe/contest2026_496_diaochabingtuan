/**
 * 生成 openvela 侧的应用：build/app.ux + 公共样式
 *
 * 用法：node tools/build-openvela.js
 *
 * 产出（都在 build/openvela-app/ 下）：
 *   app.ux            入口页面（内联了打包产物）
 *   manifest.json     包名 com.velaguard.inspection，designWidth 720
 *   common/…          公共资源（样式在 app.ux 里内联，这里只放图标等）
 *
 * 部署方式见 docs/部署到openvela.md（unzip 成 /data/app/<包名>/ 后 vapp 启动）。
 */
const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

const ROOT = path.resolve(__dirname, '..')
const SRC = path.join(ROOT, 'src')
const OUT = path.join(ROOT, 'build', 'openvela-app')

/* ---------- 1. 先打 bundle（openvela 目标） ---------- */
const bundlePath = path.join(ROOT, 'build', 'velaguard.bundle.js')
execFileSync(process.execPath, [path.join(__dirname, 'bundle.js'),
  '--target', 'openvela', '--out', bundlePath], { stdio: 'inherit' })

let bundle = fs.readFileSync(bundlePath, 'utf8')

/* ---------- 2. 自检：产物里不能残留 import/export ---------- */
const problems = []
const lines = bundle.split('\n')
lines.forEach(function (l, i) {
  if (/^\s*(import|export)\s/.test(l)) {
    problems.push('第 ' + (i + 1) + ' 行残留模块语法：' + l.trim().slice(0, 80))
  }
})
if (problems.length) {
  console.error('打包产物自检失败：')
  problems.forEach(function (p) { console.error('  ' + p) })
  process.exit(1)
}

/* ---------- 3. 嵌入 app.ux 模板 ---------- */
const tmpl = fs.readFileSync(path.join(SRC, 'app.ux.tmpl'), 'utf8')
if (tmpl.indexOf('__VELAGUARD_BUNDLE__') < 0) {
  console.error('模板里找不到 __VELAGUARD_BUNDLE__ 占位符')
  process.exit(1)
}
/* 缩进对齐：bundle 位于模块顶层的 IIFE 里，补 2 个空格便于阅读 */
const indented = bundle.split('\n').map(function (l) {
  return l.length ? '  ' + l : l
}).join('\n')
const appUx = tmpl.replace('__VELAGUARD_BUNDLE__', indented)

/* ---------- 4. 写出 ---------- */
fs.mkdirSync(OUT, { recursive: true })
fs.writeFileSync(path.join(OUT, 'app.ux'), appUx, 'utf8')
fs.copyFileSync(path.join(SRC, 'manifest.json'), path.join(OUT, 'manifest.json'))

const files = []
function walk(d) {
  fs.readdirSync(d, { withFileTypes: true }).forEach(function (e) {
    const fp = path.join(d, e.name)
    if (e.isDirectory()) { walk(fp) } else {
      files.push({ rel: path.relative(OUT, fp), size: fs.statSync(fp).size })
    }
  })
}
walk(OUT)

console.log('')
console.log('=== openvela 应用已生成 ===')
console.log('输出目录：' + OUT)
files.forEach(function (f) {
  console.log('  ' + f.rel.padEnd(16) + (f.size / 1024).toFixed(1) + ' KB')
})
console.log('')
console.log('下一步：')
console.log('  1) 确认固件菜单已开：CONFIG_QUICKAPP=y / CONFIG_QUICKAPP_VAPP=y /')
console.log('     CONFIG_INTERPRETERS_QUICKJS=y / CONFIG_LIB_YOGA=y /')
console.log('     CONFIG_GRAPHICS_LVGL=y / CONFIG_FEATURE_FRAMEWORK=y /')
console.log('     CONFIG_FEATURE_SYSTEM_VELACLAW=y / CONFIG_EXAMPLES_AI_AGENT_VELA=y')
console.log('  2) 部署：见 docs/部署到openvela.md（unzip → adb push → vapp 启动）')
