'use strict'

/**
 * 运行时测试：把界面加载进无头浏览器，验证「编译产物真的能跑」。
 *
 * 覆盖内容：
 *   1. 页面加载：无 JS 异常、根节点渲染成功
 *   2. 六个页面逐个构建：都有非空渲染结果
 *   3. 数据源切换：demo / file / sim 三态可用，切换后界面同步变化
 *   4. 交互：磁贴跳转、预设指令、派单
 *   5. 真实数据链路：注入一份 state.json，验证界面按外部数据渲染
 *   6. 离线自包含：产物不含任何外部请求
 *
 * 用法：node tools/test.js
 */

const fs = require('fs')
const path = require('path')
const net = require('net')
const http = require('http')
const crypto = require('crypto')
const os = require('os')
const { spawn } = require('child_process')

const ROOT = path.join(__dirname, '..')
const PREVIEW = path.join(ROOT, 'preview', 'index.html')

const CHROME = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
].filter(function (p) { return fs.existsSync(p) })[0]

let passed = 0
let failed = 0

function check(name, ok, detail) {
  if (ok) {
    passed += 1
    console.log('  \u2713 ' + name)
  } else {
    failed += 1
    console.log('  \u2717 ' + name + (detail ? '  → ' + detail : ''))
  }
}

/* ---------------- 静态检查：产物必须自包含 ---------------- */
function staticChecks() {
  console.log('\n[1] 产物自包含（离线可用）')

  if (!fs.existsSync(PREVIEW)) {
    check('preview/index.html 存在', false, '请先运行 node tools/build-preview.js')
    return
  }
  const html = fs.readFileSync(PREVIEW, 'utf8')

  check('产物存在且非空', html.length > 10000, html.length + ' bytes')

  /*
   * 原规则是「不得出现任何 http(s)://」，本意是保证界面不依赖外部网络。
   * 但语音助手需要连本机的离线语音服务（127.0.0.1:8124），这属于本机回环，
   * 不是外部依赖，而且服务不可用时界面会优雅降级。所以规则改为
   * 「不得引用外部主机」：允许 localhost / 127.0.0.1 / ::1，其余一律禁止。
   */
  const urls = html.match(/https?:\/\/[^\s"'`)<>]+/g) || []
  const external = urls.filter(function (u) {
    return !/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(\/|$)/.test(u)
  })
  check('无外部主机引用（允许本机回环）',
    external.length === 0,
    external.length ? '发现外部引用: ' + external.slice(0, 3).join(', ') : '')

  check('无 src= 外部资源', !/\ssrc="/.test(html))
  check('无 import 语句', !/^\s*import\s/m.test(html))
  check('store 已内联', html.indexOf('function summarize') >= 0)
  check('source 适配层已内联', html.indexOf('function createSource') >= 0)
  check('图标已 base64 内联', html.indexOf('data:image/png;base64,') >= 0)
}

/* ---------------- 起一个本地服务，便于 fetch 链路测试 ---------------- */
let server = null
let PORT = 0

const STATE_JSON = {
  zones: [
    { id: 'Z1', name: '入口大厅', route: 'R-01', routeDesc: '前台 → 闸机', car: 'CAR-1', status: 'done', progress: 100, detail: '真实数据：无异常' },
    { id: 'Z2', name: '主通道', route: 'R-02', routeDesc: 'A → B', car: 'CAR-2', status: 'blocked', progress: 40, detail: '真实数据：有障碍' },
    { id: 'Z3', name: '展项区', route: 'R-03', routeDesc: '展台 1→4', car: 'CAR-3', status: 'idle', progress: 0, detail: '真实数据：未开始' },
    { id: 'Z4', name: '设备区', route: 'R-04', routeDesc: '配电柜', car: 'CAR-4', status: 'idle', progress: 0, detail: '真实数据：未开始' }
  ],
  cars: [
    { id: 'CAR-1', zone: '入口大厅', ip: '10.0.0.11', online: true, battery: 90 },
    { id: 'CAR-2', zone: '主通道', ip: '10.0.0.12', online: true, battery: 80 },
    { id: 'CAR-3', zone: '展项区', ip: '10.0.0.13', online: false, battery: 0 },
    { id: 'CAR-4', zone: '设备区', ip: '10.0.0.14', online: true, battery: 70 }
  ],
  records: [{ round: '真实轮次', time: '刚刚', zones: [{ name: '入口大厅', result: 'done' }], summary: '来自 state.json' }]
}

function startServer() {
  return new Promise(function (resolve) {
    PORT = 18923
    server = http.createServer(function (req, res) {
      const url = req.url.split('?')[0]
      if (url === '/preview/index.html') {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
        res.end(fs.readFileSync(PREVIEW))
        return
      }
      if (url === '/data/state.json') {
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' })
        res.end(JSON.stringify(STATE_JSON))
        return
      }
      // 指令通道：真实部署时由 M1 侧的服务接收
      if (url === '/api/command' && req.method === 'POST') {
        let body = ''
        req.on('data', function (c) { body += c })
        req.on('end', function () {
          receivedCommands.push(JSON.parse(body))
          res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' })
          res.end(JSON.stringify({ ok: true }))
        })
        return
      }
      res.writeHead(404)
      res.end('nope')
    })
    server.listen(PORT, '127.0.0.1', resolve)
  })
}

const receivedCommands = []

/* ---------------- 极简 CDP 客户端 ---------------- */
function getJSON(url) {
  return new Promise(function (resolve, reject) {
    http.get(url, function (res) {
      let d = ''
      res.on('data', function (c) { d += c })
      res.on('end', function () { try { resolve(JSON.parse(d)) } catch (e) { reject(e) } })
    }).on('error', reject)
  })
}

function connectWS(wsUrl) {
  return new Promise(function (resolve, reject) {
    const u = new URL(wsUrl)
    const key = crypto.randomBytes(16).toString('base64')
    const sock = net.connect(Number(u.port), u.hostname, function () {
      sock.write('GET ' + u.pathname + ' HTTP/1.1\r\nHost: ' + u.host +
        '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: ' + key +
        '\r\nSec-WebSocket-Version: 13\r\n\r\n')
    })
    let buf = Buffer.alloc(0)
    let hs = false
    const listeners = []
    sock.on('data', function (chunk) {
      buf = Buffer.concat([buf, chunk])
      if (!hs) {
        const idx = buf.indexOf('\r\n\r\n')
        if (idx < 0) { return }
        buf = buf.slice(idx + 4)
        hs = true
        resolve({ send: send, on: function (fn) { listeners.push(fn) }, close: function () { sock.destroy() } })
      }
      for (;;) {
        if (buf.length < 2) { return }
        const b1 = buf[1]
        let len = b1 & 0x7f
        let off = 2
        if (len === 126) { if (buf.length < 4) { return } len = buf.readUInt16BE(2); off = 4 }
        else if (len === 127) { if (buf.length < 10) { return } len = Number(buf.readBigUInt64BE(2)); off = 10 }
        if (buf.length < off + len) { return }
        const payload = buf.slice(off, off + len)
        buf = buf.slice(off + len)
        listeners.forEach(function (fn) { fn(payload.toString('utf8')) })
      }
    })
    sock.on('error', reject)
    function send(str) {
      const data = Buffer.from(str, 'utf8')
      const mask = crypto.randomBytes(4)
      let header
      if (data.length < 126) { header = Buffer.alloc(2); header[1] = 0x80 | data.length }
      else if (data.length < 65536) { header = Buffer.alloc(4); header[1] = 0x80 | 126; header.writeUInt16BE(data.length, 2) }
      else { header = Buffer.alloc(10); header[1] = 0x80 | 127; header.writeBigUInt64BE(BigInt(data.length), 2) }
      header[0] = 0x81
      const masked = Buffer.alloc(data.length)
      for (let i = 0; i < data.length; i += 1) { masked[i] = data[i] ^ mask[i % 4] }
      sock.write(Buffer.concat([header, mask, masked]))
    }
  })
}

async function main() {
  staticChecks()

  if (!CHROME) {
    console.log('\n未找到 Chrome/Edge，跳过运行时测试')
    return
  }

  await startServer()

  const userDir = path.join(os.tmpdir(), 'vg-test-' + Date.now())
  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--hide-scrollbars',
    '--remote-debugging-port=9310', '--user-data-dir=' + userDir,
    '--window-size=1400,960', '--no-first-run', '--no-default-browser-check',
    'about:blank'
  ], { stdio: 'ignore' })

  let targets = null
  for (let i = 0; i < 40; i += 1) {
    try { targets = await getJSON('http://127.0.0.1:9310/json/list'); if (targets && targets.length) { break } } catch (e) {}
    await new Promise(function (r) { setTimeout(r, 250) })
  }
  if (!targets || !targets.length) {
    chrome.kill(); server.close()
    throw new Error('无法连接 Chrome DevTools')
  }

  const page = targets.filter(function (t) { return t.type === 'page' })[0]
  const ws = await connectWS(page.webSocketDebuggerUrl)
  let id = 0
  const waiters = {}
  const errors = []
  ws.on(function (raw) {
    let msg
    try { msg = JSON.parse(raw) } catch (e) { return }
    if (msg.id && waiters[msg.id]) { waiters[msg.id](msg); delete waiters[msg.id]; return }
    if (msg.method === 'Runtime.exceptionThrown') {
      const d = msg.params.exceptionDetails
      errors.push(d.exception && d.exception.description ? d.exception.description : d.text)
    }
  })
  function cmd(method, params) {
    id += 1
    const myId = id
    return new Promise(function (resolve) { waiters[myId] = resolve; ws.send(JSON.stringify({ id: myId, method: method, params: params || {} })) })
  }
  async function evaluate(expr) {
    const r = await cmd('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
    return r.result && r.result.result ? r.result.result.value : undefined
  }

  await cmd('Runtime.enable')
  await cmd('Page.enable')
  await cmd('Page.navigate', { url: 'http://127.0.0.1:' + PORT + '/preview/index.html' })
  await new Promise(function (r) { setTimeout(r, 2500) })

  /* ---------------- 2. 加载与六个页面 ---------------- */
  console.log('\n[2] 页面加载与渲染')
  check('运行时就绪', (await evaluate('!!window.__velaguard')) === true)
  check('加载期无 JS 异常', errors.length === 0, errors.join(' | '))
  check('数据源已创建', (await evaluate('typeof window.__velaguard.source.get')) === 'function')

  const pages = ['Home', 'VoiceAssistant', 'Dispatch', 'Zones', 'Records', 'System']
  for (const p of pages) {
    const r = await evaluate(
      'window.__velaguard.build(' + JSON.stringify(p) + ');' +
      'JSON.stringify({' +
      ' kids: document.getElementById("root").children.length,' +
      ' text: (document.getElementById("root").textContent||"").trim().length,' +
      ' page: document.getElementById("root").getAttribute("data-page")' +
      '})'
    )
    const info = JSON.parse(r || '{}')
    check(p + ' 渲染成功（' + info.text + ' 字符）',
      info.kids === 1 && info.text > 40 && info.page === p)
  }

  /* ---------------- 2b. URL hash 启动路由 ----------------
   * start.sh --page voice 会生成 '#kiosk,voice'，界面必须能解析出 voice 并
   * 直接进入语音助手页。早期版本拿整串当页面名匹配，静默失效回到首页，
   * 所以这里锁住这个行为。
   */
  console.log('\n[2b] URL hash 启动路由')

  for (const [hash, expect] of [
    ['voice', 'VoiceAssistant'],
    ['kiosk,voice', 'VoiceAssistant'],
    ['kiosk,dispatch', 'Dispatch'],
    ['/voice', 'VoiceAssistant'],
    ['kiosk', 'Home'],
    ['', 'Home']
  ]) {
    /*
     * 必须加缓存破坏参数强制整页加载：
     * CDP 的 Page.navigate 到「同 URL 仅 hash 不同」时不会重新加载文档，
     * 只做 hash 变更，于是断言会读到上一次遗留的页面状态（假失败）。
     */
    await cmd('Page.navigate', {
      url: 'http://127.0.0.1:' + PORT + '/preview/index.html?t=' + Date.now() +
        (hash ? '#' + hash : '')
    })
    await new Promise(function (r) { setTimeout(r, 2000) })
    const cur = await evaluate('document.getElementById("root").getAttribute("data-page")')
    check('hash "#' + hash + '" → ' + expect, cur === expect, '实际 ' + cur)
  }

  // kiosk 标记应隐藏工具栏
  await cmd('Page.navigate', {
    url: 'http://127.0.0.1:' + PORT + '/preview/index.html?t=' + Date.now() + '#kiosk,voice'
  })
  await new Promise(function (r) { setTimeout(r, 2000) })
  const kioskOn = await evaluate('document.body.classList.contains("kiosk")')
  const kioskPage = await evaluate('document.getElementById("root").getAttribute("data-page")')
  check('#kiosk 隐藏工具栏生效', kioskOn === true, String(kioskOn))
  check('#kiosk,voice 同时进入语音助手', kioskPage === 'VoiceAssistant', String(kioskPage))

  /* ---------------- 3. 数据源切换 ---------------- */
  console.log('\n[3] 数据源切换')
  await evaluate('window.__velaguard.build("Home")')
  const demo = await evaluate('window.__velaguard.source.name')
  check('默认数据源为 demo', demo === 'demo', String(demo))

  const sim = await evaluate('window.__velaguard.setSource("sim")')
  const simText = await evaluate('window.__velaguard.source.get().sourceText')
  check('切换到 sim 成功', sim === 'sim' && simText === '在线模拟', String(sim) + '/' + String(simText))

  const file = await evaluate('window.__velaguard.setSource("file")')
  check('切换到 file 成功', file === 'file', String(file))

  // 轮询等待外部数据到位（最多 8 秒），比固定 sleep 稳
  let fs2 = null
  for (let i = 0; i < 16; i += 1) {
    await new Promise(function (r) { setTimeout(r, 500) })
    const raw = await evaluate(
      'JSON.stringify((function(){var s=window.__velaguard.source.get();' +
      'return s ? {src:s.source, connected:s.connected, first:s.zones[0].name, ' +
      'detail:s.zones[0].detail, cars:s.cars.length, blocked:s.summary.counts.blocked} : null})())'
    )
    fs2 = JSON.parse(raw || 'null')
    if (fs2 && fs2.connected) {
      break
    }
  }
  check('file 模式读到外部 state.json', !!fs2 && fs2.connected === true, JSON.stringify(fs2))
  if (fs2) {
    check('外部数据字段正确（区域名/说明来自文件）',
      fs2.first === '入口大厅' && String(fs2.detail).indexOf('真实数据') === 0, fs2.detail)
    check('外部车辆数据已解析', fs2.cars === 4, String(fs2.cars))
    check('外部状态参与汇总（阻塞 1 区）', fs2.blocked === 1, String(fs2.blocked))
  }

  // 界面是否真的跟着外部数据变了
  // Home 页只显示汇总与数据源标签；区域明细要切到调度台才看得到
  const homeText = await evaluate('document.getElementById("root").textContent || ""')
  check('桌面按外部数据重绘（数据源标签 + 离线车数来自文件）',
    homeText.indexOf('M1 数据') >= 0 && homeText.indexOf('4 区中 1 区已完成') >= 0,
    JSON.stringify(String(homeText).slice(0, 100)))

  const dispatchText = await evaluate(
    'window.__velaguard.build("Dispatch");' +
    'document.getElementById("root").textContent || ""'
  )
  check('调度台显示外部明细（出现「真实数据」）',
    String(dispatchText).indexOf('真实数据') >= 0,
    JSON.stringify(String(dispatchText).slice(0, 120)))

  // 指令通道：file 模式下派单应发出 HTTP 请求（直接测适配层，与当前页面无关）
  await evaluate('window.__velaguard.source.dispatch("Z4")')
  await new Promise(function (r) { setTimeout(r, 1200) })
  check('指令经 HTTP 通道下发', receivedCommands.length > 0 &&
    receivedCommands.some(function (c) { return c.action === 'dispatch' && c.zoneId === 'Z4' }),
    JSON.stringify(receivedCommands))

  const backDemo = await evaluate('window.__velaguard.setSource("demo")')
  check('切回 demo 成功', backDemo === 'demo', String(backDemo))

  /* ---------------- 4. 交互 ---------------- */
  console.log('\n[4] 交互')
  await evaluate('window.__velaguard.build("Home")')
  const nav = await evaluate('window.__velaguard.act("openApp", "/voice");' +
    'document.getElementById("root").getAttribute("data-page")')
  check('磁贴跳转到语音助手', nav === 'VoiceAssistant', String(nav))

  const chat = await evaluate(
    'window.__velaguard.act("askQuick", "现在哪些区域没查完");' +
    'JSON.stringify((window.__velaguard.getData().messages||[]).map(function(m){return m.text}))'
  )
  const msgs = JSON.parse(chat || '[]')
  check('预设指令产生问答两条消息', msgs.length === 3, String(msgs.length))
  check('本地指令返回了真实汇总',
    msgs.some(function (m) { return m.indexOf('尚未完成') >= 0 || m.indexOf('都已查完') >= 0 }),
    JSON.stringify(msgs))

  // 先制造「进行中 + 阻塞」的混合状态，再验证一键取消
  const before = await evaluate(
    'window.__velaguard.build("Dispatch");' +
    'window.__velaguard.act("onDispatch", "Z1");' +   // 入口大厅（已完成）→ 进行中
    'window.__velaguard.act("onDispatch", "Z2");' +   // 主通道（进行中）→ 进行中
    'JSON.stringify(window.__velaguard.source.get().summary.counts)'
  )
  const beforeCounts = JSON.parse(before || '{}')
  check('派单后出现进行中任务', beforeCounts.running >= 1, before)

  const dispatch = await evaluate(
    'window.__velaguard.act("onCancelAll", "");' +
    'JSON.stringify(window.__velaguard.source.get().summary.counts)'
  )
  const counts = JSON.parse(dispatch || '{}')
  check('一键取消清空进行中与阻塞（未开始保持未开始）',
    counts.running === 0 && counts.blocked === 0 && counts.idle >= 1, dispatch)

  /* ---------------- 5. 汇总 ---------------- */
  console.log('\n[5] 运行期异常')
  check('全流程无 JS 异常', errors.length === 0, errors.slice(0, 3).join(' | '))

  ws.close()
  chrome.kill()
  server.close()
}

main()
  .catch(function (e) {
    failed += 1
    console.error('\n测试执行失败：' + e.message)
  })
  .then(function () {
    console.log('\n─────────────────────────────')
    console.log('运行时测试：' + passed + ' 通过，' + failed + ' 失败')
    process.exit(failed > 0 ? 1 : 0)
  })
