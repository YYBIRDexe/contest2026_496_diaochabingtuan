/**
 * _patch_demo_realcar.js —— 把「E5 演示页的开始巡检按钮」接到真车控制器上
 *
 * 改一个文件：tools/build-demo-e5.js（演示宿主模板的源头）
 * 改完必须重跑：node tools/build-demo-e5.js
 *
 * 为什么改模板而不是改产物：build/demo-e5.html 是**生成物**，
 * 直接改产物下次 build 就没了。
 *
 * 幂等：重复运行会先检测标记再决定是否写入；--revert 可回退。
 *
 * 用法：
 *   node tools/_patch_demo_realcar.js            # 打补丁
 *   node tools/_patch_demo_realcar.js --check    # 只看当前状态
 *   node tools/_patch_demo_realcar.js --revert   # 回退
 */
const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..')
const FILE = path.join(ROOT, 'tools', 'build-demo-e5.js')
const BACKUP = path.join(ROOT, 'tools', 'build-demo-e5.js.bak-before-realcar')
const MARK = 'VelaGuard 真车联动'

const REVERT = process.argv.includes('--revert')
const CHECK = process.argv.includes('--check')

let src = fs.readFileSync(FILE, 'utf8')
const patched = src.indexOf(MARK) >= 0

if (CHECK) {
  console.log(patched ? '已打补丁' : '未打补丁（原始模板）')
  process.exit(0)
}

if (REVERT) {
  if (!patched) {
    console.log('当前是原始模板，无需回退')
    process.exit(0)
  }
  if (!fs.existsSync(BACKUP)) {
    console.error('找不到备份 ' + BACKUP + '，拒绝回退（避免整文件写坏）')
    process.exit(1)
  }
  fs.copyFileSync(BACKUP, FILE)
  console.log('✓ 已回退到 ' + BACKUP)
  process.exit(0)
}

if (patched) {
  console.log('已经打过补丁，跳过（幂等）')
  process.exit(0)
}

if (!fs.existsSync(BACKUP)) {
  fs.copyFileSync(FILE, BACKUP)
  console.log('备份 → ' + BACKUP)
}

/* ---------------------------------------------------------------- 1. 样式 */
const OLD_CSS = `    '#hint b{display:block;font-size:32px;font-weight:700;color:#fff;margin-bottom:6px;}'
  ].join('')`
const NEW_CSS = `    '#hint b{display:block;font-size:32px;font-weight:700;color:#fff;margin-bottom:6px;}',

    /* ---------- 真车联动状态徽标 ----------
     * 演示页现在会去 127.0.0.1:8127 问「四台车跑到哪一步了」。
     * 链路不可用时必须**看得见**地提示，不能默默退化成纯动画 ——
     * 那正是这次要修的毛病（按了按钮车不动，界面上却像在跑）。 */
    '#carstat{position:absolute;right:22px;top:18px;z-index:10000;font-size:22px;',
    'line-height:1.35;color:#eaf2ff;background:rgba(11,18,32,.86);',
    'border:1px solid rgba(255,255,255,.14);border-radius:14px;padding:10px 16px;',
    'max-width:640px;pointer-events:none;text-shadow:0 1px 6px rgba(0,0,0,.9);}',
    '#carstat b{display:block;font-size:24px;}',
    '#carstat .ok{color:#3ddc84;}',
    '#carstat .busy{color:#4da3ff;}',
    '#carstat .bad{color:#ff6b6b;}',
    '#carstat .dim{color:#94a3b8;}'
  ].join('')`

/* ------------------------------------------------------- 2. 浮层 DOM */
const OLD_DOM = `  var bar = doc.createElement('div'); bar.id = 'bar'`
const NEW_DOM = `  /* ---------- 真车联动状态徽标 ---------- */
  var carStat = doc.createElement('div')
  carStat.id = 'carstat'
  carStat.innerHTML = '<b>真车联动</b><span class="dim">正在连接车端执行器…</span>'
  stage.appendChild(carStat)

  var bar = doc.createElement('div'); bar.id = 'bar'`

/* ------------------------------------------------- 3. 联动逻辑 + 按钮 */
const OLD_LOGIC = `  function demoRun() {
    clearAll()
    var vg = window.__vg`
const NEW_LOGIC = `  /* ================================================================== *
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
    var store = window.VelaGuard.store
    var zones = st.zones || []
    if (RC.closedRound !== st.round) {
      RC.closedRound = st.round
    }
    if (st.round && store.round !== st.round) {
      store.round = st.round
    }
    for (var i = 0; i < zones.length; i += 1) {
      var z = zones[i]
      var t = store.tasks[z.id]
      if (!t) { continue }
      var stat = z.status
      if (stat === 'aborted') { stat = 'blocked' }
      /* STATUS 字典只有五态，写进未登记的值会让 zoneStates() 直接抛错 */
      if (['pending', 'running', 'done', 'blocked'].indexOf(stat) < 0) { stat = 'running' }
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
  }

  function poll() {
    if (RC.once) { return }
    syncNow().then(function (st) {
      setBadgeFromState(st)
      maybeCloseRound(st)
    }).catch(function (e) {
      setCarStatus('<b class="bad">真车联动未连接</b><span class="dim">' +
        shortErr(e) + '<br>按下按钮不会让车动；先起车端执行器（见 README 真车联动一节）</span>')
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
    var vg = window.__vg`
/* --------------------------------------- 4. demoRun：改成车端驱动 */
const OLD_RUN = `  function demoRun() {
    clearAll()
    var vg = window.__vg
    /* 提示条退场放在 demoRun 内部，而不是按钮回调里 ——
       这样「点按钮」和「脚本调 __demo.run()」行为完全一致，截图验证才有意义 */
    fade(hint, 0, 350)

    /*
     * 时间轴依据（src/common/data.js 实测）：
     *   速度 0.8 m/s，最短一条路线 2.3 m + 停留 1.5 s ≈ 4.4 s 跑完一个区
     *   → 必须在开始后 ~2 s 内注入障碍，否则任务已完成，inject 会返回
     *     「当前是已完成，无法注入故障」（第一版就是这么错的，截图验证抓出来的）
     */

    /* 0s 开始本轮巡检（= 点首页「开始本轮巡检」） */
    vg.navigate('Home')
    T(function () { vg.dispatch('startRound', '') }, 300)

    /* 1.6s 切到调度台，此时任务刚下发、正在执行 */
    T(function () { vg.navigate('Dispatch') }, 1600)

    /* 2.6s 切到地图，能看见车正沿线走 */
    T(function () { vg.navigate('Map') }, 2600)

    /* 3.4s 注入障碍：车跑到一半遇障停车 —— 走真实 store 逻辑 */
    T(function () {
      var zs = window.VelaGuard.store.zoneStates()
      var target = null
      /* 优先挑「正在执行」的区域；实在没有就挑第一个有任务的 */
      for (var i = 0; i < zs.length; i++) {
        if (zs[i].status === 'running') { target = zs[i]; break }
      }
      if (!target) {
        for (var j = 0; j < zs.length; j++) {
          if (zs[j].taskId) { target = zs[j]; break }
        }
      }
      if (!target) { return }
      vg.navigate('Dispatch')
      T(function () { vg.dispatch('inject', target.id) }, 500)
    }, 3400)

    /* 9s 切到巡检记录，展示阻塞统计与轮次结论 */
    T(function () { vg.navigate('Records') }, 9000)
  }
`

const NEW_RUN = `  function demoRun() {
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
       *   ③ 26 秒后切巡检记录：0.15 m/s 跑完 2.3~2.7 m 要 15~20 秒，
       *      留足余量，此时记录页里已经是真实结论。
       */
      vg.navigate('Home')
      T(function () { vg.dispatch('startRound', '') }, 300)
      T(function () { vg.navigate('Dispatch') }, 1200)
      T(function () { vg.navigate('Map') }, 2100)
      T(function () { vg.navigate('Records') }, 26000)
    }).catch(function (e) {
      btn.disabled = false
      setCarStatus('<b class="bad">本轮没有下发到车上</b><span class="dim">' +
        shortErr(e) + '</span>')
    })
  }
`

/* ------------------------------------- 5. 按钮：先下发真车，再演出 */
const OLD_BTN = `  btn.onclick = function () { demoRun() }
  btnReset.onclick = function () {
    clearAll()
    var store = window.VelaGuard.store
    store.cancelAll()
    store.resetCars()
    window.__vg.navigate('Home')
    fade(hint, 1, 350)
  }

  /* 暴露给自动化测试/录屏脚本 */
  window.__demo = {
    run: demoRun,
    reset: function () { btnReset.onclick() }
  }`

const NEW_BTN = `  btn.onclick = function () { demoRun() }

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
  }`

let out = src
  .replace(OLD_CSS, NEW_CSS)
  .replace(OLD_DOM, NEW_DOM)
  .replace(OLD_LOGIC, NEW_LOGIC)
  .replace(OLD_RUN, NEW_RUN)
  .replace(OLD_BTN, NEW_BTN)

/* 每一处都必须真的替换成功，否则宁可不写 —— 半成品模板比不打补丁更糟 */
const missing = []
if (out.indexOf(MARK) < 0) { missing.push('联动逻辑') }
if (out.indexOf('startReal()') < 0) { missing.push('按钮下发') }
if (out.indexOf('carstat') < 0) { missing.push('状态徽标') }
if (out.indexOf("vg.dispatch('inject', target.id)") >= 0) {
  missing.push('旧的定时注入障碍仍然在（应已移除）')
}
if (out.indexOf("T(function () { vg.navigate('Records') }, 9000)") >= 0) {
  missing.push('旧的 9 秒切记录页仍然在（应已改为车端驱动）')
}
if (out.indexOf("window.__demo = {") < 0 || out.indexOf('sync: syncNow') < 0) {
  missing.push('__demo 句柄未更新')
}
if (missing.length) {
  console.error('✗ 补丁没打全，未写入。缺：' + missing.join('、'))
  process.exit(1)
}

fs.writeFileSync(FILE, out, 'utf8')
console.log('✓ 已写入 ' + FILE)
console.log('  下一步：node tools/build-demo-e5.js  （产物会带上真车联动）')
