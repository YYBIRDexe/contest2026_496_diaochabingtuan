/**
 * 航点生成器 / 路线合规校验器
 *
 * 用法：
 *   node tools/gen-waypoints.js            # 打印航点表（贴进 src/common/data.js）
 *   node tools/gen-waypoints.js --check    # 只校验 src/common/data.js 里的现有路线
 *
 * 为什么要有这个脚本：路线坐标手算极易出错——第一版我按直觉写的
 * route_aisle，其中一段实际长度是 2.96 m，而方案二自己写的约束是
 * 「单步远小于全局上限（1.0 m）」。手算看不出来，脚本一眼就看出来。
 *
 * 采样规则：沿折线每 step 米插一个航点，并强制以拐点收尾，
 * 保证**每一段都 ≤ step**，且每个明显拐弯处都有一个航点。
 */
const path = require('path')
const esm = require('./esm.js')

const STEP = 0.5

/** 四条路线的折线骨架（米，地图坐标系） */
const SKELETON = {
  entrance: [[0.90, 1.60], [3.40, 1.60]],
  aisle: [[3.40, 1.60], [3.40, 4.30], [6.10, 4.30]],
  exhibit: [[6.10, 4.30], [8.60, 4.30], [8.60, 2.40]],
  equipment: [[8.60, 2.40], [8.60, 0.80], [6.10, 0.80]]
}

function lerp(a, b, n) {
  const out = []
  for (let i = 1; i < n; i += 1) {
    const t = i / n
    out.push([
      +(a[0] + (b[0] - a[0]) * t).toFixed(2),
      +(a[1] + (b[1] - a[1]) * t).toFixed(2)
    ])
  }
  return out
}

/** 把折线按 step 采样成航点序列 */
function chain(pts, step) {
  const raw = [pts[0]]
  for (let i = 1; i < pts.length; i += 1) {
    const a = pts[i - 1]
    const b = pts[i]
    const d = Math.hypot(b[0] - a[0], b[1] - a[1])
    const n = Math.max(1, Math.ceil(d / step))
    lerp(a, b, n).forEach(function (p) { raw.push(p) })
    raw.push(b)
  }
  return raw
}

function stats(list) {
  let len = 0
  let maxStep = 0
  for (let i = 1; i < list.length; i += 1) {
    const d = Math.hypot(list[i][0] - list[i - 1][0], list[i][1] - list[i - 1][1])
    len += d
    maxStep = Math.max(maxStep, d)
  }
  return { len: len, maxStep: maxStep }
}

/* ================================================================== */
if (process.argv.indexOf('--check') >= 0) {
  /* ---- 校验模式：读 data.js 的真实路线 ---- */
  const COMMON = path.resolve(__dirname, '..', 'src', 'common')
  const D = esm.makeLoader(COMMON).value('./data.js')

  let fail = 0
  console.log('=== 路线合规校验（data.js）===')
  const bnd = D.MAP.bounds || { x: [0, D.MAP.width], y: [0, D.MAP.height] }
  console.log('约束：单步 ≤ ' + D.LIMITS.step_distance_max_m + ' m，单条 ≤ 3.5 m，航点必须在可行区域内')
  console.log('可行区域（来自车端真实地图）：x ' + bnd.x[0] + ' ~ ' + bnd.x[1] +
    '   y ' + bnd.y[0] + ' ~ ' + bnd.y[1])
  console.log('')
  const names = Object.keys(D.ROUTES)
  names.forEach(function (rid) {
    const r = D.ROUTES[rid]
    const pts = D.routePoints(rid)
    const problems = []

    if (pts.length < 2) {
      problems.push('航点少于 2 个')
    }
    if (pts.length !== r.stops.length) {
      problems.push('有 stop 指向了不存在的航点（stops=' + r.stops.length + ', 解析出 ' + pts.length + '）')
    }
    pts.forEach(function (p) {
      if (p.x < bnd.x[0] || p.x > bnd.x[1] || p.y < bnd.y[0] || p.y > bnd.y[1]) {
        problems.push('航点 ' + p.id + ' 落在可行区域外 (' + p.x + ', ' + p.y + ')')
      }
    })
    let maxStep = 0
    for (let i = 1; i < pts.length; i += 1) {
      const d = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y)
      maxStep = Math.max(maxStep, d)
      if (d > D.LIMITS.step_distance_max_m + 1e-6) {
        problems.push('第 ' + i + ' 步 ' + d.toFixed(2) + ' m 超过上限（' +
          pts[i - 1].id + ' → ' + pts[i].id + '）')
      }
    }
    const len = D.routeLength(rid)
    if (len > 3.5 + 1e-6) {
      problems.push('单条路线 ' + len.toFixed(2) + ' m 过长（要求 ≤ 3.5 m）')
    }

    if (problems.length === 0) {
      console.log('  ok   ' + rid.padEnd(16) + ' ' + pts.length + ' 点 / ' +
        len.toFixed(2) + ' m / 最长步 ' + maxStep.toFixed(2) + ' m')
    } else {
      fail += 1
      console.log('  FAIL ' + rid.padEnd(16) + ' ' + pts.length + ' 点 / 最长步 ' +
        maxStep.toFixed(2) + ' m')
      problems.forEach(function (p) { console.log('         · ' + p) })
    }
  })

  const total = names.reduce(function (s, rid) { return s + D.routeLength(rid) }, 0)
  console.log('')
  console.log('整条巡检路线总长：' + total.toFixed(2) + ' m（四条短路线首尾相接）')
  console.log(fail === 0 ? '结论：全部合规' : '结论：' + fail + ' 条不合规')
  process.exit(fail === 0 ? 0 : 1)
}

/* ---- 生成模式 ---- */
console.log('/* 由 tools/gen-waypoints.js 生成，采样步长 ' + STEP + ' m */')
Object.keys(SKELETON).forEach(function (k) {
  const c = chain(SKELETON[k], STEP)
  const s = stats(c)
  console.log('')
  console.log('// ' + k + '：' + c.length + ' 点 / ' + s.len.toFixed(2) +
    ' m / 最长步 ' + s.maxStep.toFixed(2) + ' m')
  c.forEach(function (p, i) {
    const id = k.slice(0, 2).toUpperCase() + String(i + 1).padStart(2, '0')
    const last = i === c.length - 1
    console.log("  { id: '" + id + "', x: " + p[0].toFixed(2) + ", y: " + p[1].toFixed(2) +
      ", yaw: 0.00, name: '" + k + " " + (i + 1) + "' }" + (last ? '' : ','))
  })
})
