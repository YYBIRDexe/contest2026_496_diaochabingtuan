/**
 * VelaGuard · 端侧任务状态机（openvela 快应用版）
 *
 * 这个文件承载方案二的功能二、三、四：
 *   功能二 任务派单与结果回收 —— dispatch / tick / 状态流转
 *   功能三 异常中断与人工处置 —— 阻塞判定 + 重派 / 取消 / 顺延
 *   功能四 巡检覆盖的基础汇总 —— summarize / 每轮记录
 *
 * 三条设计原则（对应方案的红线）：
 *  1. **路线只认编号**：派单只传 route 编号，坐标/速度由 CFG 里的预设路线决定，
 *     调用方无法传入任意坐标。
 *  2. **越界即拒发，不静默改成边界值**：参数不合规返回 {ok:false}，不留后门。
 *  3. **离线车不得被派单**：在线状态先判，再谈派单。
 *
 * 本文件是纯逻辑，不碰界面、不碰宿主 API，因此可以直接在 Node 里跑单测。
 */
import CFG from './data.js'

const STATUS = CFG.STATUS

/* ------------------------------------------------------------------ *
 * 内部状态：任务表 + 轮次
 * ------------------------------------------------------------------ */
let seq = 1000
let round = 0
/** 本轮各区域的最新任务，key 是 zoneId */
let tasks = {}
/** 历史轮次台账 */
let records = []
/** 事件回调（界面订阅后用于主动弹提示） */
let emitter = null

/**
 * 虚拟时钟（毫秒）。
 *
 * 为什么不直接用 Date.now()：失联判定是**方案二功能三的核心**（连续 N 秒无回执 →
 * 判失联），如果读墙钟，这条逻辑在自动化测试里就必须真等 20 秒，实际上等于没测。
 * 改成由 tick(dt) 推进的虚拟时钟后，20 秒的超时可以在一次循环里验完。
 * 界面侧每个 tick 传真实经过的秒数，行为与墙钟一致。
 */
let clock = Date.now()

function nowText() {
  const d = new Date()
  const pad = function (n) { return n < 10 ? '0' + n : '' + n }
  return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds())
}

function makeTask(zone, car) {
  seq += 1
  const pts = CFG.routePoints(zone.route)
  return {
    /* --- 任务单字段（与 patrol_proto.py 的 task 消息一一对应） --- */
    taskId: 'T-' + seq,
    seq: seq,
    robot: car ? car.id : '',
    zoneId: zone.id,
    zoneName: zone.name,
    route: zone.route,
    status: 'pending',
    /* --- 执行进度 --- */
    leg: 0,              // 正在走的第几段（0 = 从起点到第 1 个航点）
    legProgress: 0,      // 当前段完成比例 0~1
    legDone: false,      // 当前段终点已到达（正在停留）
    dwellLeft: 0,        // 当前航点还要停多久
    x: pts.length ? pts[0].x : 0,
    y: pts.length ? pts[0].y : 0,
    yaw: pts.length ? pts[0].yaw : 0,
    totalLegs: Math.max(0, pts.length - 1),
    points: pts,
    /* --- 台账 --- */
    round: round,
    startedAt: 0,
    finishedAt: 0,
    elapsed: 0,
    lastReceiptAt: 0,
    /**
     * 静默标记：为真时车端「不回话」——回执时间不再刷新，于是必然触发失联判定。
     * 演示里靠它把「阈值主动」这条能力做得**可复现**（不用真去拔网线）。
     */
    silent: false,
    reason: '',
    detail: '等待派单'
  }
}

/* ------------------------------------------------------------------ *
 * 功能二：任务派单与结果回收
 * ------------------------------------------------------------------ */

/**
 * 派单。只接受 zoneId —— 路线由区域登记表决定，不接受外部坐标。
 * 返回 {ok, message, taskId?}
 */
export function dispatch(zoneId) {
  const zone = CFG.zoneById(zoneId)
  if (!zone) {
    return { ok: false, message: '区域不存在：' + zoneId }
  }
  const car = CFG.carById(zone.car)
  if (!car) {
    return { ok: false, message: zone.name + ' 未登记车辆，派单已拒绝' }
  }
  if (!car.online) {
    return { ok: false, message: car.name + ' 离线，拒绝派单（离线车不得被派单）' }
  }
  if (car.battery < CFG.LIMITS.battery_min) {
    return { ok: false, message: car.name + ' 电量 ' + car.battery + '% 低于 ' +
      CFG.LIMITS.battery_min + '%，不派单' }
  }
  if (!CFG.ROUTES[zone.route]) {
    return { ok: false, message: '区域 ' + zone.name + ' 的路线 ' + zone.route + ' 未登记' }
  }
  const old = tasks[zoneId]
  if (old && old.status === 'running') {
    return { ok: false, message: zone.name + ' 已有任务在执行（' + old.taskId + '）' }
  }

  const t = makeTask(zone, car)
  tasks[zoneId] = t
  return { ok: true, taskId: t.taskId, message: '已向 ' + car.name + ' 下发「' + zone.name + '」任务单 ' + t.taskId }
}

/** 取消某个区域的任务 */
export function cancel(zoneId) {
  const t = tasks[zoneId]
  if (!t) {
    return { ok: false, message: '该区域没有任务' }
  }
  if (t.status === 'done') {
    return { ok: false, message: t.zoneName + ' 已完成，无需取消' }
  }
  t.status = 'cancelled'
  t.detail = '人工取消'
  t.reason = 'cancelled'
  t.finishedAt = clock
  return { ok: true, message: '已取消「' + t.zoneName + '」任务 ' + t.taskId }
}

/** 一键取消本轮全部未完成任务 */
export function cancelAll() {
  let n = 0
  for (let i = 0; i < CFG.ZONES.length; i += 1) {
    const t = tasks[CFG.ZONES[i].id]
    if (t && (t.status === 'running' || t.status === 'blocked' || t.status === 'pending')) {
      t.status = 'cancelled'
      t.detail = '一键取消'
      t.reason = 'cancelled'
      t.finishedAt = clock
      n += 1
    }
  }
  return { ok: true, message: n > 0 ? '已取消 ' + n + ' 个未完成任务' : '当前没有待取消的任务' }
}

/**
 * 功能三：异常中断的人工处置。
 * 阻塞/失联任务可以「重派」——把同一区域的路线上顺延给登记表中的下一台**在线**车。
 * 找不到可用车就如实说找不到，不做假成功。
 */
export function reassign(zoneId) {
  const t = tasks[zoneId]
  const zone = CFG.zoneById(zoneId)
  if (!zone) {
    return { ok: false, message: '区域不存在' }
  }
  if (!t) {
    return dispatch(zoneId)
  }
  /* 候选车：在线、电量够、且不是当前这台 */
  const candidates = CFG.CARS.filter(function (c) {
    return c.online && c.battery >= CFG.LIMITS.battery_min && c.id !== t.robot
  })
  if (candidates.length === 0) {
    return { ok: false, message: '没有其它在线车辆可承接「' + zone.name + '」，建议顺延到下一轮' }
  }
  const car = candidates[0]
  const nt = makeTask(zone, car)
  nt.status = 'pending'
  nt.detail = '由 ' + t.robot + ' 改派而来（原任务 ' + t.taskId + ' ' + STATUS[t.status].text + '）'
  tasks[zoneId] = nt
  return { ok: true, taskId: nt.taskId, message: '「' + zone.name + '」已改派给 ' + car.name + '（' + nt.taskId + '）' }
}

/** 把某轮未完成的区域顺延到下一轮 */
export function postpone(zoneId) {
  const t = tasks[zoneId]
  if (!t) {
    return { ok: false, message: '该区域没有任务' }
  }
  t.status = 'cancelled'
  t.detail = '已顺延到下一轮'
  t.reason = 'postponed'
  t.finishedAt = clock
  return { ok: true, message: '「' + t.zoneName + '」已顺延到下一轮' }
}

/* ------------------------------------------------------------------ *
 * 功能三：推进与异常判定
 * ------------------------------------------------------------------ */

/** 记录一次回执（心跳）。静默中的车不发，于是必然被判失联。 */
function receipt(t) {
  if (!t.silent) {
    t.lastReceiptAt = clock
  }
}

/**
 * 到达第 leg 段的终点航点。
 *
 * 三种情形分开处理，这是修掉「卡在某个航点永远不走」的关键：
 *  · 是最后一段 —— 置 legDone 并进入停留，停留结束才结算完成
 *  · dwell > 0  —— 置 legDone 并进入停留
 *  · dwell = 0  —— 立刻结算这一段，leg 前进，**不要**置 legDone
 *    （早期版本无条件置 legDone，遇到 dwell=0 的航点就再也没人推进 leg，
 *     任务永远停在那里，20 秒后被误判成失联）
 */
function arrive(t) {
  const to = t.points[t.leg + 1]
  t.x = to.x
  t.y = to.y
  t.yaw = to.yaw
  t.legProgress = 1
  t.detail = '已到达 ' + to.name + '（' + fmt(t.x) + ', ' + fmt(t.y) + '）'

  if (t.leg + 1 >= t.points.length - 1) {
    /*
     * 刚走完的是**最后一段**（段号从 0 数，最后一段是 points.length - 2）。
     * 判据必须是「leg + 1 >= points.length - 1」，不能写成
     * 「t.leg >= t.totalLegs」——后者在最后一段到达时不成立
     * （leg 那时是 totalLegs - 1），于是永远进不了收尾分支，
     * 表现为车停在终点、文案也写了"路线执行完毕"，状态却一直是进行中。
     */
    t.dwellLeft = to.dwell > 0 ? to.dwell : 0.0001
    t.legDone = true
    return
  }
  if (to.dwell > 0) {
    t.dwellLeft = to.dwell
    t.legDone = true
    return
  }
  t.leg += 1
  t.legProgress = 0
  const nt = t.points[t.leg + 1]
  t.detail = '通过 ' + to.name + '，前往 ' + nt.name
}

/** 让一个运行中的任务沿路线前进 dt 秒 */
function advance(t, dt) {
  /*
   * 已结束的任务一律不再推进。
   * 少了这一句会出很隐蔽的 bug：finish() 在停留分支里被调用后，下一次 tick
   * 又会进来把 legDone 清掉、leg 继续往前推（此时 leg 已等于 totalLegs），
   * 于是状态字段被反复改写、进度卡在 75%，表现为"永远跑不完"。
   */
  if (t.status !== 'running') {
    return
  }

  const speed = CFG.LIMITS.demo_speed_mps
  t.elapsed += dt

  /* --- 正在航点上停留 --- */
  if (t.dwellLeft > 0) {
    t.dwellLeft -= dt
    if (t.dwellLeft <= 0) {
      t.dwellLeft = 0
      /* 判据要与 arrive 里一致：刚停留完的是不是**最后一个**航点 */
      if (t.leg + 1 >= t.points.length - 1) {
        /* 最后一个航点停留结束 —— 整条路线到这里才算真正走完 */
        finish(t, '路线执行完毕，未发现异常')
        return
      }
      t.leg += 1
      t.legProgress = 0
      t.legDone = false
      const nt = t.points[t.leg + 1]
      t.detail = nt
        ? ('离开 ' + t.points[t.leg].name + '，前往 ' + nt.name)
        : '路线执行完毕'
    }
    return
  }

  if (t.legDone || t.leg + 1 > t.points.length - 1) {
    return
  }

  /* --- 正常行进：这一段是从 points[leg] 到 points[leg+1] --- */
  const from = t.points[t.leg]
  const to = t.points[t.leg + 1]
  const dx = to.x - from.x
  const dy = to.y - from.y
  const len = Math.sqrt(dx * dx + dy * dy)

  if (len < 1e-6) {
    t.legProgress = 1
  } else {
    t.legProgress += (speed * dt) / len
  }
  if (t.legProgress > 1) {
    t.legProgress = 1
  }
  t.x = from.x + dx * t.legProgress
  t.y = from.y + dy * t.legProgress
  t.yaw = Math.atan2(dy, dx)

  if (t.legProgress >= 1) {
    arrive(t)
  } else {
    t.detail = '行进中 ' + Math.round(t.legProgress * 100) + '% → ' + to.name
  }
}

function fmt(v) {
  return v.toFixed(2)
}

function finish(t, detail) {
  t.status = 'done'
  t.detail = detail
  /*
   * 必须把 leg 推到终点、legProgress 归 1：
   * 进度 = (leg + legProgress) / (totalLegs + 1)。最后一个航点到达时
   * leg 还停在 totalLegs - 1，不收尾的话界面会显示 75% + "已完成"，
   * 一眼就是个假数字。
   */
  t.leg = t.totalLegs
  t.legProgress = 1
  t.legDone = true
  t.dwellLeft = 0
  t.finishedAt = clock
}

/**
 * 阈值主动：连续 N 秒收不到回执 → 判失联 → 阻塞。
 * 返回 true 表示这次判定把任务转成了阻塞（调用方据此不再重复处理）。
 */
function judgeTimeout(t, zid, events) {
  if (t.silent || clock - t.lastReceiptAt > CFG.LIMITS.receipt_timeout_s * 1000) {
    t.status = 'blocked'
    t.reason = t.silent ? 'silent' : 'timeout'
    t.detail = '连续 ' + CFG.LIMITS.receipt_timeout_s + ' 秒未收到回执，判定失联'
    t.finishedAt = clock
    events.push({
      type: 'blocked',
      zoneId: zid,
      text: '连续 ' + CFG.LIMITS.receipt_timeout_s + ' 秒未收到 ' + t.robot + ' 回报，判定失联，已将其区域顺延。'
    })
    return true
  }
  /* 时限判定：整条路线跑太久（不是卡在某一步）也算异常，但优先级低于失联 */
  if (t.elapsed > CFG.LIMITS.task_deadline_s) {
    t.status = 'blocked'
    t.reason = 'deadline'
    t.detail = '超过任务时限 ' + CFG.LIMITS.task_deadline_s + ' 秒'
    t.finishedAt = clock
    events.push({ type: 'blocked', zoneId: zid, text: t.zoneName + ' 超过时限，任务挂起。' })
    return true
  }
  return false
}

/**
 * 时钟推进：先推进虚拟时钟，再跑所有 running 任务，并做两类**主动判定**。
 * 返回本 tick 产生的事件列表（供界面/Agent 主动告警用）。
 *
 * dt 单位秒，由调用方给「距上次 tick 真实过了多久」。
 */
export function tick(dt) {
  const step = typeof dt === 'number' && dt > 0 ? dt : 0
  clock += step * 1000
  const events = []

  for (let i = 0; i < CFG.ZONES.length; i += 1) {
    const zid = CFG.ZONES[i].id
    const t = tasks[zid]
    if (!t || t.status !== 'running') {
      continue
    }

    /*
     * 判定顺序很重要：**先判失联，再推进**。
     * 反过来的话，正常行进中的车会在 advance 里刷新回执时间，
     * 于是「静默的车」永远判不出来（这个顺序 bug 是测试抓到的）。
     */
    if (judgeTimeout(t, zid, events)) {
      continue
    }
    advance(t, step)
    /* 只要还在跑就算收到回执（含原地停留阶段），静默的车不发 */
    receipt(t)
    if (t.status === 'done') {
      events.push({
        type: 'done',
        zoneId: zid,
        text: t.zoneName + ' 已完成（' + Math.round(t.elapsed) + ' 秒）。'
      })
    }
  }
  return events
}

/**
 * 让某台车「不回话」：它的任务在下一次 tick 就会被判失联。
 * 这是把方案二的「阈值主动」做成**可复现演示**的抓手——不用真去拔网线。
 */
export function silence(zoneId) {
  const t = tasks[zoneId]
  if (!t) {
    return { ok: false, message: '该区域没有任务' }
  }
  t.silent = true
  return { ok: true, message: t.robot + ' 回执通道已静默（下一次判定即失联）' }
}

/** 恢复回话 */
export function unsilence(zoneId) {
  const t = tasks[zoneId]
  if (!t) {
    return { ok: false, message: '该区域没有任务' }
  }
  t.silent = false
  t.lastReceiptAt = clock
  return { ok: true, message: t.robot + ' 回执通道已恢复' }
}

export function now() {
  return clock
}

/** 派单后启动（pending → running） */
export function start(zoneId) {
  const t = tasks[zoneId]
  if (!t) {
    return { ok: false, message: '该区域没有任务' }
  }
  if (t.status !== 'pending') {
    return { ok: false, message: t.zoneName + ' 当前是' + STATUS[t.status].text + '，无法启动' }
  }
  t.status = 'running'
  t.startedAt = clock
  t.lastReceiptAt = clock
  t.elapsed = 0
  t.detail = '路线开始，前往 ' + (t.points[1] ? t.points[1].name : '终点')
  return { ok: true, message: t.zoneName + ' 已开始执行' }
}

/**
 * 一键「开始本轮巡检」：开新一轮 → 派单所有区域 → 立即启动。
 * 这是演示里的主按钮。
 *
 * 注意：**不在这里复位车辆在线状态** —— 「置离线」是给人看的故障注入，
 * 要能一直留到演示者手动恢复，否则"离线车不派单"这条就演示不出来了。
 * 需要恢复时用 resetCars()。
 */
export function startRound() {
  round += 1
  tasks = {}
  const msgs = []
  let started = 0
  for (let i = 0; i < CFG.ZONES.length; i += 1) {
    const zid = CFG.ZONES[i].id
    const r = dispatch(zid)
    if (!r.ok) {
      msgs.push(CFG.zoneById(zid).name + '：' + r.message)
      continue
    }
    const s = start(zid)
    if (s.ok) {
      started += 1
    } else {
      msgs.push(s.message)
    }
  }
  return {
    ok: started > 0,
    round: round,
    started: started,
    message: '第 ' + round + ' 轮已开始，' + started + ' 个区域派单成功' +
      (msgs.length ? '；' + msgs.join('；') : '')
  }
}

/* ------------------------------------------------------------------ *
 * 模拟故障注入（演示功能三用；同时是测试的抓手）
 * ------------------------------------------------------------------ */

/** 让某台车「遇障停车」：任务立刻转阻塞，理由 obstacle。 */
export function injectObstacle(zoneId, note) {
  const t = tasks[zoneId]
  if (!t) {
    return { ok: false, message: '该区域没有任务' }
  }
  if (t.status !== 'running' && t.status !== 'pending') {
    return { ok: false, message: t.zoneName + ' 当前是' + STATUS[t.status].text + '，无法注入故障' }
  }
  t.status = 'blocked'
  t.reason = 'obstacle'
  t.detail = note || '前方有障碍，已停车待处置'
  t.finishedAt = clock
  return {
    ok: true,
    message: t.robot + ' 遇到障碍已停止，其余车辆保持原位，建议单独改派或取消。'
  }
}

/** 让某台车掉线（用于演示离线车不被派单） */
export function setCarOnline(carId, online) {
  const car = CFG.carById(carId)
  if (!car) {
    return { ok: false, message: '车辆不存在' }
  }
  car.online = !!online
  return { ok: true, message: car.name + (online ? ' 已上线' : ' 已离线') }
}

/**
 * 把所有车辆恢复在线。
 * 「置离线」是给人看的故障注入，一旦点过就会留在状态里；
 * 演示/测试要恢复到干净起点时调这个，而不是偷偷在别处复位。
 */
export function resetCars() {
  for (let i = 0; i < CFG.CARS.length; i += 1) {
    CFG.CARS[i].online = true
  }
  return { ok: true, message: '四台车已恢复为在线' }
}

/* ------------------------------------------------------------------ *
 * 功能四：覆盖汇总 + 轮次台账
 * ------------------------------------------------------------------ */

/** 每个区域的展示态（含由车在线状态推导出来的离线态） */
export function zoneStates() {
  const out = []
  for (let i = 0; i < CFG.ZONES.length; i += 1) {
    const z = CFG.ZONES[i]
    const t = tasks[z.id]
    const car = CFG.carById(z.car)
    let status = 'pending'
    let detail = '等待派单'
    let progress = 0
    let taskId = ''
    if (t) {
      status = t.status
      detail = t.detail
      taskId = t.taskId
      progress = t.totalLegs > 0
        ? Math.round(((t.leg + t.legProgress) / (t.totalLegs + 1)) * 100)
        : (t.status === 'done' ? 100 : 0)
      if (t.status === 'done') {
        progress = 100
      }
    }
    if (car && !car.online && status !== 'done') {
      status = 'offline'
      detail = car.name + ' 离线，任务未派出'
    }
    /* 任务实际派给的那台车可能**不是**登记车（改派之后就不一样了）。
       两个都暴露出去：界面显示"谁在执行"要用 taskCar，
       而"这个区域的登记车是谁"用 car。只给 car 会让人误以为改派没生效。 */
    const taskCar = car && t && t.robot ? (CFG.carById(t.robot) || null) : null
    out.push({
      id: z.id,
      name: z.name,
      route: z.route,
      routeName: CFG.ROUTES[z.route].name,
      routeDesc: CFG.ROUTES[z.route].desc,
      car: z.car,
      carName: car ? car.name : z.car,
      taskCar: t && t.robot ? t.robot : '',
      taskCarName: taskCar ? taskCar.name : (t && t.robot ? t.robot : '—'),
      status: status,
      statusText: STATUS[status].text,
      color: STATUS[status].color,
      detail: detail,
      progress: progress,
      taskId: taskId,
      lengthM: CFG.routeLength(z.route).toFixed(1)
    })
  }
  return out
}

/** 各区域车辆的当前位置（供地图页画小车标记；没有任务的区域不出现） */
export function vehiclePositions() {
  const out = {}
  for (let i = 0; i < CFG.ZONES.length; i += 1) {
    const zid = CFG.ZONES[i].id
    const t = tasks[zid]
    if (!t) {
      continue
    }
    out[zid] = {
      x: t.x,
      y: t.y,
      yaw: t.yaw,
      leg: t.leg,
      totalLegs: t.totalLegs,
      progress: t.status === 'done'
        ? 100
        : (t.totalLegs > 0
          ? Math.round(((t.leg + t.legProgress) / (t.totalLegs + 1)) * 100)
          : 0),
      status: t.status
    }
  }
  return out
}

/**
 * 覆盖汇总：功能四只汇总**任务状态**，
 * 不传输实时视频、不承诺视觉识别结论。
 */
export function summarize() {
  const counts = { pending: 0, running: 0, done: 0, blocked: 0, cancelled: 0, offline: 0 }
  const zs = zoneStates()
  for (let i = 0; i < zs.length; i += 1) {
    counts[zs[i].status] += 1
  }
  const needAction = counts.blocked + counts.offline
  return {
    round: round,
    total: zs.length,
    counts: counts,
    doneText: counts.done + ' / ' + zs.length,
    needAction: needAction
  }
}

/** 本轮一句话结论（也可直接由 Agent 朗读） */
export function summaryLine() {
  const s = summarize()
  if (s.round === 0) {
    return '尚未开始巡检'
  }
  const parts = []
  const zs = zoneStates()
  for (let i = 0; i < zs.length; i += 1) {
    parts.push(zs[i].name + zs[i].statusText)
  }
  return '第 ' + s.round + ' 轮：' + parts.join('、')
}

/** 收轮：把本轮结果写进台账，形成可追溯记录 */
export function closeRound() {
  const zs = zoneStates()
  if (round === 0) {
    return { ok: false, message: '还没有开始过巡检' }
  }
  const zones = zs.map(function (z) {
    return { name: z.name, result: z.status, resultText: z.statusText }
  })
  const s = summarize()
  let summary
  if (s.needAction > 0) {
    summary = s.counts.done + ' 区已完成，' + s.counts.blocked + ' 区阻塞待处置，' + s.counts.offline + ' 区车辆离线'
  } else if (s.counts.running > 0 || s.counts.pending > 0) {
    summary = '本轮尚未走完，' + s.counts.done + ' 区已收回结果'
  } else {
    summary = '四区全部完成，本轮无异常'
  }
  const rec = { round: '第 ' + round + ' 轮', time: nowText(), zones: zones, summary: summary }
  records.unshift(rec)
  if (records.length > 12) {
    records.pop()
  }
  return { ok: true, record: rec, message: '第 ' + round + ' 轮已归档：' + summary }
}

export function getRecords() {
  return records.map(function (r) {
    return { round: r.round, time: r.time, summary: r.summary, zones: r.zones.slice() }
  })
}

/** 供「跨轮次记忆」用的摘要：上轮哪些区域没完成 */
export function memoryOfLastRound() {
  if (records.length === 0) {
    return null
  }
  const last = records[0]
  const bad = last.zones.filter(function (z) {
    return z.result !== 'done'
  })
  if (bad.length === 0) {
    return null
  }
  const names = bad.map(function (z) { return z.name }).join('、')
  return { round: last.round, zones: names, text: last.round + ' ' + names + ' 未完成，本轮建议优先安排。' }
}

/* ------------------------------------------------------------------ *
 * 订阅与快照
 * ------------------------------------------------------------------ */
export function onEvent(fn) {
  emitter = fn
}

export function emit(evt) {
  if (emitter) {
    emitter(evt)
  }
}

export function snapshot() {
  return {
    round: round,
    zones: zoneStates(),
    cars: CFG.CARS.map(function (c) {
      return Object.assign({}, c)
    }),
    summary: summarize(),
    summaryLine: summaryLine(),
    records: getRecords(),
    map: CFG.MAP,
    waypoints: CFG.WAYPOINTS,
    routes: CFG.ROUTES
  }
}

/** 仅测试用：把状态机复位 */
export function __reset() {
  seq = 1000
  round = 0
  tasks = {}
  records = []
  emitter = null
  clock = Date.now()
}

export default {
  dispatch: dispatch,
  cancel: cancel,
  cancelAll: cancelAll,
  reassign: reassign,
  postpone: postpone,
  start: start,
  startRound: startRound,
  tick: tick,
  silence: silence,
  unsilence: unsilence,
  now: now,
  injectObstacle: injectObstacle,
  setCarOnline: setCarOnline,
  resetCars: resetCars,
  zoneStates: zoneStates,
  vehiclePositions: vehiclePositions,
  summarize: summarize,
  summaryLine: summaryLine,
  closeRound: closeRound,
  getRecords: getRecords,
  memoryOfLastRound: memoryOfLastRound,
  snapshot: snapshot,
  onEvent: onEvent,
  emit: emit
}
