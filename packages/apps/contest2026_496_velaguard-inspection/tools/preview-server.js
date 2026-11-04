/**
 * 本地预览服务（零依赖）
 *
 * 用法：
 *   node tools/preview-server.js [端口]
 *   浏览器打开 http://127.0.0.1:8177
 *
 * 它做两件事：
 *   1. /                → 预览页面（内联 bundle + 浏览器宿主 + 公共样式）
 *   2. /api/bundle.js   → 现打的 bundle（避免手工重建）
 *
 * 每次请求都重新打包，所以改完 src/ 直接刷新页面即可——预览与 openvela 同源，
 * 不存在"预览对了、真机不对"的两份代码问题。
 */
const http = require('http')
const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

const ROOT = path.resolve(__dirname, '..')
const PORT = parseInt(process.argv[2] || '8177', 10)

/* 宿主是真正的 .js 文件，直接读内容内联——不做任何字符串剥离 */
const HOST_JS = fs.readFileSync(path.join(__dirname, 'host-browser.js'), 'utf8')

function buildBundle() {
  execFileSync(process.execPath, [path.join(__dirname, 'bundle.js'), '--target', 'browser',
    '--out', path.join(ROOT, 'build', 'bundle.browser.js')], { stdio: 'pipe' })
  return fs.readFileSync(path.join(ROOT, 'build', 'bundle.browser.js'), 'utf8')
}

function page(bundle) {
  return '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n' +
    '<meta charset="utf-8">\n' +
    '<meta name="viewport" content="width=720, initial-scale=1">\n' +
    '<title>VelaGuard 快应用预览（openvela 720×1280）</title>\n' +
    '<style>body{margin:0;background:#05080f;display:flex;justify-content:center;}' +
    '#frame{width:720px;box-shadow:0 0 40px rgba(0,0,0,0.8);}</style>\n' +
    '</head>\n<body>\n<div id="frame"><div id="app"></div></div>\n' +
    '<script>' + bundle + '</script>\n' +
    '<script>' + HOST_JS + '</script>\n' +
    '</body>\n</html>\n'
}

const server = http.createServer(function (req, res) {
  const url = req.url.split('?')[0]
  try {
    if (url === '/' || url === '/index.html') {
      const bundle = buildBundle()
      const html = page(bundle)
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' })
      res.end(html)
      return
    }
    if (url === '/api/bundle.js') {
      const bundle = buildBundle()
      res.writeHead(200, { 'Content-Type': 'application/javascript; charset=utf-8', 'Cache-Control': 'no-store' })
      res.end(bundle)
      return
    }
    if (url === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ ok: true, port: PORT }))
      return
    }
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
    res.end('404')
  } catch (e) {
    res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' })
    res.end('打包失败：\n' + (e && e.stack ? e.stack : String(e)))
  }
})

server.listen(PORT, '127.0.0.1', function () {
  console.log('预览服务已启动：http://127.0.0.1:' + PORT)
  console.log('（每次请求都会重新打包 src/，改完源码刷新页面即可）')
})
