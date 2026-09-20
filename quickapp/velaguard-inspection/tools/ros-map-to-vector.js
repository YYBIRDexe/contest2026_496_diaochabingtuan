/**
 * 把车端真实 ROS 地图（PGM + YAML）转成 app 能画的矢量轮廓
 *
 * 用法：
 *   node tools/ros-map-to-vector.js <classroom.pgm> <classroom.yaml> [--out src/common/map-data.js]
 *   node tools/ros-map-to-vector.js --auto            # 用工作区里已归档的那份
 *
 * 为什么要转：
 *   模拟器里的快应用要自己画地图。直接把 350×197 的 PGM 塞进去不现实
 *   （体积、灰度渲染、快应用没有图像解码器），而路线又必须画在**真实坐标系**上，
 *   所以需要一份轻量的矢量近似：外围墙线 + 若干内部障碍块。
 *
 * 算法（刻意保持朴素，够用即可）：
 *   1. 读 PGM（P5 二进制），按 YAML 的 resolution / origin 把像素映射回米；
 *   2. 行优先扫描占据格（值为 0 的墙），用**行程 + 纵向合并**压成矩形；
 *   3. 丢掉面积过小的碎块（建图噪点），保留墙与家具轮廓；
 *   4. 顺带统计四周墙体上的**缺口**（门洞/通道），打印出来供人工确认。
 *
 * 注意：这只是**画图用的近似**。方案不声称具备 SLAM/导航能力，
 * 路线是预设的、车端只沿线走；本脚本产出的轮廓不参与任何控制逻辑。
 */
const fs = require('fs')
const path = require('path')

/* ------------------------------------------------------------------ *
 * 1. 读 YAML（只认我们需要的几个字段，不引第三方库）
 * ------------------------------------------------------------------ */
function parseYaml(text) {
  const out = {}
  text.split(/\r?\n/).forEach(function (line) {
    const s = line.replace(/#.*$/, '').trim()
    if (!s) { return }
    const m = /^([A-Za-z_]+)\s*:\s*(.+)$/.exec(s)
    if (!m) { return }
    let v = m[2].trim()
    if (v.charAt(0) === '[') {
      out[m[1]] = v.replace(/[\[\]]/g, '').split(',').map(function (x) { return parseFloat(x) })
    } else if (/^-?\d+(\.\d+)?$/.test(v)) {
      out[m[1]] = parseFloat(v)
    } else {
      out[m[1]] = v
    }
  })
  return out
}

/* ------------------------------------------------------------------ *
 * 2. 读 PGM（P5 / P2）
 * ------------------------------------------------------------------ */
function readPgm(buf) {
  let pos = 0
  function token() {
    /* 跳过空白与 # 注释 */
    for (;;) {
      while (pos < buf.length && /\s/.test(String.fromCharCode(buf[pos]))) { pos += 1 }
      if (buf[pos] === 0x23) {
        while (pos < buf.length && buf[pos] !== 0x0a) { pos += 1 }
      } else {
        break
      }
    }
    let s = ''
    while (pos < buf.length && !/\s/.test(String.fromCharCode(buf[pos]))) {
      s += String.fromCharCode(buf[pos])
      pos += 1
    }
    return s
  }
  const magic = token()
  if (magic !== 'P5' && magic !== 'P2') {
    throw new Error('只支持 P5/P2 的 PGM，收到 ' + magic)
  }
  const w = parseInt(token(), 10)
  const h = parseInt(token(), 10)
  const maxv = parseInt(token(), 10)
  pos += 1  /* 单字节分隔符 */
  const px = new Uint8Array(w * h)
  if (magic === 'P5') {
    px.set(buf.subarray(pos, pos + w * h))
  } else {
    for (let i = 0; i < w * h; i += 1) {
      px[i] = parseInt(token(), 10)
    }
  }
  return { w: w, h: h, maxv: maxv, px: px }
}

/* ------------------------------------------------------------------ *
 * 3. 占据格 → 矩形（行程 + 纵向合并）
 * ------------------------------------------------------------------ */
function toRects(pgm, occupiedThreshold) {
  const w = pgm.w
  const h = pgm.h
  const occ = new Uint8Array(w * h)
  for (let i = 0; i < w * h; i += 1) {
    occ[i] = pgm.px[i] <= occupiedThreshold ? 1 : 0
  }
  const used = new Uint8Array(w * h)
  const rects = []
  for (let y = 0; y < h; y += 1) {
    let x = 0
    while (x < w) {
      if (!occ[y * w + x] || used[y * w + x]) { x += 1; continue }
      /* 向右扩展同行的连续占据格 */
      let x2 = x
      while (x2 + 1 < w && occ[y * w + x2 + 1] && !used[y * w + x2 + 1]) { x2 += 1 }
      /* 向下扩展：下一行同区间必须全部占据且未用 */
      let y2 = y
      for (;;) {
        const ny = y2 + 1
        if (ny >= h) { break }
        let ok = true
        for (let k = x; k <= x2; k += 1) {
          if (!occ[ny * w + k] || used[ny * w + k]) { ok = false; break }
        }
        if (!ok) { break }
        y2 = ny
      }
      for (let yy = y; yy <= y2; yy += 1) {
        for (let xx = x; xx <= x2; xx += 1) { used[yy * w + xx] = 1 }
      }
      rects.push({ x: x, y: y, w: x2 - x + 1, h: y2 - y + 1 })
      x = x2 + 1
    }
  }
  return rects
}

/* ------------------------------------------------------------------ *
 * 4. 门洞检测：沿四条外边界找"非墙"的连续段
 * ------------------------------------------------------------------ */
function findGaps(occ, w, h, band, minLen) {
  function runs(get, n) {
    const out = []
    let i = 0
    while (i < n) {
      if (get(i)) { i += 1; continue }
      let j = i
      while (j + 1 < n && !get(j + 1)) { j += 1 }
      if (j - i + 1 >= minLen) { out.push([i, j]) }
      i = j + 1
    }
    return out
  }
  function isWall(x, y) {
    if (x < 0 || y < 0 || x >= w || y >= h) { return true }
    return occ[y * w + x] === 1
  }
  /* 上下边：看 band 行内是否有墙；左右边：看 band 列内是否有墙 */
  const top = runs(function (i) {
    for (let d = 0; d < band; d += 1) { if (isWall(i, d)) { return true } }
    return false
  }, w)
  const bottom = runs(function (i) {
    for (let d = 0; d < band; d += 1) { if (isWall(i, h - 1 - d)) { return true } }
    return false
  }, w)
  const left = runs(function (i) {
    for (let d = 0; d < band; d += 1) { if (isWall(d, i)) { return true } }
    return false
  }, h)
  const right = runs(function (i) {
    for (let d = 0; d < band; d += 1) { if (isWall(w - 1 - d, i)) { return true } }
    return false
  }, h)
  return { top: top, bottom: bottom, left: left, right: right }
}

/* ------------------------------------------------------------------ *
 * 主流程
 * ------------------------------------------------------------------ */
function main() {
  const args = process.argv.slice(2)
  let pgmPath
  let yamlPath
  let outPath = path.resolve(__dirname, '..', 'src', 'common', 'map-data.js')

  if (args.indexOf('--auto') >= 0) {
    const base = 'F:\\xiaomiaiot\\01-VelaGuard小车项目\\地图\\车端实际地图-20260919\\01-当前生效'
    pgmPath = path.join(base, 'classroom.pgm')
    yamlPath = path.join(base, 'classroom.yaml')
  } else {
    const rest = args.filter(function (a) { return a.indexOf('--') !== 0 })
    pgmPath = rest[0]
    yamlPath = rest[1]
    const oi = args.indexOf('--out')
    if (oi >= 0 && args[oi + 1]) { outPath = args[oi + 1] }
  }

  if (!pgmPath || !fs.existsSync(pgmPath)) {
    console.error('找不到 PGM：' + pgmPath)
    process.exit(1)
  }
  const yml = yamlPath && fs.existsSync(yamlPath)
    ? parseYaml(fs.readFileSync(yamlPath, 'utf8'))
    : {}
  const res = yml.resolution || 0.05
  const origin = yml.origin || [0, 0, 0]

  const pgm = readPgm(fs.readFileSync(pgmPath))
  console.log('=== ROS 地图 → 矢量轮廓 ===')
  console.log('源文件   : ' + pgmPath)
  console.log('分辨率   : ' + res + ' m/格    原点: [' + origin.join(', ') + ']')
  console.log('栅格尺寸 : ' + pgm.w + ' × ' + pgm.h + ' 格 = ' +
    (pgm.w * res).toFixed(2) + ' × ' + (pgm.h * res).toFixed(2) + ' m')

  const W = pgm.w * res
  const H = pgm.h * res

  /* 栅格坐标 → 地图坐标（米，原点在左下、y 轴向上） */
  function toWorldRect(r) {
    const x0 = origin[0] + r.x * res
    const y1 = origin[1] + (pgm.h - r.y) * res
    const y0 = origin[1] + (pgm.h - (r.y + r.h)) * res
    return { x: +x0.toFixed(2), y: +y0.toFixed(2), w: +(r.w * res).toFixed(2), h: +(r.h * res).toFixed(2) }
  }

  const occupiedThreshold = 60
  const rects = toRects(pgm, occupiedThreshold)
  const world = rects.map(toWorldRect)
  console.log('原始矩形 : ' + rects.length + ' 个')

  /* 丢掉碎块：面积 < 0.04 m²（约 4×4 格）的按噪点处理 */
  const kept = world.filter(function (r) { return r.w * r.h >= 0.04 })
  const dropped = world.length - kept.length
  console.log('保留矩形 : ' + kept.length + ' 个（丢弃碎块 ' + dropped + ' 个）')

  /* 门洞 */
  const occ = new Uint8Array(pgm.w * pgm.h)
  for (let i = 0; i < pgm.w * pgm.h; i += 1) { occ[i] = pgm.px[i] <= occupiedThreshold ? 1 : 0 }
  const gaps = findGaps(occ, pgm.w, pgm.h, 3, 6)
  function gapToWorld(edge, g) {
    if (edge === 'top' || edge === 'bottom') {
      const x0 = origin[0] + g[0] * res
      const x1 = origin[0] + (g[1] + 1) * res
      const y = edge === 'top' ? origin[1] + pgm.h * res : origin[1]
      return { edge: edge, x: +((x0 + x1) / 2).toFixed(2), y: +y.toFixed(2), width: +(x1 - x0).toFixed(2) }
    }
    const y0 = origin[1] + (pgm.h - (g[1] + 1)) * res
    const y1 = origin[1] + (pgm.h - g[0]) * res
    const x = edge === 'left' ? origin[0] : origin[0] + pgm.w * res
    return { edge: edge, x: +x.toFixed(2), y: +((y0 + y1) / 2).toFixed(2), width: +(y1 - y0).toFixed(2) }
  }
  console.log('')
  console.log('外边界缺口（疑似门洞/通道，单位米）：')
  const allGaps = []
  ;['top', 'bottom', 'left', 'right'].forEach(function (edge) {
    gaps[edge].forEach(function (g) {
      const w = gapToWorld(edge, g)
      allGaps.push(w)
      console.log('  ' + edge.padEnd(7) + ' 中心 (' + w.x + ', ' + w.y + ')  宽 ' + w.width + ' m')
    })
  })
  if (allGaps.length === 0) {
    console.log('  （未检出明显缺口）')
  }

  /* 边界框：地图里真实的可行区域范围 */
  let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9
  kept.forEach(function (r) {
    minX = Math.min(minX, r.x); minY = Math.min(minY, r.y)
    maxX = Math.max(maxX, r.x + r.w); maxY = Math.max(maxY, r.y + r.h)
  })
  console.log('')
  console.log('占据区域包围盒: x ' + minX.toFixed(2) + ' ~ ' + maxX.toFixed(2) +
    '   y ' + minY.toFixed(2) + ' ~ ' + maxY.toFixed(2))

  /* 输出为 app 可直接 import 的数据文件 */
  const body = []
  body.push('/**')
  body.push(' * 地图矢量轮廓 —— **自动生成，请勿手改**')
  body.push(' *')
  body.push(' * 生成命令：node tools/ros-map-to-vector.js --auto')
  body.push(' * 来源：车端当前生效地图 ' + path.basename(pgmPath) +
    '（' + pgm.w + '×' + pgm.h + ' 格，' + res + ' m/格，原点 [' + origin.join(', ') + ']）')
  body.push(' *')
  body.push(' * 说明：把栅格地图压成矩形块，只用于**画图**；')
  body.push(' *      不参与任何控制逻辑（路线是预设的，车端只沿线走）。')
  body.push(' */')
  body.push('')
  body.push('export const MAP_META = ' + JSON.stringify({
    name: path.basename(pgmPath).replace(/\.pgm$/i, ''),
    source: path.basename(pgmPath),
    gridW: pgm.w,
    gridH: pgm.h,
    resolution: res,
    origin: origin,
    width: +W.toFixed(2),
    height: +H.toFixed(2),
    bounds: {
      x: [+minX.toFixed(2), +maxX.toFixed(2)],
      y: [+minY.toFixed(2), +maxY.toFixed(2)]
    }
  }, null, 2))
  body.push('')
  body.push('/** 外墙与固定障碍（矩形块，米） */')
  body.push('export const WALLS = [')
  kept.forEach(function (r, i) {
    body.push('  { x: ' + r.x + ', y: ' + r.y + ', w: ' + r.w + ', h: ' + r.h + ' }' +
      (i === kept.length - 1 ? '' : ','))
  })
  body.push(']')
  body.push('')
  body.push('/** 外边界缺口（门洞/通道中心点，米） */')
  body.push('export const GAPS = [')
  allGaps.forEach(function (g, i) {
    body.push('  { edge: ' + JSON.stringify(g.edge) + ', x: ' + g.x + ', y: ' + g.y +
      ', width: ' + g.width + ' }' + (i === allGaps.length - 1 ? '' : ','))
  })
  body.push(']')
  body.push('')
  body.push('export default { MAP_META: MAP_META, WALLS: WALLS, GAPS: GAPS }')
  body.push('')

  fs.mkdirSync(path.dirname(outPath), { recursive: true })
  fs.writeFileSync(outPath, body.join('\n'), 'utf8')
  console.log('')
  console.log('已写出：' + outPath + '（' + (fs.statSync(outPath).size / 1024).toFixed(1) + ' KB）')
}

main()
