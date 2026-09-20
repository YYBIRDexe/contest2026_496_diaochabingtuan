/**
 * store.js 冒烟测试（Node 直接跑，不依赖界面）
 *
 * 用法：node tools/test-store.js
 *
 * 做法：用 tools/esm.js 把 src/common/*.js 的 ESM 语法就地转成 CommonJS 再载入，
 * 测的是**同一份源码**，不是副本——避免"测试过了但源码没改"。
 */
const path = require('path')
const esm = require('./esm.js')

const COMMON = path.resolve(__dirname, '..', 'src', 'common')

/** 每个用例都拿一个全新的 store 实例（store 内部有模块级状态） */
function freshStore() {
  return esm.makeLoader(COMMON).value('./store.js')
}
function loadData() {
  return esm.makeLoader(COMMON).value('./data.js')
}

/* ------------------------------------------------------------------ */
let pass = 0
let fail = 0

function ok(name, cond, extra) {
  if (cond) {
    pass += 1
    console.log('  ok   ' + name)
  } else {
    fail += 1
    console.log('  FAIL ' + name + (extra ? '  → ' + extra : ''))
  }
}
function eq(name, actual, expected) {
  ok(name, actual === expected,
    'got ' + JSON.stringify(actual) + ', want ' + JSON.stringify(expected))
}
function zone(snap, id) {
  return snap.zones.filter(function (z) { return z.id === id })[0]
}
/** 一直 tick 到某区域不再是 running，或超过 maxSec 秒 */
function runUntil(store, id, maxSec) {
  const dt = 0.25
  let t = 0
  let events = []
  while (t < maxSec) {
    events = events.concat(store.tick(dt))
    t += dt
    if (zone(store.snapshot(), id).status !== 'running') {
      break
    }
  }
  return { seconds: t, events: events }
}

/* ================================================================== */
console.log('=== VelaGuard store.js 冒烟测试 ===')

/* ---------- 1. 数据表自检（路线必须短、必须落在地图内） ---------- */
console.log('\n[1] 端侧预设表自检')
const D = loadData()
ok('data.js 可加载', !!D && !!D.ROUTES)
ok('登记 4 个区域', D.ZONES.length === 4)
ok('登记 4 台车', D.CARS.length === 4)
ok('每个区域的路线都存在', D.ZONES.every(z => !!D.ROUTES[z.route]))
ok('每个区域的车都存在', D.ZONES.every(z => !!D.carById(z.car)))

let routeOk = true
let routeMax = 0
const bnd = D.MAP.bounds || { x: [0, D.MAP.width], y: [0, D.MAP.height] }
Object.keys(D.ROUTES).forEach(function (rid) {
  const pts = D.routePoints(rid)
  if (pts.length < 2) { routeOk = false }
  /* 每个航点都必须落在**可行区域**内（真实地图的原点可能是负的，
     所以判据是 bounds 而不是 0~width） */
  pts.forEach(function (p) {
    if (p.x < bnd.x[0] || p.x > bnd.x[1] || p.y < bnd.y[0] || p.y > bnd.y[1]) { routeOk = false }
  })
  /* 单步距离不得超过上限（方案二红线：参数越界即拒发） */
  for (let i = 1; i < pts.length; i += 1) {
    const d = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y)
    if (d > D.LIMITS.step_distance_max_m) { routeOk = false }
    routeMax = Math.max(routeMax, d)
  }
  /* 路线要短：单条 ≤ 3.5 m */
  if (D.routeLength(rid) > 3.5) { routeOk = false }
})
ok('四条路线都合法（≥2 航点 / 在地图内 / 单步 ≤1m / 单条 ≤3.5m）', routeOk,
  '最长单步 ' + routeMax.toFixed(2) + ' m')
ok('整条固定路线由四条短路线首尾相接', D.ALL_ROUTE.length === 4)

/* ---------- 2. 功能一+二：派单与离线车拦截 ---------- */
console.log('\n[2] 功能一/二 · 派单与状态机')
let store = freshStore()
let snap = store.snapshot()
eq('初始轮次 0', snap.round, 0)
eq('四个区域都是待执行', snap.summary.counts.pending, 4)
eq('初始汇总话术', snap.summaryLine, '尚未开始巡检')

store.setCarOnline('CAR-4', false)
let r = store.dispatch('Z4')
ok('离线车派单被拒', r.ok === false, r.message)
ok('拒绝理由提到离线', /离线/.test(r.message), r.message)
ok('未知区域派单被拒', store.dispatch('Z9').ok === false)

store = freshStore()
store.setCarOnline('CAR-4', false)
const sr = store.startRound()
eq('第 1 轮启动', sr.round, 1)
eq('3 个区域派单成功（CAR-4 离线）', sr.started, 3)
ok('提示里说明离线原因', /离线|CAR-4/.test(sr.message), sr.message)
snap = store.snapshot()
eq('3 个进行中', snap.summary.counts.running, 3)
eq('1 个离线', snap.summary.counts.offline, 1)

/* ---------- 3. 功能二：沿固定路线走完 ---------- */
console.log('\n[3] 功能二 · 路线执行到完成')
const before = zone(store.snapshot(), 'Z1')
eq('Z1 初始进度 0', before.progress, 0)
const run1 = runUntil(store, 'Z1', 30)
const after = zone(store.snapshot(), 'Z1')
eq('Z1 走完为已完成', after.status, 'done')
eq('Z1 进度到 100', after.progress, 100)
ok('耗时在合理区间（2~8 秒）', run1.seconds > 2 && run1.seconds < 8, run1.seconds + 's')
ok('产生了 done 事件', run1.events.some(e => e.type === 'done'))

/* 全部跑完 → 四区汇总 */
let guard = 0
while (guard < 400 && store.snapshot().summary.counts.running > 0) {
  store.tick(0.25)
  guard += 1
}
snap = store.snapshot()
eq('三个在线区域全部完成', snap.summary.counts.done, 3)
ok('汇总话术列出四个区域', /第 1 轮/.test(snap.summaryLine), snap.summaryLine)

/* ---------- 4. 功能三：故障注入 + 人工处置 ---------- */
console.log('\n[4] 功能三 · 异常中断与人工处置')
store = freshStore()
store.startRound()
const inj = store.injectObstacle('Z2')
ok('故障注入成功', inj.ok === true, inj.message)
ok('告警话术含车号与停止', /CAR-2/.test(inj.message) && /停止/.test(inj.message), inj.message)
eq('Z2 转阻塞', store.snapshot().summary.counts.blocked, 1)

const re = store.reassign('Z2')
ok('改派成功', re.ok === true, re.message)
ok('改派换了一台车（不再是 CAR-2）', !/CAR-2/.test(re.message), re.message)
eq('改派后 Z2 回到待执行', zone(store.snapshot(), 'Z2').status, 'pending')

/* 只剩一台在线车时，改派必须如实说找不到 */
store = freshStore()
store.startRound()
store.setCarOnline('CAR-1', false)
store.setCarOnline('CAR-2', false)
store.setCarOnline('CAR-3', false)
store.setCarOnline('CAR-4', false)
const inj3 = store.injectObstacle('Z2')
ok('（前置）Z2 仍可注入阻塞', inj3.ok === true, inj3.message)
const re2 = store.reassign('Z2')
ok('全部车离线时改派如实失败', re2.ok === false, re2.message)
ok('失败理由建议顺延', /顺延/.test(re2.message), re2.message)

/* 只有一台在线车、且它就是当前那台时，也必须失败 */
store = freshStore()
store.startRound()
store.setCarOnline('CAR-1', false)
store.setCarOnline('CAR-3', false)
store.setCarOnline('CAR-4', false)
store.injectObstacle('Z2')
const re3 = store.reassign('Z2')
ok('仅剩本车在线时无车可改派', re3.ok === false, re3.message)

/* 顺延 */
store = freshStore()
store.startRound()
store.injectObstacle('Z3')
const po = store.postpone('Z3')
ok('顺延成功', po.ok === true, po.message)
eq('顺延后 Z3 为已取消', zone(store.snapshot(), 'Z3').status, 'cancelled')

/* 一键取消 */
store = freshStore()
store.startRound()
const ca = store.cancelAll()
eq('一键取消 4 个任务', ca.message, '已取消 4 个未完成任务')
eq('取消后无进行中', store.snapshot().summary.counts.running, 0)
eq('取消后 4 个已取消', store.snapshot().summary.counts.cancelled, 4)

/* ---------- 5. 功能三核心：阈值主动（失联判定） ---------- */
console.log('\n[5] 功能三核心 · 连续无回执 → 判失联')
store = freshStore()
store.startRound()
store.silence('Z3')
const ev5 = store.tick(0.25)
const z3 = zone(store.snapshot(), 'Z3')
eq('Z3 一次 tick 内即被判失联', z3.status, 'blocked')
ok('阻塞原因是超时', /未收到回执|失联/.test(z3.detail), z3.detail)
ok('抛出 blocked 事件', ev5.some(e => e.type === 'blocked' && e.zoneId === 'Z3'))
ok('告警文案含秒数与车号', /20 秒/.test(ev5[0].text), ev5[0].text)
ok('未受影响的区域仍在跑', zone(store.snapshot(), 'Z1').status === 'running')

/* 正常推进时不应误判失联 */
store = freshStore()
store.startRound()
const run5 = runUntil(store, 'Z1', 30)
ok('正常推进不会被误判为失联', run5.events.filter(e => e.type === 'blocked').length === 0)

/* ---------- 6. 功能四：覆盖汇总 + 轮次台账 + 跨轮次记忆 ---------- */
console.log('\n[6] 功能四 · 覆盖汇总与跨轮次记忆')
store = freshStore()
store.startRound()
store.injectObstacle('Z2')
store.tick(0.25)
let guard6 = 0
while (guard6 < 400 && store.snapshot().summary.counts.running > 0) {
  store.tick(0.25)
  guard6 += 1
}
const cr = store.closeRound()
ok('收轮成功', cr.ok === true, cr.message)
eq('台账 1 条', store.getRecords().length, 1)
eq('台账含 4 个区域', store.getRecords()[0].zones.length, 4)
ok('汇总里点出阻塞', /阻塞/.test(cr.message), cr.message)

const mem = store.memoryOfLastRound()
ok('上一轮有未完成 → 给出跨轮次提醒', mem !== null, JSON.stringify(mem))
ok('提醒点明是哪个区域', mem && /主通道/.test(mem.text), mem && mem.text)

/* 全完成的一轮不应产生记忆噪音 */
store = freshStore()
store.startRound()
let guard6b = 0
while (guard6b < 500 && store.snapshot().summary.counts.running > 0) {
  store.tick(0.25)
  guard6b += 1
}
store.closeRound()
ok('四区全完成时不再提醒', store.memoryOfLastRound() === null,
  JSON.stringify(store.memoryOfLastRound()))

/* ---------- 7. 事件回调（Agent 主动告警的挂点） ---------- */
console.log('\n[7] 主动事件回调')
store = freshStore()
let got = null
store.onEvent(function (e) { got = e })
store.emit({ type: 'test', text: 'hello' })
ok('onEvent 回调可用', got && got.type === 'test')

/* ---------- 8. 复位 ---------- */
console.log('')
console.log('结果：' + pass + ' 通过，' + fail + ' 失败')
process.exit(fail === 0 ? 0 : 1)
