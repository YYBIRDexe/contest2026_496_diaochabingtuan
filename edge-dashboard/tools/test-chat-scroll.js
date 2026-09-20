"use strict"

/**
 * 验证会话区滚动行为（真机问题的回归测试）。
 *
 * 用户报的两个现象：
 *   1. 聊天记录自己跳回顶部 —— 根因是 doRender() 整棵 DOM 重建，滚动位置归零
 *   2. 右侧滑动很难 —— 需要足够的可滑动面积与触控滚动支持
 *
 * 本测试用 DOM 实测，而不是看截图：
 *   a) 灌入多条消息使内容溢出
 *   b) 滚到中间，再推一条新消息（触发重建），看位置是否被保留
 *   c) 滚到底部，再推一条，看是否自动跟随到底
 *   d) 量可滑动区域的高度
 *
 * 用法：node tools/test-chat-scroll.js
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
const PORT = 18960

const CHROME = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
].filter(function (p) { return fs.existsSync(p) })[0]

function sleepMs(ms) {
  return new Promise(function (r) { setTimeout(r, ms) })
}

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

/** 往假语音服务里塞一条「设备侧记录」（模拟唤醒词触发的那一轮／迟到的识别结果） */
function postJSON(url, obj) {
  return new Promise(function (resolve, reject) {
    const body = Buffer.from(JSON.stringify(obj), "utf8")
    const u = new URL(url)
    const req = http.request({
      hostname: u.hostname, port: u.port, path: u.pathname, method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": body.length }
    }, function (res) {
      let d = ""
      res.on("data", function (c) { d += c })
      res.on("end", function () { resolve(d) })
    })
    req.on("error", reject)
    req.end(body)
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
  /*
   * 起一个假语音服务（127.0.0.1:8124），让「说话」按键的两段式走到成功路径。
   * 没有它的话，第一段只会以「连接被拒绝」失败 —— 那是正确行为，
   * 但测不出「按下即变状态」和「第二次按下出结果」这两条关键交互。
   *
   * stdio 全部接到 ignore：父进程不需要它的输出，也避开沙箱里
   * 「管道被子进程继承」的限制。
   */
  const fakeBridge = spawn(process.execPath,
    [path.join(ROOT, "tools", "fake-speech-bridge.js"), "8124"],
    { stdio: "ignore" })

  /*
   * 等假服务真的起来再继续。只 sleep 是不够的 —— 端口没监听时
   * 界面会走进「起不来」分支，测试会得到一堆看不懂的失败
   * （之前就是这个坑：假服务没起，跑了 6 个假失败）。
   */
  let fakeUp = false
  for (let i = 0; i < 30; i += 1) {
    try {
      const h = await getJSON("http://127.0.0.1:8124/api/health")
      if (h && h.ok) { fakeUp = true; break }
    } catch (e) { /* 还没起来 */ }
    await sleepMs(200)
  }
  console.log("假语音服务：" + (fakeUp ? "已就绪（127.0.0.1:8124）" : "未启动（按键测试会退化）") + "\n")

  const server = http.createServer(function (req, res) {
    if (req.url.split("?")[0] === "/preview/index.html") {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" })
      res.end(fs.readFileSync(PREVIEW))
      return
    }
    res.writeHead(404); res.end("no")
  })
  await new Promise(function (r) { server.listen(PORT, "127.0.0.1", r) })

  const userDir = path.join(os.tmpdir(), "vgscroll-" + Date.now())
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars",
    "--remote-debugging-port=9420", "--user-data-dir=" + userDir,
    "--window-size=1920,1080", "--no-first-run", "about:blank"], { stdio: "ignore" })

  let targets = null
  for (let i = 0; i < 40; i += 1) {
    try { targets = await getJSON("http://127.0.0.1:9420/json/list"); if (targets.length) { break } } catch (e) {}
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
    if (r.result && r.result.exceptionDetails) { return "ERR: " + JSON.stringify(r.result.exceptionDetails) }
    return r.result && r.result.result ? r.result.result.value : undefined
  }
  const sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms) }) }

  await cmd("Runtime.enable")
  await cmd("Page.enable")
  await cmd("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false })
  await cmd("Page.navigate", { url: "http://127.0.0.1:" + PORT + "/preview/index.html#kiosk,voice" })
  await sleep(2600)

  console.log("=== 会话区滚动行为测试 ===\n")

  /* --- 确认页面对了 --- */
  const curPage = await ev('document.getElementById("root").getAttribute("data-page")')
  check("已进入语音助手页", curPage === "VoiceAssistant", String(curPage))

  /* --- 标记是否存在 --- */
  const hasMark = await ev('!!document.querySelector("#root .chat[data-auto-bottom]")')
  check("会话区带 data-auto-bottom 标记", hasMark === true, String(hasMark))

  /* --- 灌入足够多的消息，让内容溢出 ---
   * 用页面自己的 pushMessage 循环追加：这既是真实加消息的代码路径，
   * 也避开了宿主桩件的一个坑 —— 实测把整个数组赋给 proxy
   * （d.messages = [...]）数据会变但 DOM 不重绘，pushMessage 则正常。 */
  const seedResult = await ev(
    "(function(){" +
    " var d = window.__velaguard.getData();" +
    " if (!d || typeof d.pushMessage !== 'function') return 'no-pushMessage';" +
    " for (var i = 0; i < 18; i++) {" +
    "   d.pushMessage(i % 2 ? '助手' : '你'," +
    "     '测试消息第 ' + (i+1) + ' 条：这是一段用于把会话区撑到可滚动的较长文本内容，' +" +
    "     '确保内容高度明显超过容器高度。', i % 2 === 1);" +
    " }" +
    " return (window.__velaguard.getData().messages || []).length;" +
    " })()"
  )
  await sleep(900)
  const bubbleAfterSeed = await ev("document.querySelectorAll('#root .chat .bubble').length")
  console.log("  (注入后 messages=" + seedResult + "，气泡=" + bubbleAfterSeed + ")\n")

  const geo = await ev(
    "(function(){" +
    " var c = document.querySelector('#root .chat');" +
    " if (!c) return JSON.stringify({found:false});" +
    " var r = c.getBoundingClientRect();" +
    " return JSON.stringify({found:true, h: Math.round(r.height), w: Math.round(r.width)," +
    "   scrollH: c.scrollHeight, clientH: c.clientHeight, top: Math.round(c.scrollTop)});" +
    " })()"
  )
  const g = JSON.parse(geo || "{}")
  check("会话区内容已溢出（可滚动）", g.scrollH > g.clientH + 20,
    "scrollH=" + g.scrollH + " clientH=" + g.clientH)
  check("会话区高度 ≥ 560px（触控易滑动）", g.h >= 560, g.h + "px")
  check("会话区宽度接近满屏", g.w >= 1800, g.w + "px")

  /* --- 场景 A：滚到中间 → 推新消息 → 位置应保留 ---
   *
   * ⚠️ 必须用 __velaguard.patch 改数据（走 Proxy）。直接改 getData() 拿到的
   * 对象不触发重渲染 —— 那样断言会「永远成立」，因为 DOM 根本没变过。 */
  await ev("document.querySelector('#root .chat').scrollTop = 120")
  await sleep(300)
  const before = await ev("Math.round(document.querySelector('#root .chat').scrollTop)")
  const bubblesBeforeA = await ev("document.querySelectorAll('#root .chat .bubble').length")
  await ev(
    "(function(){ var d = window.__velaguard.getData();" +
    " var l = d.messages.slice();" +
    " l.push({role:'助手', text:'新增一条用于测试滚动保持的消息。', bubbleStyle:'background-color: #1d2a44', roleStyle:'color: #4da3ff'});" +
    " return window.__velaguard.patch({messages: l}); })()"
  )
  await sleep(700)
  const afterMid = await ev("Math.round(document.querySelector('#root .chat').scrollTop)")
  const bubblesAfterA = await ev("document.querySelectorAll('#root .chat .bubble').length")
  check("新消息确实渲染了（" + bubblesBeforeA + " -> " + bubblesAfterA + " 条气泡）",
    bubblesAfterA === bubblesBeforeA + 1, bubblesBeforeA + " -> " + bubblesAfterA)
  check("上翻时新增消息不会跳回顶部（" + before + " -> " + afterMid + "）",
    Math.abs(afterMid - before) <= 30, "差值 " + (afterMid - before))

  /* --- 场景 B：滚到底部 → 推新消息 → 应自动跟随 --- */
  await ev(
    "(function(){ var c = document.querySelector('#root .chat');" +
    " c.scrollTop = c.scrollHeight; return 1; })()"
  )
  await sleep(400)
  const atBottomBefore = await ev(
    "(function(){ var c = document.querySelector('#root .chat');" +
    " return (c.scrollHeight - c.scrollTop - c.clientHeight) < 24; })()"
  )
  check("能滚到底部", atBottomBefore === true, String(atBottomBefore))

  await ev(
    "(function(){ var d = window.__velaguard.getData();" +
    " var l = d.messages.slice();" +
    " l.push({role:'助手', text:'这条进来后应自动滚到底部。', bubbleStyle:'background-color: #1d2a44', roleStyle:'color: #4da3ff'});" +
    " return window.__velaguard.patch({messages: l}); })()"
  )
  await sleep(700)
  const stillBottom = await ev(
    "(function(){ var c = document.querySelector('#root .chat');" +
    " return (c.scrollHeight - c.scrollTop - c.clientHeight) < 24; })()"
  )
  check("在底部时新消息自动跟随下滚", stillBottom === true, String(stillBottom))

  /* --- 场景 D：按键「按下即响应」 ---
   * 「按住说话」必须按下就有反馈。这里的验证方式是发一次 CDP 按下事件，
   * 不发抬起 —— 如果状态已经变了，说明是「按下」触发的而不是「抬起后的 click」。
   * 只验证到「开始听」为止：第二段会真的去连 127.0.0.1:8124，测试环境没这个服务。 */
  const idleState = await ev(
    "JSON.stringify((function(){var d=window.__velaguard.getData();" +
    "return {micText:d.micText, listening:d.listening, busy:d.busy}})())"
  )
  check("按键初始为待机（显示「说话」）", JSON.parse(idleState).micText === '说话', idleState)

  const micBox = await ev(
    "JSON.stringify((function(){var n=document.querySelector('#root .mic');" +
    "if(!n)return null;var r=n.getBoundingClientRect();" +
    "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}})())"
  )
  const mb = JSON.parse(micBox || 'null')
  check("找得到「说话」按键", !!mb, String(micBox))
  if (mb) {
    /* 第一段要等假服务那 900ms 的延迟（模拟真机停唤醒引擎的耗时），
     * 所以采样点放在 1.2 秒：太早会采到「正在启动」这个中间态。 */
    await cmd("Input.dispatchMouseEvent",
      { type: "mousePressed", x: mb.x, y: mb.y, button: "left", clickCount: 1 })
    await sleep(1250)
    const pressed = await ev(
      "JSON.stringify((function(){var d=window.__velaguard.getData();" +
      "return {micText:d.micText, listening:d.listening, hint:d.hint," +
      " style:d.micStyle}})())"
    )
    const pr = JSON.parse(pressed)
    console.log("  (按下后状态 " + pressed + ")")
    check("按下（未抬起）按键即变「结束」", pr.micText === '结束', pressed)
    check("按下后进入 listening 状态", pr.listening === true, pressed)
    check("按下后按钮变色提示", String(pr.style).indexOf('F59E0B') >= 0, String(pr.style))

    /* 确认已经处于「正在听」再按第二次 —— 否则第二下会被 busy 守卫忽略，
     * 得到一堆看不懂的失败（这类时序脆弱点要显式等到位）。 */
    let ready = false
    for (let i = 0; i < 40; i += 1) {
      const st = await ev("window.__velaguard.getData().listening === true")
      if (st === true) { ready = true; break }
      await sleep(150)
    }
    check("已进入可结束状态", ready === true, "listening 未置位")

    /* --- 场景 E：第二次按下 → 立即结束并回填结果 --- */
    await cmd("Input.dispatchMouseEvent",
      { type: "mouseReleased", x: mb.x, y: mb.y, button: "left", clickCount: 1 })
    await sleep(150)
    await cmd("Input.dispatchMouseEvent",
      { type: "mousePressed", x: mb.x, y: mb.y, button: "left", clickCount: 1 })
    await sleep(1200)
    const stopped = await ev(
      "JSON.stringify((function(){var d=window.__velaguard.getData();" +
      "var m=d.messages||[];return {micText:d.micText, busy:d.busy, listening:d.listening," +
      " last:m.length?m[m.length-1].text:'', lastRole:m.length?m[m.length-1].role:''}})())"
    )
    const st2 = JSON.parse(stopped)
    console.log("  (第二次按下后 " + stopped + ")")
    check("第二次按下后回到待机（显示「说话」）", st2.micText === '说话', stopped)
    check("第二次按下后结束 listening", st2.listening === false, stopped)
    check("识别结果已回填会话区", st2.last === '收到，前进半米', stopped)
    await cmd("Input.dispatchMouseEvent",
      { type: "mouseReleased", x: mb.x, y: mb.y, button: "left", clickCount: 1 })
    await sleep(200)
  }

  /* --- 场景 F（先跑）：消息确实渲染出来了 ---
   * 1 条初始问候 + 追加的 18 条 + 语音这一轮的 2 条（你说 + 助手说）。 */
  const bubbleCount = await ev("document.querySelectorAll('#root .chat .bubble').length")
  check("消息气泡已渲染（" + bubbleCount + " 条，含初始问候）",
    bubbleCount >= 19, String(bubbleCount))

  /* --- 场景 G：内容「第一次」撑出滚动条时必须贴底 ---
   *
   * 这是用户第二次报的同一句话：「弹出新的文字后依旧没有自动下滑」。
   *
   * 根因在框架层：snapshotScroll() 以前只快照**已经能滚**的容器，
   * 于是「首次溢出」那一次快照是空的 → restoreScroll() 直接 return →
   * 新消息进来了却停在顶部。
   *
   * 测法要点：先重建页面拿到「一条消息、还不需要滚动」的初始状态，
   * 然后**直接改数据**（绕开页面自己的 pushMessage）把内容撑到溢出 ——
   * 这样唯一可能把滚动条放到底部的就只有框架层。
   * 之所以能同步读到结果：框架的重建是同步的，而页面的滚动挂在
   * requestAnimationFrame 上，这一刻还没轮到它。 */
  await ev('window.__velaguard.build("VoiceAssistant")')
  await sleep(900)
  const startGeom = await ev(
    "(function(){" +
    " var c = document.querySelector('#root .chat');" +
    " return c.scrollHeight > c.clientHeight + 2;" +
    " })()"
  )
  const growResult = await ev(
    "(function(){" +
    " var d = window.__velaguard.getData();" +
    " var l = (d.messages || []).slice();" +
    " for (var i = 0; i < 18; i++) {" +
    "   l.push({role:'助手', text:'撑出滚动条的第 ' + (i+1) + ' 条：' +" +
    "     '这是一段足够长的文本，用来把会话区顶到必须滚动的高度。'," +
    "     bubbleStyle:'background-color: #1d2a44', roleStyle:'color: #4da3ff'});" +
    " }" +
    " window.__velaguard.patch({messages: l});" +
    " return (d.messages || []).length;" +
    " })()"
  )
  await sleep(700)
  const grown = await ev(
    "(function(){" +
    " var c = document.querySelector('#root .chat');" +
    " return JSON.stringify({overflow: c.scrollHeight > c.clientHeight + 20," +
    "   gap: c.scrollHeight - c.scrollTop - c.clientHeight," +
    "   top: Math.round(c.scrollTop), bubbles:" +
    "   document.querySelectorAll('#root .chat .bubble').length});" +
    " })()"
  )
  const go2 = JSON.parse(grown || "{}")
  check("重建后是「还不需要滚动」的初始状态", startGeom === false, String(startGeom))
  check("首次撑出滚动条时自动贴底（框架层还原）",
    go2.overflow === true && go2.gap < 24,
    "gap=" + go2.gap + " top=" + go2.top + " bubbles=" + go2.bubbles +
    " messages=" + growResult)
  await sleep(200)

  /* --- 场景 H：设备侧新记录（界面没参与的那一轮）要自己出现 ---
   *
   * 模拟两种真实情况：
   *   · 喊唤醒词触发的一轮（界面根本不知道）
   *   · 云端识别几十秒后才出结果
   * 界面靠 /api/voice/records 轮询把它捞出来并贴底。 */
  await ev('window.__velaguard.build("VoiceAssistant")')
  await sleep(1200)                       // 等首次对游标（primeRecords）落定
  await postJSON("http://127.0.0.1:8124/__push", {
    text: "四辆小车都连上了吗？", said: "小车都联系不上", intent: "car_check"
  })
  const beforePoll = await ev("document.querySelectorAll('#root .chat .bubble').length")
  let polled = null
  for (let i = 0; i < 20; i += 1) {
    await sleep(500)
    polled = await ev(
      "JSON.stringify((function(){" +
      " var bs = document.querySelectorAll('#root .chat .bubble');" +
      " var last = bs.length ? bs[bs.length-1] : null;" +
      " var c = document.querySelector('#root .chat');" +
      " return {n: bs.length, lastText: last ? last.textContent : ''," +
      "   gap: c.scrollHeight - c.scrollTop - c.clientHeight," +
      "   lastSeq: window.__velaguard.getData().lastSeq};" +
      "})())"
    )
    const p = JSON.parse(polled || "{}")
    if (p.n >= beforePoll + 2) { break }
  }
  const pp = JSON.parse(polled || "{}")
  check("设备侧新记录会自动出现在会话区（" + beforePoll + " -> " + pp.n + " 条气泡）",
    pp.n >= beforePoll + 2, polled)
  check("轮询进来的消息内容是设备的播报（" + pp.lastText + "）",
    String(pp.lastText).indexOf('小车都联系不上') >= 0, String(pp.lastText))
  check("轮询进来后会自动贴底", pp.gap < 24, "gap=" + pp.gap)

  ws.close(); chrome.kill(); server.close()
  if (fakeBridge && !fakeBridge.killed) { fakeBridge.kill() }
}

main()
  .catch(function (e) { failed += 1; console.error("失败: " + e.message) })
  .then(function () {
    console.log("\n─────────────────────────────")
    console.log("会话区滚动测试：" + passed + " 通过，" + failed + " 失败")
    process.exit(failed > 0 ? 1 : 0)
  })
