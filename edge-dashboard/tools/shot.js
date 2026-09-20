'use strict'

/**
 * 用 Chrome DevTools Protocol 打开预览页并截图，同时输出渲染诊断信息。
 * 仅依赖 Node 内置能力（http + net + crypto），无需安装 puppeteer。
 *
 * 用法：node tools/debug-preview.js [端口] [页面名] [输出png] [宽,高]
 */

const http = require('http')
const net = require('net')
const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const os = require('os')
const { spawn } = require('child_process')

const PORT = process.argv[2] || '8123'
const PAGE = process.argv[3] || 'Home'
const OUT = process.argv[4] || path.join(__dirname, '..', 'preview', '_shot-' + PAGE + '.png')
const SIZE = process.argv[5] || '1400,960'
const URL_ = 'http://127.0.0.1:' + PORT + '/preview/index.html'

const CHROME = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
].filter(function (p) { return fs.existsSync(p) })[0]

if (!CHROME) {
  console.error('未找到 Chrome/Edge')
  process.exit(1)
}

function getJSON(url) {
  return new Promise(function (resolve, reject) {
    http.get(url, function (res) {
      let d = ''
      res.on('data', function (c) { d += c })
      res.on('end', function () {
        try {
          resolve(JSON.parse(d))
        } catch (e) {
          reject(e)
        }
      })
    }).on('error', reject)
  })
}

/** 极简 WebSocket 客户端：只处理文本帧 */
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
    let handshaken = false
    const listeners = []

    function send(str) {
      const data = Buffer.from(str, 'utf8')
      const mask = crypto.randomBytes(4)
      let header
      if (data.length < 126) {
        header = Buffer.alloc(2)
        header[1] = 0x80 | data.length
      } else if (data.length < 65536) {
        header = Buffer.alloc(4)
        header[1] = 0x80 | 126
        header.writeUInt16BE(data.length, 2)
      } else {
        header = Buffer.alloc(10)
        header[1] = 0x80 | 127
        header.writeBigUInt64BE(BigInt(data.length), 2)
      }
      header[0] = 0x81
      const masked = Buffer.alloc(data.length)
      for (let i = 0; i < data.length; i += 1) {
        masked[i] = data[i] ^ mask[i % 4]
      }
      sock.write(Buffer.concat([header, mask, masked]))
    }

    sock.on('data', function (chunk) {
      buf = Buffer.concat([buf, chunk])
      if (!handshaken) {
        const idx = buf.indexOf('\r\n\r\n')
        if (idx < 0) {
          return
        }
        buf = buf.slice(idx + 4)
        handshaken = true
        resolve({ send: send, on: function (fn) { listeners.push(fn) }, close: function () { sock.destroy() } })
      }
      for (;;) {
        if (buf.length < 2) {
          return
        }
        const b1 = buf[1]
        let len = b1 & 0x7f
        let off = 2
        if (len === 126) {
          if (buf.length < 4) { return }
          len = buf.readUInt16BE(2)
          off = 4
        } else if (len === 127) {
          if (buf.length < 10) { return }
          len = Number(buf.readBigUInt64BE(2))
          off = 10
        }
        if (buf.length < off + len) {
          return
        }
        const payload = buf.slice(off, off + len)
        buf = buf.slice(off + len)
        listeners.forEach(function (fn) { fn(payload.toString('utf8')) })
      }
    })
    sock.on('error', reject)
  })
}

async function main() {
  const userDir = path.join(os.tmpdir(), 'vg-chrome-' + Date.now())
  const chrome = spawn(CHROME, [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    '--remote-debugging-port=9222',
    '--user-data-dir=' + userDir,
    '--window-size=' + SIZE,
    '--no-first-run',
    '--no-default-browser-check',
    'about:blank'
  ], { stdio: 'ignore' })

  let targets = null
  for (let i = 0; i < 40; i += 1) {
    try {
      targets = await getJSON('http://127.0.0.1:9222/json/list')
      if (targets && targets.length) {
        break
      }
    } catch (e) { /* 继续等待 */ }
    await new Promise(function (r) { setTimeout(r, 250) })
  }
  if (!targets || !targets.length) {
    chrome.kill()
    throw new Error('无法连接 Chrome DevTools')
  }

  const page = targets.filter(function (t) { return t.type === 'page' })[0]
  const ws = await connectWS(page.webSocketDebuggerUrl)

  let id = 0
  const waiters = {}
  const logs = []

  ws.on(function (raw) {
    let msg
    try {
      msg = JSON.parse(raw)
    } catch (e) {
      return
    }
    if (msg.id && waiters[msg.id]) {
      waiters[msg.id](msg)
      delete waiters[msg.id]
      return
    }
    if (msg.method === 'Runtime.exceptionThrown') {
      const d = msg.params.exceptionDetails
      logs.push('[EXCEPTION] ' + (d.exception && d.exception.description ? d.exception.description : d.text))
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

  await cmd('Runtime.enable')
  await cmd('Page.enable')
  // 支持 VG_HASH（如 "kiosk"）与 VG_QUERY（如 "src=file"）定制导航 URL
  let navUrl = URL_
  if (process.env.VG_QUERY) {
    navUrl += '?' + process.env.VG_QUERY
  }
  if (process.env.VG_HASH) {
    navUrl += '#' + process.env.VG_HASH
  }
  await cmd('Page.navigate', { url: navUrl })
  await new Promise(function (r) { setTimeout(r, 2500) })

  await cmd('Runtime.evaluate', {
    expression: 'window.__velaguard && window.__velaguard.build("' + PAGE + '")'
  })
  await new Promise(function (r) { setTimeout(r, 600) })

  // 可选的交互回归：ACT="方法名|tid" 时先触发一次页面事件再截图
  const ACT = process.env.VG_ACT
  if (ACT) {
    const parts = ACT.split('|')
    const r = await cmd('Runtime.evaluate', {
      expression: 'window.__velaguard.act(' + JSON.stringify(parts[0]) + ', ' +
        JSON.stringify(parts[1] || '') + ')',
      returnByValue: true
    })
    console.log('--- 交互 ---\n' + parts[0] + '(' + (parts[1] || '') + ') → ' +
      (r.result && r.result.result ? r.result.result.value : '?'))
    await new Promise(function (r2) { setTimeout(r2, 500) })
  }

  const diag = await cmd('Runtime.evaluate', {
    expression: [
      '(function () {',
      '  var q = function (s) { return document.querySelector(s) };',
      '  var info = function (s) {',
      '    var n = q(s);',
      '    if (!n) { return "NO_NODE" }',
      '    var cs = getComputedStyle(n);',
      '    var r = n.getBoundingClientRect();',
      '    return cs.display + "/" + cs.flexDirection + " " + Math.round(r.width) + "x" + Math.round(r.height);',
      '  };',
      '  return JSON.stringify({',
      '    api: !!window.__velaguard,',
      '    err: window.__err || "",',
      '    rootKids: document.getElementById("root").children.length,',
      '    tiles: document.querySelectorAll(".tile").length,',
      '    screen: info(".screen"),',
      '    heroStats: info(".hero-stats"),',
      '    dock: info(".dock"),',
      '    items: document.querySelectorAll(".card,.car,.task,.record,.row,.quick").length,',
      '    kiosk: document.body.classList.contains("kiosk"),',
      '    barHidden: getComputedStyle(document.getElementById("bar")).display,',
      '    curPage: (function () {',
      '      var r = document.getElementById("root");',
      '      return r ? (r.getAttribute("data-page") || "NONE") : "NO_ROOT";',
      '    })(),',
      '    clock: (function () {',
      '      var n = document.querySelector(".sb-time");',
      '      return n ? n.textContent : "NO_CLOCK";',
      '    })(),',
      '    badges: document.querySelectorAll(".badge").length,',
      '    badgeHTML: q(".badge") ? q(".badge").outerHTML : "NO_BADGE",',
      '    zoneHTML: q(".zone") ? q(".zone").outerHTML : "NO_ZONE"',
      '  });',
      '})()'
    ].join('\n'),
    returnByValue: true
  })
  console.log('--- 诊断 ---')
  console.log(diag.result && diag.result.result ? diag.result.result.value : JSON.stringify(diag))

  const shot = await cmd('Page.captureScreenshot', { format: 'png' })
  const data = shot.result && shot.result.data ? shot.result.data : (shot.data || null)
  if (data) {
    fs.mkdirSync(path.dirname(OUT), { recursive: true })
    fs.writeFileSync(OUT, Buffer.from(data, 'base64'))
    console.log('--- 截图 ---\n' + OUT + ' (' + fs.statSync(OUT).size + ' bytes)')
  } else {
    console.log('--- 截图失败 ---')
  }

  if (logs.length) {
    console.log('--- 控制台异常 ---')
    console.log(logs.join('\n'))
  }

  ws.close()
  chrome.kill()
}

main().catch(function (e) {
  console.error('调试失败：' + e.message)
  process.exit(1)
})
