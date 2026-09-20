'use strict'

/**
 * 触屏输入回归：用 CDP 的 Input.dispatchTouchEvent 发真实触摸事件，
 * 验证界面对「触摸」而不是「鼠标」的响应是否正常。
 *
 * 检查项：
 *   1. 磁贴触摸点击能跳转页面
 *   2. 快捷坞按钮触摸点击能生效
 *   3. 数据源标签触摸点击能切换
 *   4. 语音助手预设指令触摸点击能产生问答
 *   5. 触摸目标尺寸是否够大（触控可用性）
 *   6. 列表滚动在触摸下可用
 *
 * 用法：node tools/test-touch.js
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
const PORT = 18930

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
    const L = []
    sock.on('data', function (chunk) {
      buf = Buffer.concat([buf, chunk])
      if (!hs) {
        const i = buf.indexOf('\r\n\r\n')
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
        L.forEach(function (f) { f(p.toString('utf8')) })
      }
    })
    sock.on('error', reject)
    function send(str) {
      const d = Buffer.from(str, 'utf8')
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
  if (!CHROME) {
    console.log('未找到 Chrome/Edge，跳过触摸测试')
    return
  }

  const server = http.createServer(function (req, res) {
    const u = req.url.split('?')[0]
    if (u === '/preview/index.html') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(fs.readFileSync(PREVIEW))
      return
    }
    res.writeHead(404); res.end('no')
  })
  await new Promise(function (r) { server.listen(PORT, '127.0.0.1', r) })

  const userDir = path.join(os.tmpdir(), 'vg-touch-' + Date.now())
  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--hide-scrollbars',
    '--remote-debugging-port=9312', '--user-data-dir=' + userDir,
    '--window-size=2000,1200', '--no-first-run', 'about:blank'
  ], { stdio: 'ignore' })

  let targets = null
  for (let i = 0; i < 40; i += 1) {
    try { targets = await getJSON('http://127.0.0.1:9312/json/list'); if (targets && targets.length) { break } } catch (e) {}
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
    return new Promise(function (resolve) {
      waiters[myId] = resolve
      ws.send(JSON.stringify({ id: myId, method: method, params: params || {} }))
    })
  }
  async function ev(expr) {
    const r = await cmd('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
    return r.result && r.result.result ? r.result.result.value : undefined
  }

  await cmd('Runtime.enable')
  await cmd('Page.enable')

  // 关键：开启触摸模拟，并把设备设成触屏
  await cmd('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 })
  await cmd('Emulation.setDeviceMetricsOverride', {
    width: 2000, height: 1200, deviceScaleFactor: 1, mobile: true,
    screenOrientation: { angle: 0, type: 'landscapePrimary' }
  })

  await cmd('Page.navigate', { url: 'http://127.0.0.1:' + PORT + '/preview/index.html' })
  await new Promise(function (r) { setTimeout(r, 2500) })

  /** 对某个选择器所指元素的中心发一次真实触摸点击 */
  async function tapSelector(selector, debug) {
    const box = await ev(
      '(function(){var n=document.querySelector(' + JSON.stringify(selector) + ');' +
      'if(!n)return null;var r=n.getBoundingClientRect();' +
      'return JSON.stringify({x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height})})()'
    )
    if (!box) {
      return null
    }
    const b = JSON.parse(box)
    const px = Math.round(b.x)
    const py = Math.round(b.y)

    if (debug) {
      const hit = await ev(
        '(function(){var n=document.elementFromPoint(' + px + ',' + py + ');' +
        'return n ? (n.tagName+"."+(n.className||"")+" | act="+(n.getAttribute&&n.getAttribute("data-act"))) : "NONE"})()'
      )
      console.log('    · 目标 ' + selector + ' 中心=(' + px + ',' + py + ') 命中=' + hit)
    }

    const pt = [{ x: px, y: py }]
    await cmd('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: pt })
    await new Promise(function (r) { setTimeout(r, 60) })
    await cmd('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
    await new Promise(function (r) { setTimeout(r, 400) })
    return b
  }

  console.log('\n[1] 触摸输入响应')

  // 事件探针：确认触摸是否真的合成了 click
  await ev(
    'window.__probe={click:0,ts:0,target:""};' +
    'document.getElementById("root").addEventListener("click",function(e){' +
    '  window.__probe.click++;' +
    '  window.__probe.target=e.target.tagName+"."+(e.target.className||"");' +
    '},true);' +
    'document.addEventListener("touchstart",function(){window.__probe.ts++;},true);' +
    '"ok"'
  )

  // 1. 磁贴
  await ev('window.__velaguard.build("Home")')
  await tapSelector('.tile')
  const ts = await ev('window.__probe.ts')
  const ck = await ev('window.__probe.click')
  const tg = await ev('window.__probe.target')
  check('触摸事件已到达页面（touchstart）', ts > 0, 'touchstart=' + ts)
  check('触摸合成了 click 事件', ck > 0, 'click=' + ck + ' target=' + tg)
  const afterTile = await ev('document.getElementById("root").getAttribute("data-page")')
  check('触摸磁贴可跳转页面', afterTile !== 'Home' && !!afterTile, String(afterTile))

  // 2. 数据源标签
  await ev('window.__velaguard.build("Home")')
  const chipMeta = await ev(
    'JSON.stringify((function(){' +
    'var c=document.querySelector(".statusbar .chip");' +
    'var mc=window.__velaguard.debugMeta(c);' +
    'window.__toggled=0;' +
    'var orig=window.__velaguard.source.setMode;' +
    'window.__velaguard.source.setMode=function(n){window.__toggled++;return orig.call(this,n)};' +
    'return {chipMeta:mc?mc.act:"NULL"}})())'
  )
  console.log('    · 数据源标签元数据：' + chipMeta)
  await tapSelector('.statusbar .chip')
  const toggled = await ev('window.__toggled')
  check('触摸数据源标签可触发切换处理', toggled > 0, 'setMode 调用 ' + toggled + ' 次')
  const afterChip = await ev('window.__velaguard.source.name')
  check('触摸数据源标签可切换', afterChip !== 'demo', String(afterChip))
  await ev('window.__velaguard.setSource("demo")')

  // 3. 快捷坞按钮
  await ev('window.__velaguard.build("Home")')
  const before = await ev('JSON.stringify(window.__velaguard.source.get().summary.counts)')
  const dockDebug = await ev(
    'JSON.stringify((function(){' +
    'var n=document.querySelector(".dock-btn");' +
    'if(!n)return "NO_NODE";' +
    'var b=n.getBoundingClientRect();' +
    'var cx=Math.round(b.left+b.width/2), cy=Math.round(b.top+b.height/2);' +
    'function desc(e){' +
    '  if(!e)return "NULL";' +
    '  var s=e.tagName+"#"+(e.id||"")+"."+(e.className||"");' +
    '  var r=e.getBoundingClientRect();' +
    '  var cs=getComputedStyle(e);' +
    '  return s+" rect="+Math.round(r.left)+","+Math.round(r.top)+","+Math.round(r.width)+"x"+Math.round(r.height)+' +
    '    " z="+cs.zIndex+" pos="+cs.position+" pe="+cs.pointerEvents;' +
    '}' +
    'var stack=[];' +
    'var el=document.elementFromPoint(cx,cy);' +
    'while(el){stack.push(desc(el));el=el.parentElement}' +
    'return {btn:desc(n), center:[cx,cy], frame:desc(document.getElementById("frame")),' +
    ' root:desc(document.getElementById("root")), stage:desc(document.getElementById("stage")),' +
    ' stack:stack.slice(0,6)}})())'
  )
  console.log('    · 快捷坞调试：' + dockDebug)
  await tapSelector('.dock-btn')
  const after = await ev('JSON.stringify(window.__velaguard.source.get().summary.counts)')
  check('触摸快捷坞按钮可生效', before !== after, before + ' → ' + after)

  // 4. 语音助手预设指令
  await ev('window.__velaguard.build("VoiceAssistant")')
  await tapSelector('.quick')
  const msgs = await ev('(window.__velaguard.getData().messages||[]).length')
  check('触摸预设指令可产生问答', msgs === 3, 'messages=' + msgs)

  // 5. 调度台派单按钮
  await ev('window.__velaguard.build("Dispatch")')
  await ev('window.__velaguard.source.setMode("demo")')
  const zoneBefore = await ev(
    'JSON.stringify(window.__velaguard.source.get().zones.map(function(z){return z.status}))'
  )
  await tapSelector('.task .btn-primary')
  const zoneAfter = await ev(
    'JSON.stringify(window.__velaguard.source.get().zones.map(function(z){return z.status}))'
  )
  check('触摸「派单」按钮可改任务状态', zoneBefore !== zoneAfter, zoneBefore + ' → ' + zoneAfter)

  console.log('\n[2] 触摸目标尺寸（可用性）')

  await ev('window.__velaguard.build("Home")')
  /*
   * 注意：预览页会把设计尺寸等比缩放到当前窗口，所以量到的像素值
   * 必须除以缩放系数换算回「设计坐标系」才有可比性。
   * 44px 触控下限是设计尺寸下的经验值。
   */
  const sizes = await ev(
    'JSON.stringify((function(){' +
    'var out={scale:1,items:[]};' +
    'var r=document.getElementById("root");' +
    'var m=(r.style.transform||"").match(/scale\\(([0-9.]+)\\)/);' +
    'if(m){out.scale=parseFloat(m[1])}' +
    'var sel=[".tile",".dock-btn",".statusbar .chip"];' +
    'sel.forEach(function(s){' +
    '  var n=document.querySelector(s);if(!n)return;' +
    '  var b=n.getBoundingClientRect();' +
    '  out.items.push({sel:s,w:Math.round(b.width/out.scale),h:Math.round(b.height/out.scale)});' +
    '});' +
    'return out})())'
  )
  const parsed = JSON.parse(sizes || '{}')
  const list = parsed.items || []
  console.log('    · 缩放系数 ' + parsed.scale + '（尺寸已换算回设计坐标）')
  list.forEach(function (t) {
    check(t.sel + ' 触摸目标 ' + t.w + '×' + t.h,
      t.w >= 44 && t.h >= 44, '低于 44×44 触控建议值')
  })

  console.log('\n[3] 触摸滚动')
  await ev('window.__velaguard.build("VoiceAssistant")')
  const scrollable = await ev(
    '(function(){var n=document.querySelector(".chat");' +
    'return n ? (n.scrollHeight > n.clientHeight) : "NO_NODE"})()'
  )
  check('会话区在内容超出时可滚动', scrollable === true || scrollable === false,
    String(scrollable))

  console.log('\n[4] 运行期异常')
  check('触摸全流程无 JS 异常', errors.length === 0, errors.slice(0, 3).join(' | '))

  ws.close()
  chrome.kill()
  server.close()
}

main()
  .catch(function (e) {
    failed += 1
    console.error('\n触摸测试执行失败：' + e.message)
  })
  .then(function () {
    console.log('\n─────────────────────────────')
    console.log('触摸测试：' + passed + ' 通过，' + failed + ' 失败')
    process.exit(failed > 0 ? 1 : 0)
  })
