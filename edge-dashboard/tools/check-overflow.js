"use strict"

/**
 * 检查各页面在目标分辨率下是否溢出（内容超出 1920x1080）。
 *
 * 为什么需要：把 VoiceAssistant / Records / System 从 1280 基准放大到 1920 后，
 * 可能出现内容撑破屏幕（底部队列/按钮被挤出可视区）。这必须用 DOM 实测，
 * 不能靠肉眼看截图。
 *
 * 判据：页面根节点 scrollHeight > clientHeight 即溢出。
 *
 * 用法：node tools/check-overflow.js
 */

const fs = require("fs")
const path = require("path")
const net = require("net")
const http = require("http")
const crypto = require("crypto")
const os = require("os")
const { spawn } = require("child_process")

const ROOT = path.join(__dirname, "..")
const PREVIEW = path.join(ROOT, "preview", "index.html")
const PORT = 18950
const DESIGN_H = 1080

const CHROME = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
].filter(function (p) { return fs.existsSync(p) })[0]

let passed = 0
let failed = 0

function check(name, ok, detail) {
  if (ok) { passed += 1; console.log("  \u2713 " + name) }
  else { failed += 1; console.log("  \u2717 " + name + (detail ? "  → " + detail : "")) }
}

function getJSON(url) {
  return new Promise(function (resolve, reject) {
    http.get(url, function (res) {
      let d = ""
      res.on("data", function (c) { d += c })
      res.on("end", function () { try { resolve(JSON.parse(d)) } catch (e) { reject(e) } })
    }).on("error", reject)
  })
}

function connectWS(wsUrl) {
  return new Promise(function (resolve, reject) {
    const u = new URL(wsUrl)
    const key = crypto.randomBytes(16).toString("base64")
    const sock = net.connect(Number(u.port), u.hostname, function () {
      sock.write("GET " + u.pathname + " HTTP/1.1\r\nHost: " + u.host +
        "\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: " + key +
        "\r\nSec-WebSocket-Version: 13\r\n\r\n")
    })
    let buf = Buffer.alloc(0)
    let hs = false
    const L = []
    sock.on("data", function (chunk) {
      buf = Buffer.concat([buf, chunk])
      if (!hs) {
        const i = buf.indexOf("\r\n\r\n")
        if (i < 0) { return }
        buf = buf.slice(i + 4)
        hs = true
        resolve({ send: send, on: function (f) { L.push(f) }, close: function () { sock.destroy() } })
      }
      for (;;) {
        if (buf.length < 2) { return }
        let len = buf[1] & 0x7f
        let off = 2
        if (len === 126) { if (buf.length < 4) { return } len = buf.readUInt16BE(2); off = 4 }
        else if (len === 127) { if (buf.length < 10) { return } len = Number(buf.readBigUInt64BE(2)); off = 10 }
        if (buf.length < off + len) { return }
        const p = buf.slice(off, off + len)
        buf = buf.slice(off + len)
        L.forEach(function (f) { f(p.toString("utf8")) })
      }
    })
    sock.on("error", reject)
    function send(str) {
      const d = Buffer.from(str, "utf8")
      const m = crypto.randomBytes(4)
      let h
      if (d.length < 126) { h = Buffer.alloc(2); h[1] = 0x80 | d.length }
      else if (d.length < 65536) { h = Buffer.alloc(4); h[1] = 0x80 | 126; h.writeUInt16BE(d.length, 2) }
      else { h = Buffer.alloc(10); h[1] = 0x80 | 127; h.writeBigUInt64BE(BigInt(d.length), 2) }
      h[0] = 0x81
      const x = Buffer.alloc(d.length)
      for (let i = 0; i < d.length; i += 1) { x[i] = d[i] ^ m[i % 4] }
      sock.write(Buffer.concat([h, m, x]))
    }
  })
}

async function main() {
  const server = http.createServer(function (req, res) {
    const u = req.url.split("?")[0]
    if (u === "/preview/index.html") {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" })
      res.end(fs.readFileSync(PREVIEW))
      return
    }
    res.writeHead(404); res.end("no")
  })
  await new Promise(function (r) { server.listen(PORT, "127.0.0.1", r) })

  const userDir = path.join(os.tmpdir(), "vgover-" + Date.now())
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars",
    "--remote-debugging-port=9410", "--user-data-dir=" + userDir,
    "--window-size=1920,1080", "--no-first-run", "about:blank"], { stdio: "ignore" })

  let targets = null
  for (let i = 0; i < 40; i += 1) {
    try { targets = await getJSON("http://127.0.0.1:9410/json/list"); if (targets.length) { break } } catch (e) {}
    await new Promise(function (r) { setTimeout(r, 250) })
  }
  const page = targets.filter(function (t) { return t.type === "page" })[0]
  const ws = await connectWS(page.webSocketDebuggerUrl)
  let id = 0
  const waiters = {}
  ws.on(function (raw) {
    const m = JSON.parse(raw)
    if (m.id && waiters[m.id]) { waiters[m.id](m); delete waiters[m.id] }
  })
  function cmd(method, params) {
    id += 1
    const i = id
    return new Promise(function (r) { waiters[i] = r; ws.send(JSON.stringify({ id: i, method: method, params: params || {} })) })
  }
  async function ev(expr) {
    const r = await cmd("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })
    return r.result && r.result.result ? r.result.result.value : undefined
  }

  await cmd("Runtime.enable")
  await cmd("Page.enable")
  // 设成设备真实分辨率，且 kiosk 模式
  await cmd("Emulation.setDeviceMetricsOverride", {
    width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false
  })
  await cmd("Page.navigate", { url: "http://127.0.0.1:" + PORT + "/preview/index.html#kiosk" })
  await new Promise(function (r) { setTimeout(r, 2500) })

  const pages = ["Home", "VoiceAssistant", "Dispatch", "Zones", "Records", "System"]

  console.log("=== 各页面在 1920x1080 下的溢出检查 ===")
  console.log("判据：页面根节点 scrollHeight 不得超过 clientHeight（允许 2px 误差）\n")

  for (const p of pages) {
    const r = await ev(
      "window.__velaguard.build(" + JSON.stringify(p) + ");" +
      "(function(){" +
      " var root = document.getElementById('root');" +
      " var screen = root.querySelector('.screen') || root.firstElementChild;" +
      " var rr = root.getBoundingClientRect();" +
      " var sr = screen ? screen.getBoundingClientRect() : null;" +
      " return JSON.stringify({" +
      "   rootClient: root.clientHeight," +
      "   rootScroll: root.scrollHeight," +
      "   screenH: sr ? Math.round(sr.height) : -1," +
      "   screenClient: screen ? screen.clientHeight : -1," +
      "   screenScroll: screen ? screen.scrollHeight : -1" +
      " })" +
      "})()"
    )
    const info = JSON.parse(r || "{}")
    const overflowRoot = info.rootScroll > info.rootClient + 2
    const overflowScreen = info.screenScroll > info.screenClient + 2

    check(p + " 未溢出（根 " + info.rootScroll + "/" + info.rootClient +
      "，屏 " + info.screenScroll + "/" + info.screenClient + "）",
      !overflowRoot && !overflowScreen,
      overflowScreen ? "内容超出屏幕 " + (info.screenScroll - info.screenClient) + "px" : "")
  }

  /* 语音助手专项：触控可滑动面积的实测高度 */
  console.log("\n=== 语音助手：聊天区可滑动面积 ===")
  await ev('window.__velaguard.build("VoiceAssistant")')
  const chat = await ev(
    "(function(){" +
    " var c = document.querySelector('#root .chat');" +
    " if (!c) return JSON.stringify({found:false});" +
    " var r = c.getBoundingClientRect();" +
    " return JSON.stringify({found:true, h: Math.round(r.height), w: Math.round(r.width)," +
    "   scrollH: c.scrollHeight, clientH: c.clientHeight})" +
    "})()"
  )
  const ci = JSON.parse(chat || "{}")
  if (ci.found) {
    // 经验阈值：手机上可流畅滑动的手势区通常不低于 300px；这里要求更高
    check("聊天区高度 " + ci.h + "px（要求 ≥ 560px，手指易滑动）", ci.h >= 560,
      "过小会导致难以滑动手势")
    check("聊天区宽度 " + ci.w + "px（应为整屏宽）", ci.w >= 1800, "宽度异常")
  } else {
    check("找到聊天区元素", false, "未找到 .chat")
  }

  ws.close(); chrome.kill(); server.close()
}

main()
  .catch(function (e) { failed += 1; console.error("失败: " + e.message) })
  .then(function () {
    console.log("\n─────────────────────────────")
    console.log("溢出检查：" + passed + " 通过，" + failed + " 失败")
    process.exit(failed > 0 ? 1 : 0)
  })
