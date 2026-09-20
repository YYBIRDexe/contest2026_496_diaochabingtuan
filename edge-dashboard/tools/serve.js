'use strict'

/**
 * 预览 / 看板用的本地静态服务，同时提供「真实数据链路」的两个端点。
 *
 * 为什么需要它：
 *   1. 浏览器禁止 file:// 页面发起 fetch，所以 file 数据源必须走 http；
 *   2. 它顺带承担「M1 侧数据接入点」的角色，便于在没有真机时先把链路跑通。
 *
 * 端点：
 *   GET  /                     → 重定向到看板
 *   GET  /preview/index.html   → 界面
 *   GET  /data/state.json      → 巡检状态（界面轮询它）
 *                                文件 data/state.json 存在则读文件，
 *                                否则回落到内置演示数据，保证界面永远有内容
 *   POST /api/command          → 接收界面下发的指令（派单 / 取消）
 *                                同时追加写入 data/commands.log 供 M1 侧消费
 *
 * 用法：node tools/serve.js [端口]
 */

const http = require('http')
const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..')
const PORT = Number(process.argv[2] || 8080)

const DATA_DIR = path.join(ROOT, 'data')
const STATE_FILE = path.join(DATA_DIR, 'state.json')
const COMMAND_LOG = path.join(DATA_DIR, 'commands.log')

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ux': 'text/plain; charset=utf-8',
  '.log': 'text/plain; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8'
}

/** 没有 data/state.json 时的兜底数据，保证界面不会白屏 */
const FALLBACK_STATE = {
  zones: [
    { id: 'Z1', name: '入口大厅', route: 'R-01', routeDesc: '前台 → 闸机 → 电梯口', car: 'CAR-1', status: 'done', progress: 100, detail: '示例数据：地面无杂物，闸机通行正常' },
    { id: 'Z2', name: '主通道', route: 'R-02', routeDesc: 'A 段 → B 段', car: 'CAR-2', status: 'running', progress: 60, detail: '示例数据：正在通过 B 段' },
    { id: 'Z3', name: '展项区', route: 'R-03', routeDesc: '展台 1 → 展台 4', car: 'CAR-3', status: 'blocked', progress: 35, detail: '示例数据：前方有障碍，已停车待处置' },
    { id: 'Z4', name: '设备区', route: 'R-04', routeDesc: '配电柜 → 机柜背面', car: 'CAR-4', status: 'idle', progress: 0, detail: '示例数据：等待派单' }
  ],
  cars: [
    { id: 'CAR-1', zone: '入口大厅', ip: '192.168.4.11', online: true, battery: 86 },
    { id: 'CAR-2', zone: '主通道', ip: '192.168.4.12', online: true, battery: 72 },
    { id: 'CAR-3', zone: '展项区', ip: '192.168.4.13', online: true, battery: 64 },
    { id: 'CAR-4', zone: '设备区', ip: '192.168.4.14', online: false, battery: 0 }
  ]
}

function sendJSON(res, code, obj) {
  const body = Buffer.from(JSON.stringify(obj), 'utf8')
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': body.length,
    'Cache-Control': 'no-store',
    'Access-Control-Allow-Origin': '*'
  })
  res.end(body)
}

function serveState(res) {
  // 优先读 M1 / 外部程序写入的状态文件
  fs.readFile(STATE_FILE, 'utf8', function (err, txt) {
    if (err) {
      sendJSON(res, 200, FALLBACK_STATE)
      return
    }
    try {
      sendJSON(res, 200, JSON.parse(txt))
    } catch (e) {
      // 文件正在被写入时可能读到半截 JSON，返回兜底而不是报错
      sendJSON(res, 200, FALLBACK_STATE)
    }
  })
}

function receiveCommand(req, res) {
  let body = ''
  req.on('data', function (c) { body += c })
  req.on('end', function () {
    let cmd = null
    try {
      cmd = JSON.parse(body)
    } catch (e) {
      sendJSON(res, 400, { ok: false, message: '指令不是合法 JSON' })
      return
    }
    const line = JSON.stringify(cmd) + '\n'
    fs.mkdirSync(DATA_DIR, { recursive: true })
    fs.appendFile(COMMAND_LOG, line, function (err) {
      if (err) {
        console.error('写入指令日志失败：' + err.message)
      }
    })
    console.log('收到指令：' + line.trim())
    sendJSON(res, 200, { ok: true, message: '指令已接收' })
  })
}

const server = http.createServer(function (req, res) {
  const urlPath = decodeURIComponent(req.url.split('?')[0])

  if (urlPath === '/data/state.json') {
    serveState(res)
    return
  }

  if (urlPath === '/api/command') {
    if (req.method === 'OPTIONS') {
      res.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type'
      })
      res.end()
      return
    }
    if (req.method === 'POST') {
      receiveCommand(req, res)
      return
    }
    sendJSON(res, 405, { ok: false, message: '请用 POST' })
    return
  }

  let rel = urlPath === '/' ? '/preview/index.html' : urlPath
  const filePath = path.join(ROOT, path.normalize(rel).replace(/^([/\\])+/, ''))

  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403)
    res.end('forbidden')
    return
  }

  fs.readFile(filePath, function (err, buf) {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
      res.end('404 ' + rel)
      return
    }
    res.writeHead(200, {
      'Content-Type': MIME[path.extname(filePath).toLowerCase()] || 'application/octet-stream',
      'Cache-Control': 'no-store'
    })
    res.end(buf)
  })
})

// 绑定 0.0.0.0：这样 M1 上跑的界面可以直接访问开发机上的接口，
// 也方便用手机/平板连过来看板。仅本机使用时也不受影响。
server.listen(PORT, '0.0.0.0', function () {
  console.log('看板地址：   http://127.0.0.1:' + PORT + '/')
  console.log('状态接口：   http://127.0.0.1:' + PORT + '/data/state.json')
  console.log('指令接口：   POST http://127.0.0.1:' + PORT + '/api/command')
  console.log('根目录：     ' + ROOT)
  console.log('')
  console.log('提示：界面里点状态栏的数据源标签可切换到「M1 数据」模式，')
  console.log('      把状态写到 ' + STATE_FILE + ' 即可驱动界面。')
})
