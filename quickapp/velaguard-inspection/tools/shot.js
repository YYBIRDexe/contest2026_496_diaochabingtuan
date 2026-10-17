/**
 * 截图工具：把六个页面各截一张 PNG，供肉眼核对与写文档用
 *
 * 用法：node tools/shot.js
 * 产物：build/shots/{Home,Dispatch,Map,Zones,Records,System,Voice}.png
 */
const fs = require('fs')
const path = require('path')
const os = require('os')
const { execFileSync } = require('child_process')

const ROOT = path.resolve(__dirname, '..')
const BUILD = path.join(ROOT, 'build')
const SHOTS = path.join(BUILD, 'shots')
const HOST_JS = fs.readFileSync(path.join(__dirname, 'host-browser.js'), 'utf8')

const BROWSER = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
].filter(function (p) { return fs.existsSync(p) })[0]

if (!BROWSER) {
  console.log('找不到 Edge/Chrome，跳过截图')
  process.exit(0)
}

execFileSync(process.execPath, [path.join(__dirname, 'bundle.js'), '--target', 'browser',
  '--out', path.join(BUILD, 'bundle.browser.js')], { stdio: 'pipe' })
const bundle = fs.readFileSync(path.join(BUILD, 'bundle.browser.js'), 'utf8')

/** 每个页面截一张；Map 与 Records 额外先跑一轮巡检，让画面有内容 */
const SHOT_LIST = [
  { page: 'Home', name: 'Home', drive: '' },
  {
    page: 'Home',
    name: 'Home-running',
    drive: 'VG.store.startRound(); for (var i=0;i<14;i++) VG.store.tick(0.25);'
  },
  {
    page: 'Dispatch',
    name: 'Dispatch',
    drive: 'VG.store.startRound(); for (var i=0;i<10;i++) VG.store.tick(0.25);' +
      'VG.store.injectObstacle("Z2");'
  },
  {
    page: 'Map',
    name: 'Map',
    drive: 'VG.store.startRound(); for (var i=0;i<26;i++) VG.store.tick(0.25);'
  },
  { page: 'Zones', name: 'Zones', drive: '' },
  {
    page: 'Records',
    name: 'Records',
    drive: 'VG.store.startRound(); for (var i=0;i<60;i++) VG.store.tick(0.25);' +
      'VG.store.closeRound(); VG.store.startRound(); for (var i=0;i<8;i++) VG.store.tick(0.25);'
  },
  {
    page: 'Voice',
    name: 'Voice',
    drive: 'VG.agent.ask("现在四台车都在线吗，电量多少");' +
      'VG.agent.ask("现在哪些区域没查完");'
  },
  { page: 'System', name: 'System', drive: '' }
]

function pageHtml(drive) {
  const drv = drive
    ? '(function(){var VG=window.VelaGuard;' + drive +
      'window.__vg.render();window.__vg.navigate("__PAGE__")})();'
    : '(function(){window.__vg.navigate("__PAGE__")})();'
  return '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">' +
    '<style>body{margin:0;background:#0b1220}</style></head><body>' +
    '<div id="app"></div>' +
    '<script>' + bundle + '</script>' +
    '<script>' + HOST_JS + '</script>' +
    '<script>' + drv.replace(/__PAGE__/g, 'PAGE_PLACEHOLDER') + '</script>' +
    '</body></html>'
}

fs.mkdirSync(SHOTS, { recursive: true })

SHOT_LIST.forEach(function (s) {
  const html = pageHtml(s.drive).replace(/PAGE_PLACEHOLDER/g, s.page)
  const file = path.join(BUILD, 'shot-' + s.name + '.html')
  fs.writeFileSync(file, html, 'utf8')
  const png = path.join(SHOTS, s.name + '.png')
  execFileSync(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
    '--hide-scrollbars',
    '--user-data-dir=' + path.join(os.tmpdir(), 'vg-shot-' + s.name),
    '--window-size=720,1280',
    '--virtual-time-budget=6000',
    '--screenshot=' + png,
    'file:///' + file.replace(/\\/g, '/')
  ], { stdio: ['ignore', 'pipe', 'pipe'] })
  const size = fs.existsSync(png) ? fs.statSync(png).size : 0
  console.log((size > 0 ? 'ok  ' : 'FAIL') + '  ' + s.name + '.png  ' +
    (size / 1024).toFixed(1) + ' KB')
})

console.log('')
console.log('截图目录：' + SHOTS)
