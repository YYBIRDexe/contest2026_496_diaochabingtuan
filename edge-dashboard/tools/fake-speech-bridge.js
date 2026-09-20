'use strict'

/**
 * 假语音服务：在 127.0.0.1:8124 上冒充设备上的 speech-bridge.py。
 *
 * 为什么测试需要它：
 *   界面上的「说话」按键走两段式（/api/voice/start → /api/voice/stop）。
 *   没有这个服务时，第一段会以「连接被拒绝」失败，界面如实显示
 *   「没能开始录音」—— 那是**正确**行为，但测不出成功路径，
 *   也测不出「第二次按下立即结束」这条最关键的交互。
 *
 * 只实现测试需要的端点，返回固定内容；不接触任何硬件。
 *
 * 用法（被 test-chat-scroll.js 内部调用，也可单独起）：
 *   node tools/fake-speech-bridge.js 8124
 */

const http = require('http')

const PORT = Number(process.argv[2] || 8124)

/** 记录收到的请求，测试可以查它来判断界面到底调了什么 */
const calls = []

/*
 * 假对话记录（对应真实桥的 /api/voice/records）。
 *
 * 记录由测试通过 POST /__push 显式塞进来，不自动生成 —— 自动「定时冒出来」
 * 会污染别的用例（实测：它会在「上翻看历史」那条用例跑到一半时插一条消息，
 * 把滚动位置顶到底部，看起来像功能坏了）。
 */
const records = []

function json(res, obj, code) {
  const body = Buffer.from(JSON.stringify(obj), 'utf8')
  res.writeHead(code || 200, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': body.length,
    'Access-Control-Allow-Origin': '*'
  })
  res.end(body)
}

const server = http.createServer(function (req, res) {
  const path = req.url.split('?')[0]
  const query = req.url.indexOf('?') >= 0 ? req.url.split('?')[1] : ''
  let raw = ''
  req.on('data', function (c) { raw += c })
  req.on('end', function () {
    calls.push({ path: path, body: raw, query: query })
    if (req.method === 'OPTIONS') {
      res.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type'
      })
      res.end()
      return
    }
    if (path === '/api/health') {
      json(res, { ok: true, model: true, engine: 'vosk (假服务)', realSink: true, sinks: ['假'] })
      return
    }
    /*
     * 测试专用控制面（真实桥没有这两个端点）：
     *   GET  /__calls → 看界面到底请求过什么（排查「轮询有没有真的发生」）
     *   POST /__push  → 塞一条设备侧记录，模拟「唤醒词触发的一轮／识别姗姗来迟」
     */
    if (path === '/__calls') {
      json(res, { ok: true, calls: calls })
      return
    }
    if (path === '/__push') {
      let rec = {}
      try { rec = JSON.parse(raw || '{}') } catch (e) { rec = {} }
      const seq = records.length ? records[records.length - 1].seq + 1 : 1
      records.push({
        seq: seq,
        ts: rec.ts || '2026-09-19 04:00:00',
        text: rec.text || '',
        said: rec.said || '',
        error: rec.error || '',
        detail: rec.detail || '',
        intent: rec.intent || '',
        source: rec.source || 'agent',
        executed: rec.executed
      })
      json(res, { ok: true, seq: seq })
      return
    }
    if (path === '/api/voice/records') {
      let since = 0
      query.split('&').forEach(function (kv) {
        const p = kv.split('=')
        if (p[0] === 'since') { since = Number(p[1] || 0) }
      })
      const tail = records.filter(function (r) { return r.seq > since })
      json(res, {
        ok: true,
        count: records.length,
        lastSeq: records.length ? records[records.length - 1].seq : 0,
        records: tail
      })
      return
    }
    if (path === '/api/voice/state') {
      json(res, {
        ok: true,
        state: {
          wakeword: true, assistant: true, recording: false, service: 'active'
        }
      })
      return
    }
    if (path === '/api/voice/start') {
      /*
       * 刻意延迟 900ms 再回：真实桥里这个调用要停掉唤醒引擎再写 FIFO，
       * 实测约 1.2 秒。若这里立刻返回，界面会在同一帧里从「正在启动」
       * 直接跳到「结束」，测试就采样不到 listening 这个中间态了
       * （这不是界面快，是假服务不真实）。
       */
      setTimeout(function () {
        json(res, { ok: true, stage: 'recording', pid: '12345' })
      }, 900)
      return
    }
    if (path === '/api/voice/stop') {
      // 真正的一轮会等云端，这里立刻返回，测试才好跑
      json(res, {
        ok: true,
        stage: 'done',
        stopMode: 'manual',
        stopped: true,
        text: '前进半米',
        said: '收到，前进半米',
        intent: 'forward'
      })
      return
    }
    if (path === '/api/beep') {
      json(res, { ok: true, route: '假服务' })
      return
    }
    if (path === '/api/voice/talk') {
      json(res, { ok: true, stage: 'done', text: '现在是待命状态', said: '现在待命' })
      return
    }
    json(res, { ok: false, error: 'not found' }, 404)
  })
})

server.listen(PORT, '127.0.0.1', function () {
  console.log('假语音服务已监听 127.0.0.1:' + PORT)
  if (process.send) {
    process.send({ ready: true, port: PORT })
  }
})

module.exports = { server: server, calls: calls }
