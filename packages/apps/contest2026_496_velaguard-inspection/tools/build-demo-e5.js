/**
 * 生成「E5 触控演示版」单文件 HTML
 *
 * 做法：读已有的 build/ui-*.html（内含完整 bundle + 浏览器宿主），
 * 只替换末尾那段浏览器宿主脚本，换成演示版宿主：
 *   · 大号触控「开始巡检」按钮（E5 用手指点）
 *   · 自动播放：开始巡检 → 调度台 → 地图跑路线 → 注入障碍 → 阻塞告警 → 巡检记录
 *   · 720×1280 手机比例居中，支持点按全屏
 *
 * 为什么从 ui-*.html 派生而不是从源码重建：
 *   bundle 已经有现成产物（tools/bundle.js 生成），派生可保证演示版与
 *   正式预览版跑的是**同一份应用代码**，不会因为重新打包而行为不一致。
 *
 * 用法：node tools/build-demo-e5.js
 */
const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..')
const SRC_HTML = path.join(ROOT, 'build', 'ui-home.html')
const OUT = path.join(ROOT, 'build', 'demo-e5.html')

/* 宿主脚本的起点：bundle 结束后的第二个 <script> */
const MARK = '</script><script>'

const raw = fs.readFileSync(SRC_HTML, 'utf8')
const at = raw.indexOf(MARK)
if (at < 0) {
  console.error('✗ 在 ' + SRC_HTML + ' 里找不到 bundle 与宿主的交界标记')
  process.exit(1)
}
const bundlePart = raw.slice(0, at + '</script>'.length)
const head = '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">' +
  '<title>VelaGuard 巡检调度台</title></head><body>'

/* 原文件里 bundle 之前的内容（正文起点到 bundle 脚本） */
const bodyStart = raw.indexOf('<body>')
if (bodyStart < 0) {
  console.error('✗ 源 html 里找不到 <body>')
  process.exit(1)
}
const bodyOpenEnd = bodyStart + '<body>'.length
const bundleOnly = raw.slice(bodyOpenEnd, at + '</script>'.length)

const demoHost = `<script>
/**
 * E5 触控演示宿主
 *
 * 与正式浏览器预览宿主（preview 里那份）的差异只有三处：
 *   1. 外层多一个手机比例舞台 + 全屏按钮（E5 是竖屏触控）
 *   2. 多一个大号「开始巡检」浮层按钮，手指点得到
 *   3. 多一个自动演示序列 demoRun()，按真实动作名派发，不绕过应用逻辑
 *
 * 应用代码本身（bundle）与正式预览完全相同。
 */
(function () {
  var doc = document

  function clockText(ts) {
    var d = new Date(ts)
    function p(n) { return n < 10 ? '0' + n : '' + n }
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
      ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds())
  }
  function setContent(html) { doc.getElementById('app').innerHTML = html }
  function bindActions(html) { return html }
  function setHash() { /* 演示模式不用 hash */ }

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

  /* ---------- 舞台与浮层（演示专用，不属于应用） ---------- */
  var stageCss = doc.createElement('style')
  stageCss.textContent = [
    'html,body{margin:0;padding:0;width:100%;height:100%;background:#0b1220;',
    'overflow:hidden;-webkit-user-select:none;user-select:none;-webkit-tap-highlight-color:transparent;}',

    /* ---------- 横屏全屏适配 ----------
     * 应用基础样式（src/common/styles.js）是按 720x1280 竖屏写死的：
     *   #app{width:720px}   .tile{width:330px}
     * E5 屏是 1920x1080 横屏，照搬会被挤成中间一条窄柱（设备实拍确认过）。
     * 这里只覆盖**与屏幕方向耦合**的几条排布规则，
     * 组件内部的字号/圆角/配色全部沿用原样式 —— 观感仍是同一个应用，只是改成横屏排布。 */
    '#stage{position:absolute;left:0;top:0;width:100%;height:100%;',
    'background:#0b1220;overflow:hidden;}',
    '#app{width:100%!important;min-height:0!important;height:100%;',
    'overflow-y:auto;overflow-x:hidden;-webkit-overflow-scrolling:touch;',
    'padding-bottom:132px;box-sizing:border-box;background:#0b1220;}',

    /* 整体内容居中并限宽。1800px 太散（1920 屏上内容被拉成一条），
       收到 1500px 后卡片与列表的阅读宽度更合适 */
    '.screen{max-width:1500px;margin:0 auto;padding:16px 26px 10px 26px!important;}',

    /* 用 12 列栅格统一处理两种 .grid：
         磁贴区（6 个 .tile）   → 每个 span 4 = 每行 3 个
         区域状态条（4 个 .lrow）→ 每个 span 3 = 每行 4 个
       注意 1：.tile:nth-child(2n){margin-right:0} 是竖屏两列时写的，得覆盖掉
       注意 2：区域条的行内联写了 width:330px（模板里），必须 !important 解开，
               否则 4 条放不下会溢成 3+1 两行 —— 这个毛病在设备实拍里看得很清楚 */
    '.grid{display:grid!important;grid-template-columns:repeat(12,1fr);gap:16px;align-items:stretch;}',
    '.tile{width:auto!important;height:124px!important;margin:0!important;grid-column:span 4;}',
    '.tile:nth-child(2n){margin-right:0!important;}',
    '.grid > .lrow{grid-column:span 3;width:auto!important;margin:0!important;}',

    /* 详情类页面（调度台/记录/区域/语音）：内容单列居中，避免行被拉成超宽条 */
    '.landscape .screen > .card,',
    '.landscape .screen > .lrow,',
    '.landscape .screen > .hero,',
    '.landscape .screen > .chat,',
    '.landscape .screen > .inputbar,',
    '.landscape .screen > .presets,',
    '.landscape .screen > .dock{max-width:980px;margin-left:auto;margin-right:auto;}',

    /* 地图：SVG 的 viewBox 是 500x303 的小坐标系，里面的字号/线宽都是按那个尺度定的。
       直接拉到 1800px 宽会把文字和线宽一起放大 ~3.6 倍（第一版就是这个毛病）。
       限制到 1080px（放大 ~2.16 倍），并配一个略矮的高度，兼顾可读与页面留白。 */
    '.mapwrap{padding:6px;max-width:1080px;margin:0 auto;}',
    '.mapsvg{width:100%!important;height:auto!important;display:block;}',

    '.chat{height:calc(100vh - 470px);min-height:240px;}',
    '.toast{bottom:150px!important;max-width:1080px!important;font-size:24px!important;}',

    /* ---------- 底部按钮栏 ---------- */
    '#bar{position:absolute;left:0;right:0;bottom:0;height:132px;z-index:9999;',
    'background:linear-gradient(180deg,rgba(11,18,32,0) 0%,rgba(11,18,32,.95) 30%);',
    'display:flex;align-items:center;justify-content:center;gap:28px;}',
    '.demo-btn{height:92px;padding:0 56px;border-radius:46px;border:0;',
    'font-size:34px;font-weight:700;color:#fff;background:#2f6df6;',
    'box-shadow:0 8px 26px rgba(47,109,246,.45);}',
    '.demo-btn:active{transform:translateY(2px);}',
    '.demo-btn.ghost{background:rgba(255,255,255,.13);box-shadow:none;font-size:28px;padding:0 40px;}',

    /* 提示条固定在按钮栏正上方，不压内容；演示开始后淡出 */
    '#hint{position:absolute;left:0;right:0;bottom:132px;z-index:9998;text-align:center;',
    'color:#eaf2ff;font-size:26px;line-height:1.5;pointer-events:none;',
    'background:linear-gradient(180deg,rgba(11,18,32,0) 0%,rgba(11,18,32,.97) 24%,rgba(11,18,32,.97) 76%,rgba(11,18,32,0) 100%);',
    'padding:28px 24px 24px;text-shadow:0 2px 10px rgba(0,0,0,.95);}',
    '#hint b{display:block;font-size:32px;font-weight:700;color:#fff;margin-bottom:6px;}',

    /* ---------- 真车联动状态徽标 ----------
     * 演示页现在会去 127.0.0.1:8127 问「四台车跑到哪一步了」。
     * 链路不可用时必须**看得见**地提示，不能默默退化成纯动画 ——
     * 那正是这次要修的毛病（按了按钮车不动，界面上却像在跑）。 */
    '#carstat{position:absolute;right:26px;bottom:150px;z-index:10000;font-size:22px;',
    'line-height:1.35;color:#eaf2ff;background:rgba(11,18,32,.86);',
    'border:1px solid rgba(255,255,255,.14);border-radius:14px;padding:10px 16px;',
    'max-width:640px;pointer-events:none;text-shadow:0 1px 6px rgba(0,0,0,.9);}',
    '#carstat b{display:block;font-size:24px;}',
    '#carstat .ok{color:#3ddc84;}',
    '#carstat .busy{color:#4da3ff;}',
    '#carstat .bad{color:#ff6b6b;}',
    '#carstat .dim{color:#94a3b8;}'
  ].join('')
  doc.head.appendChild(stageCss)

  var style = doc.createElement('style')
  style.textContent = window.VelaGuard.baseCss
  doc.head.appendChild(style)

  /* ---------- 环境 ---------- */
  window.VelaGuard.agent.setAskSender(function (q) {
    return window.VelaGuard.askAgent(q)
  })
  var voice = window.VelaGuard.pages.Voice
  if (voice && voice.setRender) {
    voice.setRender(function () { if (window.__vg) { window.__vg.render() } })
  }

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

  bindClick(function (act, tid, e) {
    if (window.__vg) { window.__vg.dispatch(act, tid, e) }
  })

  window.__vg = window.VelaGuard.createApp(env)
  window.__vg.start('Home')
  window.__vgReady = true

  /* ---------- 演示浮层 ----------
   * 注：不再做整体 scale 缩放。应用已改为**横屏流体排布**（见上面的覆盖样式），
   * 直接铺满屏幕，因此不需要 #fit 之类的等比缩放包装层。 */
  var stage = doc.createElement('div'); stage.id = 'stage'
  var app = doc.getElementById('app')
  doc.body.appendChild(stage)
  stage.appendChild(app)

  /* 标记横屏模式：上面那些居中/限宽的覆盖规则都挂在这个类下面，
     这样同一个 demo 文件在竖屏浏览器里打开也不会被误伤 */
  doc.body.className = (doc.body.className ? doc.body.className + ' ' : '') + 'landscape'

  /* kiosk 模式本身已全屏，不放全屏按钮（56px 在触控屏上也点不准） */

  var hint = doc.createElement('div')
  hint.id = 'hint'
  hint.innerHTML = '<b>VelaGuard 巡检调度台</b>点击下方按钮开始本轮巡检'
  stage.appendChild(hint)

  /* ---------- 真车联动状态徽标 ---------- */
  var carStat = doc.createElement('div')
  carStat.id = 'carstat'
  carStat.innerHTML = '<b>真车联动</b><span class="dim">正在连接车端执行器…</span>'
  stage.appendChild(carStat)

  var bar = doc.createElement('div'); bar.id = 'bar'
  var btn = doc.createElement('button')
  btn.className = 'demo-btn'; btn.textContent = '开始巡检'
  var btnReset = doc.createElement('button')
  btnReset.className = 'demo-btn ghost'; btnReset.textContent = '复位'
  bar.appendChild(btn); bar.appendChild(btnReset)
  stage.appendChild(bar)

  function fade(el, to, ms) {
    el.style.transition = 'opacity ' + ms + 'ms'
    el.style.opacity = String(to)
  }

  /* ---------- 自动演示序列 ----------
   * 全程用**真实动作名**派发，等于替用户点了界面上的按钮，
   * 不绕过 store / 页面逻辑。
   */
  var timers = []
  /* 轮询用的 setInterval 不能塞进 timers —— 那个数组只装 setTimeout 的数值句柄，
     clearTimeout(对象) 是静默无效的。单独一个数组，clearAll 时一并清掉。 */
  var ixTimers = []
  function T(fn, ms) { timers.push(setTimeout(fn, ms)) }
  function clearAll() {
    for (var i = 0; i < timers.length; i++) { clearTimeout(timers[i]) }
    timers = []
    for (var j = 0; j < ixTimers.length; j++) { clearInterval(ixTimers[j]) }
    ixTimers = []
    /* RC 在下面才定义；clearAll 只会在按钮回调里跑（那时 RC 早已就绪），
       这里用 typeof 兜一下，避免将来有人在脚本顶部调它踩 TDZ */
    if (typeof RC !== 'undefined') { RC.startedRound = false }
  }

  /* ================================================================== *
   * VelaGuard 真车联动
   *
   * 这一段是「按一下开始巡检，四台车真的动」的全部前端逻辑。
   *
   * 分工：
   *   · 车端 patrol_controller.py（U2P 上，127.0.0.1:8127）负责**真派单**：
   *     四台车各跑一条预编路线，走 /cmd_vel，带里程计闭环和雷达避障。
   *   · 这里只做两件事：点按钮时下发 /patrol/start；每 800 ms 把真实进度
   *     同步进应用的状态机，让调度台/地图/记录页显示的是**车真的走到哪**。
   *
   * 与自动演示序列 demoRun() 的关系：
   *   demoRun() 仍然负责「切页面」这种演出动作（不能让它替车走路），
   *   但它不再自己推进任务状态 —— 状态一律以车端回传为准。
   *   车端不可用时**如实报错**，不退回纯动画：界面在跑、车没动，
   *   正是这次要根除的观感。
   * ================================================================== */
  var RC = {
    base: 'http://127.0.0.1:8127',
    pollMs: 800,
    once: false,
    lastMsg: '',
    lastState: null,
    closedRound: 0
  }

  function setCarStatus(html) {
    carStat.innerHTML = html
  }

  function shortErr(e) {
    var s = String((e && (e.message || e)) || '未知错误')
    return s.length > 90 ? s.slice(0, 90) + '…' : s
  }

  function fetching(pathname, opts, timeoutMs) {
    /* 车端服务在本机，正常 <1 s 返回；给 2.5 s 超时，
       免得点一下按钮转圈转到天荒地老。fetch 不可用就直接报错。 */
    if (typeof fetch !== 'function') {
      return Promise.reject(new Error('这个浏览器不支持 fetch'))
    }
    var ctl = (typeof AbortController === 'function') ? new AbortController() : null
    var timer = setTimeout(function () { if (ctl) { ctl.abort() } }, timeoutMs || 2500)
    var o = { method: (opts && opts.method) || 'GET' }
    if (ctl) { o.signal = ctl.signal }
    return fetch(RC.base + pathname, o).then(function (r) {
      clearTimeout(timer)
      return r.json().catch(function () {
        throw new Error('车端返回的不是 JSON（HTTP ' + r.status + '）')
      })
    }, function (e) {
      clearTimeout(timer)
      throw new Error(e && e.name === 'AbortError' ? '车端执行器 2.5 秒无响应' : shortErr(e))
    })
  }

  function syncNow() {
    return fetching('/patrol/status', null, 2500).then(function (st) {
      applyStatus(st)
      return st
    })
  }

  /**
   * 把车端状态写进应用的状态机。
   *
   * 只改**车端能说了算**的字段（状态/进度/位置/文案）；
   * 不回写 car.online —— 那是给人看的故障注入开关，
   * 车真离线时由车端 preflight 拦在派单之前，不使用界面开关表达。
   */
  function applyStatus(st) {
    /*
     * 取任务对象只能用 store 的**公开接口**：默认导出里没有 tasks / round
     * （第一版直接读内部 tasks 表，设备上立刻报 "store.tasks is undefined"）。
     * zoneStates() 返回的每一项就是内部 task 的引用，而且它的 progress
     * 正是界面显示的那个数字，来源唯一。
     */
    var store = window.VelaGuard.store
    var zones = st.zones || []
    if (!zones.length) { return }
    var rows = store.zoneStates()
    for (var i = 0; i < zones.length; i += 1) {
      var z = zones[i]
      var stat = z.status
      if (stat === 'aborted') { stat = 'blocked' }
      /* STATUS 字典只有五态，写进未登记的值会让 zoneStates() 直接抛错 */
      if (['pending', 'running', 'done', 'blocked'].indexOf(stat) < 0) { stat = 'running' }
      var t = null
      for (var j = 0; j < rows.length; j += 1) {
        if (rows[j].id === z.id) { t = rows[j]; break }
      }
      if (!t) { continue }
      t.status = stat
      t.detail = z.detail || t.detail
      t.lastReceiptAt = store.now()
      t.elapsed = 0
      if (stat === 'blocked') {
        t.reason = z.reason || 'obstacle'
        t.finishedAt = store.now()
      }
      if (stat === 'done') {
        t.leg = t.totalLegs
        t.legProgress = 1
        t.legDone = true
        t.dwellLeft = 0
        t.finishedAt = store.now()
      } else if (stat === 'running') {
        /* 第 n 步走完 → 地图上的车标记落在第 n-1 段终点、或正在第 n 段中间 */
        var total = z.stepTotal || t.totalLegs || 1
        var frac = Math.max(0, Math.min(1, (z.progress || 0) / 100))
        var at = frac * total
        t.leg = Math.min(t.totalLegs - 1, Math.max(0, Math.ceil(at) - 1))
        t.legProgress = Math.max(0, Math.min(1, at - t.leg))
      }
    }
  }

  function setBadgeFromState(st) {
    var zones = st.zones || []
    var done = 0, blocked = 0, running = 0
    var lines = []
    for (var i = 0; i < zones.length; i += 1) {
      var z = zones[i]
      if (z.status === 'done') { done += 1 }
      else if (z.status === 'blocked') { blocked += 1 }
      else if (z.status === 'running') { running += 1 }
      lines.push('CAR-' + z.car + ' ' + (z.stepLabel || z.zoneName) +
        (z.status === 'done' ? ' ✓' : (z.status === 'blocked' ? ' ✗' : '')))
    }
    var head = '第 ' + st.round + ' 轮 · '
    var cls = 'busy'
    if (st.status === 'idle') { head = '真车联动就绪'; cls = 'ok' }
    else if (blocked > 0) { head = '第 ' + st.round + ' 轮 · ' + done + ' 完成 / ' + blocked + ' 受阻'; cls = 'bad' }
    else if (running > 0) { head = '第 ' + st.round + ' 轮 · 执行中 ' + running + '/4'; cls = 'busy' }
    else if (st.status === 'done') { head = '第 ' + st.round + ' 轮 · 全部完成'; cls = 'ok' }
    else if (st.status === 'aborted') { head = '第 ' + st.round + ' 轮 · 已取消'; cls = 'dim' }
    setCarStatus('<b class="' + cls + '">' + head + '</b>' +
      '<span class="dim">' + lines.join('　') + '</span>')
  }

  function maybeCloseRound(st) {
    var zones = st.zones || []
    if (!zones.length) { return }
    for (var i = 0; i < zones.length; i += 1) {
      if (zones[i].status !== 'done' && zones[i].status !== 'blocked') { return }
    }
    if (RC.closedRound === st.round) { return }
    RC.closedRound = st.round
    /* 四台车都收工 → 归档成一条巡检记录（走 store 自己的台账逻辑） */
    try {
      window.VelaGuard.store.closeRound()
    } catch (e) { /* 归档失败不影响巡检本身 */ }
    /*
     * 归档后必须重绘一次。设备实拍抓到过：本轮四台车全部完成、徽标也显示
     * 「全部完成」，记录页却仍写着「历史轮次（0 条）/ 还没有归档的轮次」——
     * 因为记录页的数据只在它自己渲染时读一次，后台线程里改 store 不会触发重绘。
     */
    try {
      if (window.__vg) { window.__vg.render() }
    } catch (e) { /* 重绘失败不影响巡检本身 */ }
  }

  function poll() {
    if (RC.once) { return }
    syncNow().then(function (st) {
      RC.lastState = st
      setBadgeFromState(st)
      maybeCloseRound(st)
    }).catch(function (e) {
      setCarStatus('<b class="bad">真车联动未连接</b><span class="dim">' +
        shortErr(e) + '<br>按下按钮不会让车动。终端里跑：' +
        'bash ~/velaguard/demo/start-patrol.sh</span>')
    })
    setTimeout(poll, RC.pollMs)
  }

  function startReal() {
    return fetching('/patrol/start', { method: 'POST' }, 3000).then(function (r) {
      if (!r || r.ok !== true) {
        throw new Error((r && r.message) || '车端拒绝了这次派单')
      }
      return r
    })
  }

  function stopReal() {
    return fetching('/patrol/stop', { method: 'POST' }, 3000)
  }

  function resetReal() {
    return fetching('/patrol/reset', { method: 'POST' }, 3000)
  }

  function demoRun() {
    clearAll()
    var vg = window.__vg
    /* 提示条退场放在 demoRun 内部，而不是按钮回调里 ——
       这样「点按钮」和「脚本调 __demo.run()」行为完全一致，截图验证才有意义 */
    fade(hint, 0, 350)

    /* ★ 真车联动版：先让车端派单，再演界面。
       车端不接（没起执行器 / 车不在线 / 电量低）就**不演**，
       并在徽标上写明原因 —— 绝不做「界面在跑、车没动」的假戏，
       那正是这次要根除的观感。 */
    setCarStatus('<b class="busy">正在向车端下发本轮巡检…</b>')
    btn.disabled = true
    startReal().then(function () {
      btn.disabled = false
      return syncNow().catch(function () { /* 下一轮 poll 会刷新徽标 */ })
    }).then(function () {
      /*
       * 台上要做的事：
       *   ① 首页「开始本轮巡检」= 建本轮任务单（四区各一张，pending）
       *      —— 这一步只是**界面台账**；真正让车动的是上面的 /patrol/start，
       *      之后每 800 ms 的 syncNow() 把车端进度覆盖进来。
       *   ② 切到调度台 → 地图，让观众看见车沿线走（位置来自车端进度）。
       *   ③ 巡检记录**等四台车都收工再切**（见下），不写死秒数。
       */
      RC.startedRound = true
      vg.navigate('Home')
      T(function () { vg.dispatch('startRound', '') }, 300)
      T(function () { vg.navigate('Dispatch') }, 1200)
      T(function () { vg.navigate('Map') }, 2100)
      /*
       * 记录页不再用固定秒数切。原来写死 26 秒，是按"动画版 9 秒跑完"定的；
       * 换成真车后 0.15 m/s 跑完要 30~45 秒 —— 26 秒切过去，画面就变成
       * "车还在跑、屏幕已经停在记录页"，录制时这一条直接毁素材。
       * 现在改成**由车跑完驱动**：每 800 ms 看一次车端状态，四台车都收工才切。
       */
      T(function () {
        var iv = setInterval(function () {
          if (!RC.startedRound) { clearInterval(iv); return }
          var st = RC.lastState
          if (!st || !st.zones || !st.zones.length) { return }
          for (var i = 0; i < st.zones.length; i += 1) {
            var zoneStat = st.zones[i].status
            if (zoneStat !== 'done' && zoneStat !== 'blocked') { return }
          }
          ixTimers.push(iv)
          clearInterval(iv)
          vg.navigate('Records')
        }, 800)
        ixTimers.push(iv)
      }, 3000)
    }).catch(function (e) {
      btn.disabled = false
      setCarStatus('<b class="bad">本轮没有下发到车上</b><span class="dim">' +
        shortErr(e) + '</span>')
    })
  }

  btn.onclick = function () { demoRun() }

  btnReset.onclick = function () {
    clearAll()
    var store = window.VelaGuard.store
    /* 复位要**先停车**：只清界面台账、让车继续走，是很危险的假复位 */
    stopReal().catch(function () { /* 车端不在也继续复位界面 */ })
    store.cancelAll()
    store.resetCars()
    window.__vg.navigate('Home')
    fade(hint, 1, 350)
    RC.closedRound = 0
    setTimeout(function () { resetReal().catch(function () {}) }, 400)
  }

  /* 打开页面后就开始盯车端状态，让人一眼看出链路通不通 */
  setTimeout(poll, 300)

  /* 暴露给自动化测试/录屏脚本 */
  window.__demo = {
    run: demoRun,
    reset: function () { btnReset.onclick() },
    sync: syncNow,
    stop: stopReal,
    status: function () { return fetching('/patrol/status', null, 2500) }
  }
})();
</script></body></html>`

fs.writeFileSync(OUT, head + bundleOnly + demoHost, 'utf8')
const kb = Math.round(fs.statSync(OUT).size / 1024)
console.log('✓ 生成 ' + OUT + '  (' + kb + ' KB)')
console.log('  自包含单文件：内联 bundle + 演示宿主，无外部依赖')
