/**
 * 界面冒烟测试：在无头浏览器里真跑一遍，断言渲染结果
 *
 * 用法：node tools/test-ui.js
 *
 * 为什么必须真跑浏览器：
 *   模板引擎、宿主、页面这三层各自单测过，但它们**合起来**能不能渲染出
 *   正确的东西、点了按钮有没有反应，只有真跑一次才知道。
 *   之前那套界面就吃过"看起来对、实际白屏"的亏（M1 上预览整屏空白）。
 *
 * 做法：
 *   1. 打 bundle + 拼出与预览服务相同的单文件 HTML，落到 build/preview.html
 *   2. 用 Edge/Chrome 的 --headless --dump-dom 跑一遍，取回渲染后的 DOM
 *   3. 断言关键内容；再跑一遍带脚本的版本，模拟点击与推进，断言状态变化
 */
const fs = require('fs')
const path = require('path')
const os = require('os')
const { execFileSync } = require('child_process')

const ROOT = path.resolve(__dirname, '..')
const BUILD = path.join(ROOT, 'build')

/* 宿主是真正的 .js 文件，直接内联 */
const HOST_JS = fs.readFileSync(path.join(__dirname, 'host-browser.js'), 'utf8')

let pass = 0
let fail = 0
function ok(name, cond, extra) {
  if (cond) { pass += 1; console.log('  ok   ' + name) } else {
    fail += 1; console.log('  FAIL ' + name + (extra ? '  → ' + extra : ''))
  }
}

function findBrowser() {
  const cands = [
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'
  ]
  for (let i = 0; i < cands.length; i += 1) {
    if (fs.existsSync(cands[i])) { return cands[i] }
  }
  return null
}

function buildPage(extraScript) {
  execFileSync(process.execPath, [path.join(__dirname, 'bundle.js'), '--target', 'browser',
    '--out', path.join(BUILD, 'bundle.browser.js')], { stdio: 'pipe' })
  const bundle = fs.readFileSync(path.join(BUILD, 'bundle.browser.js'), 'utf8')
  return '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">' +
    '<title>VelaGuard 快应用预览</title></head><body>' +
    '<div id="app"></div>' +
    '<script>' + bundle + '</script>' +
    '<script>' + HOST_JS + '</script>' +
    (extraScript ? '<script>' + extraScript + '</script>' : '') +
    '</body></html>'
}

/** 取出 #app 容器里的渲染结果。
 *  注意：不能对整个 DOM 断言"没有 {{ }}"——bundle 自己的注释里就写着模板语法，
 *  那样会永远误报。只看真正渲染出来的那一块。 */
function appHtml(dom) {
  const i = dom.indexOf('<div id="app">')
  if (i < 0) {
    return ''
  }
  const start = i + '<div id="app">'.length
  const end = dom.indexOf('<script', start)
  return dom.slice(start, end < 0 ? dom.length : end)
}

/** 用无头浏览器跑一个 HTML 文件，返回渲染后的 DOM */
function dumpDom(browser, html, tag) {
  const file = path.join(BUILD, 'ui-' + tag + '.html')
  fs.mkdirSync(BUILD, { recursive: true })
  fs.writeFileSync(file, html, 'utf8')
  const profile = path.join(os.tmpdir(), 'vg-ui-test-' + tag)
  const out = execFileSync(browser, [
    '--headless=new',
    '--disable-gpu',
    '--no-sandbox',
    '--no-first-run',
    '--disable-extensions',
    '--user-data-dir=' + profile,
    '--virtual-time-budget=6000',
    '--dump-dom',
    'file:///' + file.replace(/\\/g, '/')
  ], { encoding: 'utf8', maxBuffer: 40 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] })
  return out
}

/* ================================================================== */
const browser = findBrowser()
if (!browser) {
  console.log('找不到 Edge/Chrome，跳过界面测试')
  process.exit(0)
}
console.log('=== 界面冒烟测试 ===')
console.log('浏览器：' + browser)
console.log('')

/* ---------- 第一轮：桌面页应能渲染 ---------- */
console.log('[1] 桌面页渲染')
const domHome = dumpDom(browser, buildPage(''), 'home')
const viewHome = appHtml(domHome)
ok('页面有内容（不是白屏）', viewHome.length > 3000, viewHome.length + ' 字节')
ok('状态栏时间已渲染', /20\d\d-\d\d-\d\d \d\d:\d\d:\d\d/.test(viewHome),
  (viewHome.match(/20\d\d-\d\d-\d\d \d\d:\d\d:\d\d/) || ['无'])[0])
ok('标题出现', viewHome.indexOf('VelaGuard 巡检桌面') >= 0)
ok('六个应用磁贴都在',
  viewHome.indexOf('巡检调度台') >= 0 && viewHome.indexOf('地图与路线') >= 0 &&
  viewHome.indexOf('区域与任务') >= 0 && viewHome.indexOf('巡检记录') >= 0 &&
  viewHome.indexOf('语音助手') >= 0 && viewHome.indexOf('系统与链路') >= 0)
ok('概览卡有汇总文案', viewHome.indexOf('尚未开始巡检') >= 0)
ok('底部快捷坞有主按钮', viewHome.indexOf('开始本轮巡检') >= 0)
ok('渲染结果没有残留未求值的 {{ }}',
  viewHome.indexOf('{{') < 0, (viewHome.match(/\{\{[^}]{0,40}/) || [''])[0])
ok('没有出现 undefined',
  viewHome.indexOf('undefined') < 0, viewHome.slice(Math.max(0, viewHome.indexOf('undefined') - 60), viewHome.indexOf('undefined') + 60))

/* ---------- 第二轮：脚本驱动——开始巡检 + 推进 + 切页 ---------- */
console.log('')
console.log('[2] 交互：开始巡检 → 推进路线 → 切到地图页')
const driver = [
  '(function () {',
  '  var VG = window.VelaGuard;',
  '  var app = window.__vg;',
  '  /* 直接从干净状态开始一轮，再切到地图页 */',
  '  VG.store.resetCars();',
  '  var r = VG.store.startRound();',
  '  /* 推进 12 秒（0.25s 一步），让四条路线都跑完 */',
  '  for (var i = 0; i < 48; i++) { VG.store.tick(0.25); }',
  '  app.navigate("Map");',
  '  var snap = VG.store.snapshot();',
  '  window.__probe = {',
  '    round: snap.round,',
  '    started: r.started,',
  '    counts: snap.summary.counts,',
  '    line: snap.summaryLine,',
  '    positions: VG.store.vehiclePositions(),',
  '    html: document.getElementById("app").innerHTML.length',
  '  };',
  '  document.title = "PROBE:" + JSON.stringify(window.__probe);',
  '})();'
].join('\n')

const domMap = dumpDom(browser, buildPage(driver), 'map')
const probeMatch = /PROBE:(\{[\s\S]*?\})<\/title>/.exec(domMap)
ok('驱动脚本产出了探针数据', !!probeMatch, probeMatch ? '' : '未找到 PROBE')
let probe = null
if (probeMatch) {
  try {
    probe = JSON.parse(probeMatch[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&'))
  } catch (e) {
    ok('探针 JSON 可解析', false, e.message + ' :: ' + probeMatch[1].slice(0, 200))
  }
}
if (probe) {
  ok('第 1 轮已开始', probe.round === 1, 'round=' + probe.round)
  ok('四个区域全部派单成功', probe.started === 4, 'started=' + probe.started)
  ok('推进 12 秒后四区都已完成', probe.counts.done === 4, JSON.stringify(probe.counts))
  ok('每条路线都有车辆位置', Object.keys(probe.positions).length === 4,
    Object.keys(probe.positions).join(','))
  const z1 = probe.positions.Z1
  ok('Z1 车已到路线终点附近',
    z1 && Math.abs(z1.x - (-2.60)) < 0.35 && Math.abs(z1.y - 5.00) < 0.35,
    z1 ? '(' + z1.x.toFixed(2) + ', ' + z1.y.toFixed(2) + ')' : '无')
  const viewMap = appHtml(domMap)
  ok('地图页渲染出了 SVG', viewMap.indexOf('<svg class="mapsvg"') >= 0)
  ok('地图上画了四条路线',
    (viewMap.match(/<polyline/g) || []).length >= 4,
    'polyline 数=' + (viewMap.match(/<polyline/g) || []).length)
  ok('地图上有小车标记',
    (viewMap.match(/<polygon/g) || []).length >= 4,
    'polygon 数=' + (viewMap.match(/<polygon/g) || []).length)
  ok('地图页列出了四个区域',
    viewMap.indexOf('入口大厅') >= 0 && viewMap.indexOf('主通道') >= 0 &&
    viewMap.indexOf('展项区') >= 0 && viewMap.indexOf('设备区') >= 0)
}

/* ---------- 第三轮：其余页面逐个渲染 ---------- */
console.log('')
console.log('[3] 其余页面渲染')
const pages = ['Dispatch', 'Zones', 'Records', 'Voice', 'System']
pages.forEach(function (pg) {
  const drv = '(function () { window.__vg.navigate("' + pg + '"); })();'
  const dom = dumpDom(browser, buildPage(drv), pg.toLowerCase())
  const view = appHtml(dom)
  /* 空态页（如还没归档时的记录页）本来就短，阈值取 1000 足够区分"渲染了"和"白屏" */
  const hasContent = view.length > 1000
  const noRaw = view.indexOf('{{') < 0
  ok(pg + ' 渲染有内容且无残留标签', hasContent && noRaw,
    'len=' + view.length + ' rawTpl=' + !noRaw)
})

/* ---------- 第四轮：调度台的关键交互 ---------- */
console.log('')
console.log('[4] 调度台交互：故障注入 → 阻塞 → 改派')
const drv4 = [
  '(function () {',
  '  var VG = window.VelaGuard;',
  '  /* 干净起点：前面步骤可能把某台车置离线/失联过 */',
  '  VG.store.resetCars();',
  '  VG.store.startRound();',
  '  VG.store.tick(0.25);',
  '  var inj = VG.store.injectObstacle("Z2");',
  '  var before = VG.store.snapshot().summary.counts.blocked;',
  '  var re = VG.store.reassign("Z2");',
  '  var after = VG.store.snapshot().zones.filter(function (z) { return z.id === "Z2" })[0];',
  '  var mem = VG.store.memoryOfLastRound();',
  '  VG.store.silence("Z3");',
  '  var ev = VG.store.tick(0.25);',
  '  var z3 = VG.store.snapshot().zones.filter(function (z) { return z.id === "Z3" })[0];',
  '  window.__probe = {',
  '    injOk: inj.ok, injMsg: inj.message,',
  '    blockedBefore: before,',
  '    reOk: re.ok, reMsg: re.message,',
  '    z2Status: after.status, z2Car: after.car,',
  '    mem: mem,',
  '    z3Status: z3.status, z3Detail: z3.detail,',
  '    evTypes: ev.map(function (e) { return e.type })',
  '  };',
  '  document.title = "PROBE:" + JSON.stringify(window.__probe);',
  '})();'
].join('\n')
const dom4 = dumpDom(browser, buildPage(drv4), 'dispatch')
const m4 = /PROBE:(\{[\s\S]*?\})<\/title>/.exec(dom4)
ok('调度台探针数据存在', !!m4)
if (m4) {
  let p4 = null
  try {
    p4 = JSON.parse(m4[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&'))
  } catch (e) { /* 下面统一报 */ }
  if (p4) {
    ok('故障注入成功', p4.injOk === true, p4.injMsg)
    ok('Z2 转阻塞', p4.blockedBefore === 1, 'blocked=' + p4.blockedBefore)
    ok('改派成功', p4.reOk === true, p4.reMsg)
    ok('改派后 Z2 回到待执行', p4.z2Status === 'pending', p4.z2Status)
    ok('失联判定把 Z3 判为阻塞', p4.z3Status === 'blocked', p4.z3Status + ' / ' + p4.z3Detail)
    ok('产生了 blocked 事件', (p4.evTypes || []).indexOf('blocked') >= 0,
      JSON.stringify(p4.evTypes))
  } else {
    ok('调度台探针 JSON 可解析', false, m4[1].slice(0, 300))
  }
}

/* ---------- 第五轮：语音页兜底路径 ---------- */
console.log('')
console.log('[5] 语音页：无端侧 Agent 时走本地指令表')
const drv5 = [
  '(function () {',
  '  var VG = window.VelaGuard;',
  '  var out = [];',
  '  VG.agent.ask("现在四台车都在线吗，电量多少").then(function (r) {',
  '    out.push({ q: "车队", text: r.text, source: r.source });',
  '    return VG.agent.ask("现在哪些区域没查完");',
  '  }).then(function (r) {',
  '    out.push({ q: "进度", text: r.text, source: r.source });',
  '    return VG.agent.ask("今天天气不错");',
  '  }).then(function (r) {',
  '    out.push({ q: "无关", text: r.text, source: r.source });',
  '    window.__probe = { answers: out, msgs: VG.agent.messages().length };',
  '    document.title = "PROBE:" + JSON.stringify(window.__probe);',
  '  });',
  '})();'
].join('\n')
const dom5 = dumpDom(browser, buildPage(drv5), 'voice')
const m5 = /PROBE:(\{[\s\S]*?\})<\/title>/.exec(dom5)
ok('语音页探针数据存在', !!m5)
if (m5) {
  let p5 = null
  try {
    p5 = JSON.parse(m5[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&'))
  } catch (e) { /* 统一报 */ }
  if (p5) {
    ok('第三次问句全部作答', (p5.answers || []).length === 3, JSON.stringify(p5.answers || []))
    ok('车队问句答出在线数与电量',
      /4 \/ 4 台车在线/.test(p5.answers[0].text) && /电量/.test(p5.answers[0].text),
      p5.answers[0].text)
    ok('进度问句答出四个区域',
      /入口大厅/.test(p5.answers[1].text) && /设备区/.test(p5.answers[1].text),
      p5.answers[1].text)
    ok('无关问句明确说理解不了（不猜、不下发）',
      /理解不了/.test(p5.answers[2].text), p5.answers[2].text)
    ok('兜底来源标记为 local',
      p5.answers.every(function (a) { return a.source === 'local' }),
      JSON.stringify(p5.answers.map(function (a) { return a.source })))
    ok('对话记录已累积', p5.msgs === 6, 'msgs=' + p5.msgs)
  } else {
    ok('语音页探针 JSON 可解析', false, m5[1].slice(0, 300))
  }
}

/* ---------- 第六轮：真实点击（这才是"触控程序"的核心交互） ---------- */
console.log('')
console.log('[6] 真实点击：点磁贴跳页 / 点按钮改状态')
const drv6 = [
  '(function () {',
  '  var VG = window.VelaGuard;',
  '  var app = window.__vg;',
  '  /* 干净起点：前几轮的"置离线/失联"会留在状态里，',
  '     不复位的话这个用例的结果取决于前面跑过什么（不只看代码）。 */',
  '  VG.store.resetCars();',
  '  var log = [];',
  '  /*',
  '   * ⚠️ 每次点击之后**必须重新查询元素**：',
  '   * 外壳是「重绘 = 重建 innerHTML」，旧的节点在重绘后就成了游离节点，',
  '   * 在它上面派发事件不会冒泡到 document，事件代理收不到。',
  '   * 第一版就是抓住按钮引用不放，结果"点了没反应"——查了很久。',
  '   */',
  '  function clickAct(act, tid) {',
  '    var nodes = document.querySelectorAll("[data-act=\\"" + act + "\\"]");',
  '    for (var i = 0; i < nodes.length; i++) {',
  '      if (tid === undefined || nodes[i].getAttribute("data-tid") === tid) {',
  '        nodes[i].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));',
  '        return true;',
  '      }',
  '    }',
  '    return false;',
  '  }',
  '  /* 1) 桌面：点"巡检调度台"磁贴 → 应跳到 Dispatch */',
  '  log.push({ step: "点调度台磁贴", found: clickAct("go", "Dispatch") });',
  '  log[0].page = app.current();',
  '  /* 2) 调度台：点"开始本轮巡检" → 应有 4 个进行中任务 */',
  '  log.push({ step: "点开始本轮巡检", found: clickAct("startRound") });',
  '  log[1].running = VG.store.snapshot().summary.counts.running;',
  '  /* 3) 点"2 号车遇障" → 应有 1 个阻塞 */',
  '  log.push({ step: "点2号车遇障", found: clickAct("inject", "Z2") });',
  '  log[2].blocked = VG.store.snapshot().summary.counts.blocked;',
  '  /* 4) 点"改派" → Z2 回到待执行且换了车 */',
  '  var before = VG.store.zoneStates().filter(function (z) { return z.id === "Z2" })[0];',
  '  window.__vgProbe = [];',
  '  log.push({ step: "点改派", found: clickAct("reassign", "Z2") });',
  '  var z2 = VG.store.snapshot().zones.filter(function (z) { return z.id === "Z2" })[0];',
  '  /* 读 taskCar（任务实际派给的车），不是 car（区域登记车）：',
  '     只读 car 看不出改派效果，会误判成"改派失败" */',
  '  log[3].status = z2.status; log[3].car = z2.taskCar;',
  '  log[3].beforeStatus = before.status; log[3].beforeCar = before.car;',
  '  log[3].probe = window.__vgProbe.slice();',
  '  log[3].cars = VG.mod("data").CARS.map(function (c) { return c.id + ":" + (c.online ? "on" : "off") });',
  '  /* 直接调一次 store.reassign 做对照：区分"点击没生效"与"改派逻辑本身没换车" */',
  '  log[3].directResult = (function () {',
  '    VG.store.injectObstacle("Z3");',
  '    var r = VG.store.reassign("Z3");',
  '    var z3 = VG.store.zoneStates().filter(function (z) { return z.id === "Z3" })[0];',
  '    return { ok: r.ok, msg: r.message, car: z3.car };',
  '  })();',
  '  /* 5) 点"一键取消" → 无进行中任务 */',
  '  log.push({ step: "点一键取消", found: clickAct("cancelAll") });',
  '  log[4].running = VG.store.snapshot().summary.counts.running;',
  '  window.__probe = { clicks: log, finalPage: app.current() };',
  '  document.title = "PROBE:" + JSON.stringify(window.__probe);',
  '})();'
].join('\n')
const dom6 = dumpDom(browser, buildPage(drv6), 'click')
const m6 = /PROBE:(\{[\s\S]*?\})<\/title>/.exec(dom6)
ok('点击测试探针数据存在', !!m6)
if (m6) {
  let p6 = null
  try {
    p6 = JSON.parse(m6[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&'))
  } catch (e) { /* 统一报 */ }
  if (p6 && p6.clicks) {
    const c = p6.clicks
    ok('找得到「巡检调度台」磁贴', c[0].found === true)
    ok('点磁贴真的跳页了', c[0].page === 'Dispatch', 'page=' + c[0].page)
    ok('找得到「开始本轮巡检」按钮', c[1].found === true)
    ok('点它真的派了 4 个任务', c[1].running === 4, 'running=' + c[1].running)
    ok('找得到「2 号车遇障」', c[2].found === true)
    ok('点它真的转阻塞', c[2].blocked === 1, 'blocked=' + c[2].blocked)
    ok('找得到「改派」按钮', c[3].found === true)
    ok('点改派真的换了车', c[3].status === 'pending' && c[3].car !== 'CAR-2',
      c[3].status + ' / ' + c[3].car +
      '  before=' + c[3].beforeStatus + '/' + c[3].beforeCar +
      '  探针=' + JSON.stringify(c[3].probe) +
      '  直调=' + JSON.stringify(c[3].directResult))
    ok('找得到「一键取消」', c[4].found === true)
    ok('点取消真的清空了进行中', c[4].running === 0, 'running=' + c[4].running)
  } else {
    ok('点击测试探针可解析', false, m6[1].slice(0, 300))
  }
}

console.log('')
console.log('结果：' + pass + ' 通过，' + fail + ' 失败')
process.exit(fail === 0 ? 0 : 1)
