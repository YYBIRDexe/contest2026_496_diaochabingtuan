/**
 * 浏览器预览宿主（真正的 JS 文件，不是字符串模板）
 *
 * 用法：由 tools/preview-server.js 与 tools/test-ui.js 直接读文件内容内联进页面。
 * 写成独立 .js 而不是把自己的源码塞进一个模板字符串里，
 * 就是为了避免"字符串里的代码"这种双重转义带来的低级错误
 * （第一次就是这么错的：反引号没剥掉，注入后整段脚本变成模板字符串 → 白屏）。
 *
 * 它只做三件环境相关的事：DOM 写入、定时器、hash 路由。
 * 页面与外壳代码与 openvela 版**完全相同**（src/ 一份源码）。
 */
(function () {
  var doc = document

  function clockText(ts) {
    var d = new Date(ts)
    function p(n) { return n < 10 ? '0' + n : '' + n }
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
      ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds())
  }

  function setContent(html) {
    doc.getElementById('app').innerHTML = html
  }

  /**
   * 绑定层（浏览器侧）：给渲染出来的 [data-act] 挂事件代理。
   * openvela 侧没有 DOM 事件代理，那边改写成 onclick 字符串——
   * 差异只在这一层，页面与外骨骼代码两边完全一致。
   */
  function bindActions(html, page) {
    return html
  }

  /* 事件代理：所有 [data-act] 的点击都从这里派发 */
  function bindClick(handler) {
    doc.addEventListener('click', function (e) {
      var el = e.target
      while (el && el !== doc.body) {
        if (el.getAttribute && el.getAttribute('data-act')) {
          handler(el.getAttribute('data-act'), el.getAttribute('data-tid') || '', e)
          return
        }
        el = el.parentNode
      }
    }, false)
  }

  function setHash(page) {
    try {
      if (window.location.hash !== '#' + page) {
        window.location.hash = page
      }
    } catch (e) { /* hash 只是方便，失败不影响功能 */ }
  }

  /* 注入公共样式 */
  var style = doc.createElement('style')
  style.textContent = window.VelaGuard.baseCss
  doc.head.appendChild(style)

  /* 端侧 Agent 通道：浏览器里必然失败 → agent.js 自动落到本地指令表 */
  window.VelaGuard.agent.setAskSender(function (q) {
    return window.VelaGuard.askAgent(q)
  })

  /* 语音页需要把"回车发送"后的重绘接回来 */
  var voice = window.VelaGuard.pages.Voice
  if (voice && voice.setRender) {
    voice.setRender(function () {
      if (window.__vg) { window.__vg.render() }
    })
  }

  window.addEventListener('hashchange', function () {
    var page = (window.location.hash || '').replace('#', '')
    if (page && window.__vg && page !== window.__vg.current()) {
      window.__vg.navigate(page)
    }
  })

  var env = {
    mod: function (name) { return window.VelaGuard.mod(name) },
    pages: window.VelaGuard.pages,
    doc: doc,
    now: function () { return Date.now() },
    clockText: clockText,
    setContent: setContent,
    bindActions: bindActions,
    bindClick: bindClick,
    setHash: setHash,
    setTimeout: function (fn, ms) { return window.setTimeout(fn, ms) },
    setInterval: function (fn, ms) { return window.setInterval(fn, ms) },
    clearInterval: function (id) { window.clearInterval(id) },
    onPageRendered: function (page, d) {
      var p = window.VelaGuard.pages[page]
      if (p && p.afterRender) { p.afterRender(d) }
    }
  }

  /* 事件代理只挂一次，之后统一切到 app.dispatch */
  bindClick(function (act, tid, e) {
    if (window.__vg) { window.__vg.dispatch(act, tid, e) }
  })

  var initial = (window.location.hash || '').replace('#', '') || 'Home'
  window.__vg = window.VelaGuard.createApp(env)
  window.__vg.start(initial)
  window.__vgReady = true
})();
