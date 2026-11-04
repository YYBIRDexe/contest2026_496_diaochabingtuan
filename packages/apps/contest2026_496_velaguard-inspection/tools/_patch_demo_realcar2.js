/**
 * _patch_demo_realcar2.js —— 真车联动补丁 ②：改用 store 的公开接口
 *
 * 为什么需要第二刀：第一版联动直接读 `store.tasks[zoneId]` 和 `store.round`，
 * 但 store 的默认导出里**没有** tasks / round 这两个字段（只有 zoneStates()、
 * startRound() 这些函数）。设备实拍确认：页面上确实弹出了
 * 「真车联动未连接 / store.tasks is undefined」—— 错误提示照设计工作了，
 * 但它说明取状态的方式是错的。
 *
 * 改法：用导出的 zoneStates() 拿每个区域的任务对象（它返回的就是内部 task
 * 的引用），在里面挑出车端说了算的字段改写。这也顺带把进度条的正确来源
 * 钉死了 —— zoneStates() 算的 progress 才是界面真正显示的数字。
 *
 * 同时把状态徽标从右上角（会被应用自己的状态栏压住）挪到按钮栏上方。
 *
 * 用法：
 *   node tools/_patch_demo_realcar2.js          # 打补丁
 *   node tools/_patch_demo_realcar2.js --check
 */
const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..')
const FILE = path.join(ROOT, 'tools', 'build-demo-e5.js')
const BACKUP = path.join(ROOT, 'tools', 'build-demo-e5.js.bak-before-realcar2')
// 判据必须用**只属于补丁 ② 的代码**。
// 踩过：原来用 "store.zoneStates()" 当判据 —— 那是 bundle 里本来就有的导出语句，
// 于是"是否已打补丁"永远为真，补丁 ② 静默不生效，设备上还是旧的报错。
const MARK = 'var rows = store.zoneStates()' + '\n'
const MARK_1 = 'store.tasks[z.id]'

let src = fs.readFileSync(FILE, 'utf8')

if (process.argv.includes('--check')) {
  console.log('补丁① ' + (src.indexOf(MARK_1) >= 0 ? '已打' : '未打') +
    ' / 补丁② ' + (src.indexOf(MARK) >= 0 ? '已打' : '未打'))
  process.exit(0)
}

if (src.indexOf(MARK) >= 0) {
  console.log('补丁 ② 已经打过，跳过（幂等）')
  process.exit(0)
}
if (src.indexOf(MARK_1) < 0) {
  console.error('✗ 找不到补丁 ① 的标记（' + MARK_1 + '），请先跑 _patch_demo_realcar.js')
  process.exit(1)
}
if (!fs.existsSync(BACKUP)) {
  fs.copyFileSync(FILE, BACKUP)
  console.log('备份 → ' + BACKUP)
}

/* ---- 1. applyStatus：改用 zoneStates() ---- */
const OLD_APPLY = `  function applyStatus(st) {
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
  }`

const NEW_APPLY = `  function applyStatus(st) {
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
  }`

/* ---- 2. 徽标位置：右上角会被应用状态栏压住，挪到按钮栏正上方 ---- */
const OLD_BADGE_CSS = `    '#carstat{position:absolute;right:22px;top:18px;z-index:10000;font-size:22px;',`
const NEW_BADGE_CSS = `    '#carstat{position:absolute;right:26px;bottom:150px;z-index:10000;font-size:22px;',`

/* ---- 3. 徽标里的错误文案：给出可照做的下一步 ---- */
const OLD_ERR = `      setCarStatus('<b class="bad">真车联动未连接</b><span class="dim">' +
        shortErr(e) + '<br>按下按钮不会让车动；先起车端执行器（见 README 真车联动一节）</span>')`
const NEW_ERR = `      setCarStatus('<b class="bad">真车联动未连接</b><span class="dim">' +
        shortErr(e) + '<br>按下按钮不会让车动。终端里跑：' +
        'bash ~/velaguard/demo/start-patrol.sh</span>')`

/* ---- 4. 收轮后立刻重绘：记录页读的是 store 台账，不重绘就还显示旧内容 ---- */
const MARK_ARCHIVE = '归档后必须重绘'
const OLD_ARCHIVE = `    /* 四台车都收工 → 归档成一条巡检记录（走 store 自己的台账逻辑） */
    try {
      window.VelaGuard.store.closeRound()
    } catch (e) { /* 归档失败不影响巡检本身 */ }`
const NEW_ARCHIVE = `    /* 四台车都收工 → 归档成一条巡检记录（走 store 自己的台账逻辑） */
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
    } catch (e) { /* 重绘失败不影响巡检本身 */ }`

let out = src
  .replace(OLD_APPLY, NEW_APPLY)
  .replace(OLD_BADGE_CSS, NEW_BADGE_CSS)
  .replace(OLD_ERR, NEW_ERR)
  .replace(OLD_ARCHIVE, NEW_ARCHIVE)

const missing = []
if (out.indexOf(MARK) < 0) { missing.push('applyStatus 未改') }
if (out.indexOf(MARK_1) >= 0) { missing.push('仍在使用 store.tasks') }
if (out.indexOf("bottom:150px;z-index:10000") < 0) { missing.push('徽标位置未调') }
if (out.indexOf('start-patrol.sh') < 0) { missing.push('错误文案未给出恢复命令') }
if (out.indexOf(MARK_ARCHIVE) < 0) { missing.push('收轮后未重绘') }
if (missing.length) {
  console.error('✗ 补丁没打全，未写入。缺：' + missing.join('、'))
  process.exit(1)
}

fs.writeFileSync(FILE, out, 'utf8')
console.log('✓ 已写入 ' + FILE)
console.log('  下一步：node tools/build-demo-e5.js')
