"use strict"

/**
 * 读取 DSH 会话正文（zstd 多帧格式）。
 *
 * 格式真相（踩过坑，记下来）：
 *   ~/.dsh/sessions/<项目>/<会话ID>/session.v3.jsonl.zstd
 *   是**由多个 zstd 帧串接**而成的，不是单帧 —— 实测该文件含 4648 个
 *   `28 b5 2f fd` 魔数。直接对整个文件调 zstdDecompressSync 只会解出
 *   第一帧（1 行），看起来像"文件是空的"，很容易误判。
 *
 *   所以必须先找出所有帧边界，再逐帧解压后拼接。
 *
 * 用法：
 *   node tools/vnc/sessions.js --list              列出会话
 *   node tools/vnc/sessions.js --grep <关键词>      检索（默认带上下文）
 *   node tools/vnc/sessions.js --roles <ID前缀>     查看某会话的事件类型分布
 *   node tools/vnc/sessions.js --read <ID前缀> [n]  导出正文（默认前 n=400 条）
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const zlib = require("zlib")

const SESS_ROOT = path.join(os.homedir(), ".dsh", "sessions")
const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])

function findSessionFiles() {
  const out = []
  ;(function walk(dir) {
    let es = []
    try { es = fs.readdirSync(dir, { withFileTypes: true }) } catch (e) { return }
    for (const e of es) {
      const p = path.join(dir, e.name)
      if (e.isDirectory()) { walk(p) }
      else if (/session\.v3\.jsonl\.zstd$/.test(e.name)) { out.push(p) }
    }
  })(SESS_ROOT)
  return out
}

/** 找出所有 zstd 帧的起始偏移 */
function frameOffsets(buf) {
  const offs = []
  let i = 0
  while (i >= 0 && i < buf.length - 3) {
    const at = buf.indexOf(MAGIC, i)
    if (at < 0) { break }
    offs.push(at)
    i = at + 4
  }
  return offs
}

/** 逐帧解压并拼接 */
function decompressMultiFrame(buf) {
  const offs = frameOffsets(buf)
  if (!offs.length) {
    try { return { text: zlib.zstdDecompressSync(buf).toString("utf8"), frames: 1, bad: 0 } }
    catch (e) { return { text: "", frames: 0, bad: 1, error: e.message } }
  }
  const chunks = []
  let bad = 0
  for (let k = 0; k < offs.length; k += 1) {
    const start = offs[k]
    const end = (k + 1 < offs.length) ? offs[k + 1] : buf.length
    const slice = buf.slice(start, end)
    try {
      chunks.push(zlib.zstdDecompressSync(slice).toString("utf8"))
    } catch (e) {
      // 单帧失败不影响其它帧（尾部可能是半帧）
      bad += 1
    }
  }
  return { text: chunks.join(""), frames: offs.length, bad: bad }
}

function loadSession(file) {
  const buf = fs.readFileSync(file)
  const r = decompressMultiFrame(buf)
  const events = []
  for (const line of r.text.split("\n")) {
    const t = line.trim()
    if (!t) { continue }
    try { events.push(JSON.parse(t)) } catch (e) { /* 跳过坏行 */ }
  }
  return { frames: r.frames, bad: r.bad, events: events, text: r.text }
}

/** 递归收集字符串，拼成可读文本 */
function flatten(o, out, depth) {
  out = out || []
  depth = depth || 0
  if (depth > 8 || o === null || o === undefined) { return out }
  if (typeof o === "string") {
    if (o.trim().length > 1) { out.push(o) }
    return out
  }
  if (typeof o === "number" || typeof o === "boolean") { return out }
  if (Array.isArray(o)) { o.forEach(function (x) { flatten(x, out, depth + 1) }); return out }
  if (typeof o === "object") {
    for (const k of Object.keys(o)) { flatten(o[k], out, depth + 1) }
  }
  return out
}

function roleOf(ev) {
  return ev.role || ev.type || ev.kind || "?"
}

/* ------------------------------------------------------------------ */
const mode = process.argv[2] || "--list"
const arg = process.argv[3] || ""
const extra = Number(process.argv[4] || 400)
const files = findSessionFiles().sort(function (a, b) {
  return fs.statSync(b).size - fs.statSync(a).size
})

if (mode === "--list") {
  console.log("=== DSH 会话（按体积降序）===\n")
  for (const f of files) {
    const id = path.basename(path.dirname(f))
    const sz = (fs.statSync(f).size / 1024 / 1024).toFixed(2)
    const mt = fs.statSync(f).mtime.toISOString().slice(0, 16)
    console.log("  " + id + "   " + sz + " MB   " + mt)
  }
  process.exit(0)
}

if (mode === "--roles") {
  const f = files.filter(function (x) { return path.dirname(x).indexOf(arg) >= 0 })[0]
  if (!f) { console.log("未找到: " + arg); process.exit(1) }
  const s = loadSession(f)
  console.log("帧数 " + s.frames + "（解压失败 " + s.bad + "）  事件 " + s.events.length)
  const dist = {}
  s.events.forEach(function (e) { const k = roleOf(e); dist[k] = (dist[k] || 0) + 1 })
  Object.keys(dist).sort(function (a, b) { return dist[b] - dist[a] })
    .forEach(function (k) { console.log("  " + k + ": " + dist[k]) })
  console.log("\n首事件键: " + JSON.stringify(Object.keys(s.events[0] || {})))
  process.exit(0)
}

if (mode === "--read") {
  const f = files.filter(function (x) { return path.dirname(x).indexOf(arg) >= 0 })[0]
  if (!f) { console.log("未找到: " + arg); process.exit(1) }
  const s = loadSession(f)
  console.log("=== " + arg + "  帧 " + s.frames + "  事件 " + s.events.length + " ===\n")
  s.events.slice(0, extra).forEach(function (e, i) {
    const txt = flatten(e).join("\n").trim()
    if (!txt) { return }
    console.log("──── [" + i + "] " + roleOf(e) + " ────")
    console.log(txt.slice(0, 3000))
    console.log()
  })
  process.exit(0)
}

if (mode === "--grep") {
  const kw = arg
  if (!kw) { console.log("请提供关键词"); process.exit(1) }
  console.log("=== 检索: " + kw + " ===\n")
  let sessionsHit = 0
  let totalHits = 0
  for (const f of files) {
    const s = loadSession(f)
    const id = path.basename(path.dirname(f))
    const found = []
    s.events.forEach(function (e, i) {
      const txt = flatten(e).join("\n")
      if (txt.indexOf(kw) >= 0) {
        found.push({ i: i, role: roleOf(e), txt: txt })
      }
    })
    if (!found.length) { continue }
    sessionsHit += 1
    totalHits += found.length
    console.log("【" + id + "】 命中 " + found.length + " 条事件")
    found.slice(0, 8).forEach(function (h) {
      // 抽取关键词附近的片段，便于快速理解
      const p = h.txt.indexOf(kw)
      const seg = h.txt.slice(Math.max(0, p - 150), p + 250).replace(/\s+/g, " ")
      console.log("  [" + h.i + "] " + h.role + ": …" + seg + "…")
    })
    console.log()
  }
  console.log("命中 " + sessionsHit + " 个会话，共 " + totalHits + " 条事件")
  process.exit(0)
}

console.log("用法: --list | --grep <kw> | --read <id> [n] | --roles <id>")
