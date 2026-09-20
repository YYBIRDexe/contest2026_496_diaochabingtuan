/**
 * 验证 E5 演示版：点「开始巡检」后，几个时间点各截一张图
 *
 * 关键点 1：截图尺寸用 **1920x1080** —— 与 E5 触控屏实际分辨率一致。
 *           之前用 720x1280 验，漏掉了「横屏下被挤成窄柱」这个只有真机才暴露的问题。
 * 关键点 2：headless 下用 --virtual-time-budget 推进虚拟时间，
 *           这样 setTimeout / Date.now 都会被快进，能在几秒内跑完 9 秒的演示序列。
 * 关键点 3：触发方式用 __demo.run() —— 它与按钮 onclick 调的是同一个 demoRun()。
 *
 * 用法：node tools/verify-demo.js
 * 产物：build/shots/demo-{0-start,1-dispatch,2-map-running,3-blocked,4-records}.png
 */
const fs = require('fs')
const path = require('path')
const os = require('os')
const { execFileSync } = require('child_process')

const ROOT = path.resolve(__dirname, '..')
const BUILD = path.join(ROOT, 'build')
const SHOTS = path.join(BUILD, 'shots')
const DEMO = path.join(BUILD, 'demo-e5.html')

const BROWSER = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
].filter(function (p) { return fs.existsSync(p) })[0]

if (!BROWSER) { console.log('找不到 Edge/Chrome'); process.exit(1) }
if (!fs.existsSync(DEMO)) { console.log('先跑 node tools/build-demo-e5.js'); process.exit(1) }

const raw = fs.readFileSync(DEMO, 'utf8')
const TAIL = '</body></html>'
if (raw.indexOf(TAIL) < 0) { console.log('demo-e5.html 结构异常'); process.exit(1) }
const base = raw.slice(0, raw.lastIndexOf(TAIL))

/** 每个采样点：{名称, 虚拟时间预算(ms), 触发脚本} */
const POINTS = [
  { name: '0-start', budget: 2500, drive: '' },
  { name: '1-dispatch', budget: 2400, drive: '__demo.run();' },
  { name: '2-map-running', budget: 3100, drive: '__demo.run();' },
  { name: '3-blocked', budget: 5600, drive: '__demo.run();' },
  { name: '4-records', budget: 11000, drive: '__demo.run();' }
]

/* 与 E5 触控屏一致的分辨率（横屏 1920x1080） */
const VIEW = '1920,1080'

fs.mkdirSync(SHOTS, { recursive: true })

POINTS.forEach(function (p) {
  const file = path.join(BUILD, 'demo-' + p.name + '.html')
  fs.writeFileSync(file, base +
    '<script>window.addEventListener("load",function(){' + p.drive + '});</script>' + TAIL, 'utf8')
  const png = path.join(SHOTS, 'demo-' + p.name + '.png')
  if (fs.existsSync(png)) { fs.unlinkSync(png) }
  execFileSync(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
    '--hide-scrollbars',
    '--user-data-dir=' + path.join(os.tmpdir(), 'vg-demo-' + p.name),
    '--window-size=' + VIEW,
    '--virtual-time-budget=' + p.budget,
    '--screenshot=' + png,
    'file:///' + file.replace(/\\/g, '/')
  ], { stdio: ['ignore', 'pipe', 'pipe'] })
  const size = fs.existsSync(png) ? fs.statSync(png).size : 0
  console.log((size > 0 ? 'ok  ' : 'FAIL') + '  demo-' + p.name + '.png  ' +
    (size / 1024).toFixed(1) + ' KB')
})

console.log('\n截图目录：' + SHOTS + '   （尺寸 ' + VIEW + '，与 E5 屏一致）')
