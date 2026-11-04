/**
 * VelaGuard · 地图渲染（纯函数）
 *
 * 把 CFG 里的**地图坐标系（米）**换算成屏幕像素，产出一张简笔平面图：
 *   · 房间轮廓与固定障碍（来自车端真实 ROS 地图的矢量近似）
 *   · 四个区域的分区标签与底色
 *   · 四条固定路线的折线 + 航点
 *   · 每台车的当前位置与朝向（沿路线逐段移动的动画就靠它）
 *
 * 为什么用字符串拼 SVG 而不是画一堆 div：
 *   · 折线、圆、旋转的三角用 SVG 一条元素就够，纯 flex 盒模型做不了斜线；
 *   · 快应用（LVGL）与浏览器预览对 SVG 子集的支持一致，不需要两套渲染；
 *   · 整段是**纯函数**，可以直接在 Node 里断言输出，不用起界面。
 *
 * 约定：SVG 坐标系 y 轴向下，而地图坐标系 y 轴向上，
 * 所以换算时要翻一下。这是最容易错的一处，单测里锁住了。
 */
import CFG from './data.js'

/** 屏幕与画布尺寸（openvela 模拟器 goldfish 屏是 720×1280 竖屏） */
export const SCREEN_W = 720
export const SCREEN_H = 1280

/** 地图画布在页面里的排版参数 */
export const MAP_LAYOUT = {
  /** 画布左右留白 */
  padX: 16,
  /** 画布高度（竖屏下地图占屏幕中段） */
  height: 460,
  /** 画布内再留一圈内边距，避免路线贴边 */
  inner: 14
}

/**
 * 世界坐标（米）→ 屏幕像素。
 *
 * 取景按**实际有墙的范围**（map.bounds）算，不按栅格名义尺寸：
 * 车端真图上四周有大片空白（未知区被裁掉了），按名义尺寸取景会把路线挤成一小团。
 */
export function makeProjector(map, width, height) {
  const layout = MAP_LAYOUT
  const usableW = width - layout.padX * 2 - layout.inner * 2
  const usableH = height - layout.inner * 2
  const b = map.bounds || { x: [0, map.width], y: [0, map.height] }
  const wx = b.x[1] - b.x[0]
  const wy = b.y[1] - b.y[0]
  const scale = Math.min(usableW / wx, usableH / wy)
  const offX = layout.padX + layout.inner + (usableW - wx * scale) / 2 - b.x[0] * scale
  const offY = layout.inner + (usableH - wy * scale) / 2 + b.y[1] * scale
  return function project(x, y) {
    return {
      sx: +(offX + x * scale).toFixed(1),
      /* y 轴翻转：地图向上为正，SVG 向下为正 */
      sy: +(offY - y * scale).toFixed(1)
    }
  }
}

/** 转义：名称来自数据表，仍统一转义一遍，避免以后改数据时出问题 */
function esc(s) {
  return String(s === undefined || s === null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** 区域分区块（与 data.js 里四条路线所在的位置对应；改路线时同步改这里） */
export const ZONE_BLOCKS = [
  { id: 'Z1', name: '入口大厅', x: -3.90, y: 3.10, w: 1.90, h: 2.10, color: 'rgba(47,109,246,0.13)', edge: 'rgba(47,109,246,0.45)' },
  { id: 'Z2', name: '主通道', x: -1.70, y: 3.70, w: 3.30, h: 0.90, color: 'rgba(14,165,164,0.13)', edge: 'rgba(14,165,164,0.45)' },
  { id: 'Z3', name: '展项区', x: 2.40, y: 1.40, w: 2.60, h: 1.70, color: 'rgba(124,92,255,0.13)', edge: 'rgba(124,92,255,0.45)' },
  { id: 'Z4', name: '设备区', x: 4.60, y: -3.00, w: 2.60, h: 1.70, color: 'rgba(245,158,11,0.13)', edge: 'rgba(245,158,11,0.45)' }
]

/**
 * 渲染整张地图。
 *
 * @param {object} opts
 *   zones     store.zoneStates() 的结果（拿状态色）
 *   tasks     每个区域的实时位置（{ zoneId: {x, y, yaw} }），没有就不画车
 *   width     画布像素宽，默认 SCREEN_W
 *   height    画布像素高，默认 MAP_LAYOUT.height
 *   showGrid  是否画米格网
 * @returns {string} 一段 <svg> 字符串
 */
export function renderMap(opts) {
  const o = opts || {}
  const zones = o.zones || []
  const tasks = o.tasks || {}
  const width = o.width || SCREEN_W
  const height = o.height || MAP_LAYOUT.height
  const map = CFG.MAP
  const project = makeProjector(map, width, height)

  const statusOfZone = {}
  for (let i = 0; i < zones.length; i += 1) {
    statusOfZone[zones[i].id] = zones[i]
  }

  const out = []
  out.push('<svg class="mapsvg" width="' + width + '" height="' + height +
    '" viewBox="0 0 ' + width + ' ' + height + '">')

  /* 底色 */
  out.push('<rect x="0" y="0" width="' + width + '" height="' + height +
    '" rx="18" fill="#0e1729"/>')

  /* 米格网（每米一条淡线，按实际取景范围画） */
  const bnd = map.bounds || { x: [0, map.width], y: [0, map.height] }
  if (o.showGrid !== false) {
    for (let gx = Math.ceil(bnd.x[0]); gx <= Math.floor(bnd.x[1]); gx += 1) {
      const a = project(gx, bnd.y[0])
      const b = project(gx, bnd.y[1])
      out.push('<line x1="' + a.sx + '" y1="' + a.sy + '" x2="' + b.sx + '" y2="' + b.sy +
        '" stroke="rgba(148,163,184,0.10)" stroke-width="1"/>')
    }
    for (let gy = Math.ceil(bnd.y[0]); gy <= Math.floor(bnd.y[1]); gy += 1) {
      const a = project(bnd.x[0], gy)
      const b = project(bnd.x[1], gy)
      out.push('<line x1="' + a.sx + '" y1="' + a.sy + '" x2="' + b.sx + '" y2="' + b.sy +
        '" stroke="rgba(148,163,184,0.10)" stroke-width="1"/>')
    }
  }

  /* 区域分区块 + 区域名 */
  for (let i = 0; i < ZONE_BLOCKS.length; i += 1) {
    const b = ZONE_BLOCKS[i]
    const p1 = project(b.x, b.y + b.h)
    const p2 = project(b.x + b.w, b.y)
    out.push('<rect x="' + p1.sx + '" y="' + p1.sy + '" width="' + (p2.sx - p1.sx) +
      '" height="' + (p2.sy - p1.sy) + '" rx="10" fill="' + b.color +
      '" stroke="' + b.edge + '" stroke-width="1" stroke-dasharray="6 4"/>')
    const st = statusOfZone[b.id]
    const label = b.name + (st ? ' · ' + st.statusText : '')
    const lp = project(b.x + 0.15, b.y + b.h - 0.35)
    out.push('<text x="' + lp.sx + '" y="' + lp.sy + '" fill="' +
      (st ? st.color : '#94a3b8') + '" font-size="15" font-weight="bold">' +
      esc(label) + '</text>')
  }

  /* 房间轮廓与固定障碍 */
  for (let i = 0; i < map.walls.length; i += 1) {
    const w = map.walls[i]
    const p1 = project(w.x, w.y + w.h)
    const p2 = project(w.x + w.w, w.y)
    out.push('<rect x="' + p1.sx + '" y="' + p1.sy + '" width="' + Math.max(1, p2.sx - p1.sx) +
      '" height="' + Math.max(1, p2.sy - p1.sy) + '" fill="rgba(203,213,225,0.55)"/>')
  }

  /* 四条固定路线：先画折线，再画航点 */
  const routeIds = CFG.ALL_ROUTE
  for (let r = 0; r < routeIds.length; r += 1) {
    const rid = routeIds[r]
    const pts = CFG.routePoints(rid)
    if (pts.length < 2) {
      continue
    }
    const zone = zones.filter(function (z) { return z.route === rid })[0]
    const color = zone ? zone.color : '#4DA3FF'
    const pl = []
    for (let i = 0; i < pts.length; i += 1) {
      const p = project(pts[i].x, pts[i].y)
      pl.push(p.sx + ',' + p.sy)
    }
    out.push('<polyline points="' + pl.join(' ') + '" fill="none" stroke="' + color +
      '" stroke-width="4" stroke-linejoin="round" stroke-linecap="round" opacity="0.85"/>')

    /* 航点：起点稍大，停留点用实心，过路点用小空心 */
    for (let i = 0; i < pts.length; i += 1) {
      const p = project(pts[i].x, pts[i].y)
      const isStart = i === 0
      const isStop = pts[i].dwell > 0
      const rr = isStart ? 5.5 : (isStop ? 4.5 : 3)
      out.push('<circle cx="' + p.sx + '" cy="' + p.sy + '" r="' + rr + '" fill="' +
        (isStop || isStart ? color : '#0e1729') + '" stroke="' + color + '" stroke-width="2"/>')
    }
  }

  /* 小车标记：位置 + 朝向（三角），在跑的车加一圈光晕 */
  const zoneIds = Object.keys(tasks)
  for (let i = 0; i < zoneIds.length; i += 1) {
    const zid = zoneIds[i]
    const t = tasks[zid]
    const st = statusOfZone[zid]
    if (!st) {
      continue
    }
    const p = project(t.x, t.y)
    const color = st.color
    /* yaw 是地图坐标系弧度；SVG 里 y 翻转，所以取负 */
    const deg = +(-(t.yaw || 0) * 180 / Math.PI).toFixed(1)
    if (st.status === 'running') {
      out.push('<circle cx="' + p.sx + '" cy="' + p.sy + '" r="16" fill="' + color +
        '" opacity="0.18"/>')
    }
    out.push('<g transform="translate(' + p.sx + ',' + p.sy + ') rotate(' + deg + ')">' +
      '<polygon points="11,0 -7,-8 -7,8" fill="' + color + '" stroke="#0b1220" stroke-width="1.5"/>' +
      '</g>')
    out.push('<text x="' + (p.sx + 15) + '" y="' + (p.sy - 10) + '" fill="' + color +
      '" font-size="14" font-weight="bold">' + esc(st.car) + '</text>')
  }

  /* 比例尺：1 米 */
  const s0 = project(bnd.x[0] + 0.4, bnd.y[0] + 0.35)
  const s1 = project(bnd.x[0] + 1.4, bnd.y[0] + 0.35)
  out.push('<line x1="' + s0.sx + '" y1="' + s0.sy + '" x2="' + s1.sx + '" y2="' + s1.sy +
    '" stroke="#94a3b8" stroke-width="3"/>')
  out.push('<text x="' + s0.sx + '" y="' + (s0.sy - 7) +
    '" fill="#94a3b8" font-size="13">1 m</text>')

  out.push('</svg>')
  return out.join('')
}

export default {
  SCREEN_W: SCREEN_W,
  SCREEN_H: SCREEN_H,
  MAP_LAYOUT: MAP_LAYOUT,
  ZONE_BLOCKS: ZONE_BLOCKS,
  makeProjector: makeProjector,
  renderMap: renderMap
}
