'use strict'

/**
 * 生成快应用图标资源（192x192 PNG，无第三方依赖）。
 *
 * 图标不使用字体渲染，全部由几何图形绘制，保证在任何环境下都能生成。
 * 生成结果放在 src/common/ 下，打包进 rpk。
 *
 * 用法：node tools/make-icons.js
 */

const fs = require('fs')
const path = require('path')
const zlib = require('zlib')

const SIZE = 192
const OUT_DIR = path.join(__dirname, '..', 'src', 'common')

/* ------------------------------------------------------------------ *
 * 画布：RGBA float 缓冲，方便做抗锯齿与圆角裁剪
 * ------------------------------------------------------------------ */
function createCanvas(size, color) {
  const px = new Float64Array(size * size * 4)
  for (let i = 0; i < size * size; i += 1) {
    px[i * 4] = color[0]
    px[i * 4 + 1] = color[1]
    px[i * 4 + 2] = color[2]
    px[i * 4 + 3] = color[3]
  }
  return px
}

/** 用 source-over 方式在 (x,y) 处混合一个颜色，alpha 为覆盖率 0..1 */
function blend(px, size, x, y, color, alpha) {
  if (x < 0 || y < 0 || x >= size || y >= size || alpha <= 0) {
    return
  }
  const a = Math.max(0, Math.min(1, alpha * color[3]))
  const i = (y * size + x) * 4
  const dst = [px[i], px[i + 1], px[i + 2], px[i + 3]]
  const out = []
  for (let c = 0; c < 3; c += 1) {
    out[c] = color[c] * a + dst[c] * (1 - a)
  }
  out[3] = a + dst[3] * (1 - a)
  px[i] = out[0]
  px[i + 1] = out[1]
  px[i + 2] = out[2]
  px[i + 3] = out[3]
}

/** 逐像素求值绘制，fn 返回该像素的颜色（null 表示透明） */
function paint(px, size, fn) {
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const c = fn(x + 0.5, y + 0.5)
      if (c) {
        blend(px, size, x, y, c.color, c.alpha)
      }
    }
  }
}

/* ------------------------------------------------------------------ *
 * 形状辅助：距离场 + 抗锯齿
 * ------------------------------------------------------------------ */
function coverage(dist, feather) {
  return Math.max(0, Math.min(1, 0.5 - dist / (feather || 1)))
}

function roundedRectDist(x, y, w, h, r) {
  const cx = Math.abs(x) - (w / 2 - r)
  const cy = Math.abs(y) - (h / 2 - r)
  const dx = Math.max(cx, 0)
  const dy = Math.max(cy, 0)
  return Math.sqrt(dx * dx + dy * dy) + Math.min(Math.max(cx, cy), 0) - r
}

function circleDist(x, y, cx, cy, r) {
  return Math.sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy)) - r
}

function ringDist(x, y, cx, cy, r, halfWidth) {
  return Math.abs(Math.sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy)) - r) - halfWidth
}

function segmentDist(x, y, ax, ay, bx, by, halfWidth) {
  const vx = bx - ax
  const vy = by - ay
  const wx = x - ax
  const wy = y - ay
  const len2 = vx * vx + vy * vy
  let t = len2 === 0 ? 0 : (wx * vx + wy * vy) / len2
  t = Math.max(0, Math.min(1, t))
  const dx = wx - t * vx
  const dy = wy - t * vy
  return Math.sqrt(dx * dx + dy * dy) - halfWidth
}

/* ------------------------------------------------------------------ *
 * 具体图标
 * ------------------------------------------------------------------ */

/** 圆角矩形底 + 纵向渐变 */
function makeBase(bg) {
  const px = createCanvas(SIZE, [0, 0, 0, 0])
  const half = SIZE / 2
  paint(px, SIZE, (x, y) => {
    const d = roundedRectDist(x - half, y - half, SIZE, SIZE, 44)
    if (d > 1) {
      return null
    }
    const t = y / SIZE
    const color = [
      bg[0] * (1 - t) + bg[3] * t,
      bg[1] * (1 - t) + bg[4] * t,
      bg[2] * (1 - t) + bg[5] * t,
      1
    ]
    return { color: color, alpha: coverage(d, 1) }
  })
  return px
}

/** VelaGuard：盾牌 + 扫描弧 */
function iconLogo() {
  const px = makeBase([0.18, 0.43, 0.96, 0.09, 0.26, 0.72])
  paint(px, SIZE, (x, y) => {
    // 盾牌：上宽下尖
    const shield = segmentDist(x, y, 96, 74, 96, 132, 30)
    const top = roundedRectDist(x - 96, y - 68, 72, 30, 12)
    let d = Math.min(shield, top)
    d = Math.max(d, 62 - y) // 裁掉顶部以上
    if (d > 1) {
      return null
    }
    const a = coverage(d, 1)
    // 挖出弧线纹理
    const arc1 = ringDist(x, y, 96, 104, 20, 3.2)
    const arc2 = ringDist(x, y, 96, 104, 34, 3.2)
    if (arc1 < 0 || arc2 < 0) {
      return { color: [1, 1, 1, 1], alpha: a * 0.32 }
    }
    return { color: [1, 1, 1, 1], alpha: a }
  })
  // 中心圆点
  paint(px, SIZE, (x, y) => {
    const d = circleDist(x, y, 96, 104, 9)
    if (d > 1) {
      return null
    }
    return { color: [1, 1, 1, 1], alpha: coverage(d, 1) }
  })
  return px
}

/** 语音助手：麦克风 */
function iconVoice() {
  const px = makeBase([0.05, 0.65, 0.64, 0.02, 0.42, 0.44])
  paint(px, SIZE, (x, y) => {
    const capsule = roundedRectDist(x - 96, y - 82, 46, 82, 23)
    if (capsule > 1) {
      return null
    }
    return { color: [1, 1, 1, 1], alpha: coverage(capsule, 1) }
  })
  // 下半圈拾音弧
  paint(px, SIZE, (x, y) => {
    const d = ringDist(x, y, 96, 84, 44, 6)
    if (d > 1 || y > 104) {
      return null
    }
    return { color: [1, 1, 1, 1], alpha: coverage(d, 1) }
  })
  // 支架与底座
  paint(px, SIZE, (x, y) => {
    const stem = segmentDist(x, y, 96, 126, 96, 146, 6)
    const base = segmentDist(x, y, 72, 148, 120, 148, 6)
    const d = Math.min(stem, base)
    if (d > 1) {
      return null
    }
    return { color: [1, 1, 1, 1], alpha: coverage(d, 1) }
  })
  return px
}

/** 巡检调度台：2x2 分区栅格 */
function iconDispatch() {
  const px = makeBase([0.18, 0.43, 0.96, 0.11, 0.27, 0.86])
  const cells = [
    [64, 64, 1.0],
    [128, 64, 0.72],
    [64, 128, 0.72],
    [128, 128, 1.0]
  ]
  cells.forEach(function (c) {
    paint(px, SIZE, (x, y) => {
      const d = roundedRectDist(x - c[0], y - c[1], 46, 46, 14)
      if (d > 1) {
        return null
      }
      return { color: [1, 1, 1, 1], alpha: coverage(d, 1) * c[2] }
    })
  })
  return px
}

/** 区域与路线：定位图钉 */
function iconZones() {
  const px = makeBase([0.49, 0.36, 1.0, 0.32, 0.22, 0.86])
  paint(px, SIZE, (x, y) => {
    const head = circleDist(x, y, 96, 78, 44)
    // 图钉尖端
    const tip = Math.max(
      Math.abs(x - 96) * 0.62 + (y - 82) * 0.62 - 8,
      82 - y
    )
    const d = Math.min(head, tip)
    if (d > 1) {
      return null
    }
    const a = coverage(d, 1)
    // 中空圆孔
    if (circleDist(x, y, 96, 78, 17) < 0) {
      return { color: [0.49, 0.36, 1.0, 1], alpha: a }
    }
    return { color: [1, 1, 1, 1], alpha: a }
  })
  return px
}

/** 巡检记录：剪贴板 */
function iconRecords() {
  const px = makeBase([0.96, 0.62, 0.04, 0.92, 0.44, 0.02])
  paint(px, SIZE, (x, y) => {
    const board = roundedRectDist(x - 96, y - 104, 108, 128, 18)
    if (board > 1) {
      return null
    }
    return { color: [1, 1, 1, 1], alpha: coverage(board, 1) }
  })
  // 顶部夹子
  paint(px, SIZE, (x, y) => {
    const clip = roundedRectDist(x - 96, y - 44, 60, 26, 10)
    if (clip > 1) {
      return null
    }
    return { color: [0.96, 0.62, 0.04, 1], alpha: coverage(clip, 1) }
  })
  // 文本行
  ;[92, 116, 140].forEach(function (ly, i) {
    paint(px, SIZE, (x, y) => {
      const w = i === 2 ? 34 : 62
      const line = segmentDist(x, y, 96 - w / 2, ly, 96 + w / 2, ly, 6)
      if (line > 1) {
        return null
      }
      return { color: [0.96, 0.62, 0.04, 1], alpha: coverage(line, 1) }
    })
  })
  return px
}

/** 系统与网络：齿轮 */
function iconSystem() {
  const px = makeBase([0.39, 0.45, 0.55, 0.24, 0.29, 0.39])
  const teeth = 8
  paint(px, SIZE, (x, y) => {
    const dx = x - 96
    const dy = y - 96
    const r = Math.sqrt(dx * dx + dy * dy)
    const ang = Math.atan2(dy, dx)
    // 齿：角度调制半径
    const mod = Math.cos(ang * teeth)
    const outer = 62 + (mod > 0.35 ? 12 : 0)
    const d = r - outer
    if (d > 1) {
      return null
    }
    // 中心孔
    if (r < 26) {
      return null
    }
    return { color: [1, 1, 1, 1], alpha: coverage(d, 1) }
  })
  return px
}

/* ------------------------------------------------------------------ *
 * PNG 编码（不依赖第三方库）
 * ------------------------------------------------------------------ */
function crc32(buf) {
  let c
  const table = crc32.table || (crc32.table = (function () {
    const t = []
    for (let n = 0; n < 256; n += 1) {
      c = n
      for (let k = 0; k < 8; k += 1) {
        c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
      }
      t[n] = c >>> 0
    }
    return t
  })())
  let crc = 0xffffffff
  for (let i = 0; i < buf.length; i += 1) {
    crc = table[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8)
  }
  return (crc ^ 0xffffffff) >>> 0
}

function chunk(type, data) {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length, 0)
  const typeBuf = Buffer.from(type, 'ascii')
  const body = Buffer.concat([typeBuf, data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(body), 0)
  return Buffer.concat([len, body, crc])
}

function encodePNG(px, size) {
  // 每行前置 filter byte 0
  const raw = Buffer.alloc(size * (size * 4 + 1))
  let o = 0
  for (let y = 0; y < size; y += 1) {
    raw[o] = 0
    o += 1
    for (let x = 0; x < size; x += 1) {
      const i = (y * size + x) * 4
      raw[o] = Math.round(Math.max(0, Math.min(255, px[i] * 255)))
      raw[o + 1] = Math.round(Math.max(0, Math.min(255, px[i + 1] * 255)))
      raw[o + 2] = Math.round(Math.max(0, Math.min(255, px[i + 2] * 255)))
      raw[o + 3] = Math.round(Math.max(0, Math.min(255, px[i + 3] * 255)))
      o += 4
    }
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 6 // RGBA
  ihdr[10] = 0
  ihdr[11] = 0
  ihdr[12] = 0
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0))
  ])
}

/* ------------------------------------------------------------------ *
 * 输出
 * ------------------------------------------------------------------ */
const ICONS = {
  'logo.png': iconLogo,
  'icon-voice.png': iconVoice,
  'icon-dispatch.png': iconDispatch,
  'icon-zones.png': iconZones,
  'icon-records.png': iconRecords,
  'icon-system.png': iconSystem
}

fs.mkdirSync(OUT_DIR, { recursive: true })
Object.keys(ICONS).forEach(function (name) {
  const px = ICONS[name]()
  const png = encodePNG(px, SIZE)
  const file = path.join(OUT_DIR, name)
  fs.writeFileSync(file, png)
  console.log('生成 ' + name + '  ' + png.length + ' bytes')
})
console.log('图标输出目录：' + OUT_DIR)
