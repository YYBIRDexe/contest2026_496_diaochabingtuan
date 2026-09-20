/**
 * VelaGuard 端侧数据源
 *
 * 首期为「端侧预设表」：区域 / 车辆 / 任务在此文件中维护，
 * 不依赖云端与数据库，符合 openvela 端侧闭环的定位。
 *
 * 后续接入 C1 局域网时，只需把 dispatchTask / reportResult 换成
 * 真实的任务单下发与状态回执处理，页面层无需改动。
 *
 * 说明：本文件同时被快应用（app.ux import）与浏览器预览页使用，
 * 故不对顶层做任何宿主相关判断，只导出纯数据与方法。
 */

/* ------------------------------------------------------------------ *
 * 1. 区域表：区域编号即责任划分，1 个区域对应 1 台编号巡检车
 * ------------------------------------------------------------------ */
const ZONES = [
  {
    id: 'Z1',
    name: '入口大厅',
    route: 'R-01',
    routeDesc: '前台 → 闸机 → 电梯口',
    car: 'CAR-1',
    status: 'done',
    statusText: '已完成',
    progress: 100,
    detail: '地面无杂物，闸机通行正常',
    duration: '3 分 12 秒'
  },
  {
    id: 'Z2',
    name: '主通道',
    route: 'R-02',
    routeDesc: 'A 段 → B 段 → C 段',
    car: 'CAR-2',
    status: 'running',
    statusText: '进行中',
    progress: 62,
    detail: '正在通过 B 段，暂无障碍',
    duration: '1 分 48 秒'
  },
  {
    id: 'Z3',
    name: '展项区',
    route: 'R-03',
    routeDesc: '展台 1 → 展台 4 绕行',
    car: 'CAR-3',
    status: 'blocked',
    statusText: '阻塞',
    progress: 38,
    detail: '展台 2 前有纸箱挡道，已停车待处置',
    duration: '54 秒'
  },
  {
    id: 'Z4',
    name: '设备区',
    route: 'R-04',
    routeDesc: '配电柜 → 机柜背面',
    car: 'CAR-4',
    status: 'idle',
    statusText: '未开始',
    progress: 0,
    detail: '等待派单',
    duration: '—'
  }
]

/* ------------------------------------------------------------------ *
 * 2. 车辆表：每台车使用独立网段地址，避免重复接单
 * ------------------------------------------------------------------ */
const CARS = [
  { id: 'CAR-1', zoneId: 'Z1', zone: '入口大厅', ip: '192.168.4.11', online: true, battery: 86, link: '良好' },
  { id: 'CAR-2', zoneId: 'Z2', zone: '主通道', ip: '192.168.4.12', online: true, battery: 72, link: '良好' },
  { id: 'CAR-3', zoneId: 'Z3', zone: '展项区', ip: '192.168.4.13', online: true, battery: 64, link: '良好' },
  { id: 'CAR-4', zoneId: 'Z4', zone: '设备区', ip: '192.168.4.14', online: false, battery: 0, link: '离线' }
]

/* ------------------------------------------------------------------ *
 * 3. 状态字典：任务状态机的 5 种态
 * ------------------------------------------------------------------ */
const STATUS = {
  done: { text: '已完成', color: '#3DDC84', bg: 'rgba(61,220,132,0.16)' },
  running: { text: '进行中', color: '#4DA3FF', bg: 'rgba(77,163,255,0.16)' },
  blocked: { text: '阻塞', color: '#FF6B6B', bg: 'rgba(255,107,107,0.16)' },
  idle: { text: '未开始', color: '#94A3B8', bg: 'rgba(148,163,184,0.16)' },
  offline: { text: '离线', color: '#FBBF24', bg: 'rgba(251,191,36,0.16)' }
}

/* ------------------------------------------------------------------ *
 * 4. 巡检记录：按轮次留存，形成可追溯台账
 * ------------------------------------------------------------------ */
const RECORDS = [
  {
    round: '第 3 轮',
    time: '今天 14:20',
    zones: [
      { name: '入口大厅', result: 'done' },
      { name: '主通道', result: 'running' },
      { name: '展项区', result: 'blocked' },
      { name: '设备区', result: 'idle' }
    ],
    summary: '3 区已收回结果，1 区阻塞待重派'
  },
  {
    round: '第 2 轮',
    time: '今天 11:05',
    zones: [
      { name: '入口大厅', result: 'done' },
      { name: '主通道', result: 'done' },
      { name: '展项区', result: 'done' },
      { name: '设备区', result: 'done' }
    ],
    summary: '四区全部完成，无异常'
  },
  {
    round: '第 1 轮',
    time: '昨天 16:40',
    zones: [
      { name: '入口大厅', result: 'done' },
      { name: '主通道', result: 'done' },
      { name: '展项区', result: 'offline' },
      { name: '设备区', result: 'idle' }
    ],
    summary: '展项区车辆离线，任务未派出'
  }
]

/* ------------------------------------------------------------------ *
 * 5. 数据访问与汇总（功能四：巡检覆盖的基础汇总）
 * ------------------------------------------------------------------ */
export function getZones() {
  return ZONES.map(function (z) {
    return Object.assign({}, z)
  })
}

export function getCars() {
  return CARS.map(function (c) {
    return Object.assign({}, c)
  })
}

export function getRecords() {
  return RECORDS.map(function (r) {
    return {
      round: r.round,
      time: r.time,
      summary: r.summary,
      zones: r.zones.map(function (z) {
        return { name: z.name, result: z.result }
      })
    }
  })
}

export function statusOf(key) {
  return STATUS[key] || STATUS.idle
}

/**
 * 一轮巡检的覆盖汇总，供桌面概览卡片使用。
 */
export function summarize() {
  const counts = { done: 0, running: 0, blocked: 0, idle: 0, offline: 0 }
  ZONES.forEach(function (z) {
    const key = CARS.filter(function (c) {
      return c.id === z.car
    })[0]
    if (key && !key.online) {
      counts.offline += 1
    } else {
      counts[z.status] += 1
    }
  })
  return {
    total: ZONES.length,
    counts: counts,
    doneText: counts.done + ' / ' + ZONES.length,
    needAction: counts.blocked + counts.offline
  }
}

/* ------------------------------------------------------------------ *
 * 6. 派单与取消（功能二：任务派单与结果回收）
 *
 * 真实实现应在此处通过 C1 Wi-Fi 发送「任务单」报文：
 *   任务序号 / 目标车辆 / 区域或路线编号 / 取消标记
 * 并等待带同一任务序号的「状态回执」。
 * 首期用内存状态代替，保证界面闭环可演示。
 * ------------------------------------------------------------------ */
let taskSeq = 1000

export function dispatchTask(zoneId) {
  const zone = ZONES.filter(function (z) {
    return z.id === zoneId
  })[0]
  if (!zone) {
    return { ok: false, message: '区域不存在' }
  }
  const car = CARS.filter(function (c) {
    return c.id === zone.car
  })[0]
  if (car && !car.online) {
    return { ok: false, message: zone.car + ' 离线，请检查车辆或改为降级方案' }
  }
  taskSeq += 1
  zone.status = 'running'
  zone.statusText = '进行中'
  zone.progress = 5
  zone.detail = '任务单已下发，等待车端回执'
  zone.duration = '刚刚'
  return { ok: true, seq: taskSeq, message: '已向 ' + zone.car + ' 下发「' + zone.name + '」任务单' }
}

export function cancelTask(zoneId) {
  const zone = ZONES.filter(function (z) {
    return z.id === zoneId
  })[0]
  if (!zone) {
    return { ok: false, message: '区域不存在' }
  }
  zone.status = 'idle'
  zone.statusText = '未开始'
  zone.progress = 0
  zone.detail = '任务已取消，等待重新派发'
  zone.duration = '—'
  return { ok: true, message: '已取消「' + zone.name + '」任务' }
}

/**
 * 一键取消本轮全部未完成任务（对应 U1P 按键的「一键取消」入口）。
 */
export function cancelAll() {
  let n = 0
  ZONES.forEach(function (z) {
    if (z.status === 'running' || z.status === 'blocked') {
      z.status = 'idle'
      z.statusText = '未开始'
      z.progress = 0
      z.detail = '任务已取消，等待重新派发'
      z.duration = '—'
      n += 1
    }
  })
  return { ok: true, message: n > 0 ? '已取消 ' + n + ' 个未完成任务' : '当前没有待取消的任务' }
}

/**
 * 标记任务完成（供在线模拟与真实状态回执使用）。
 * 真实接入时，这里就是「收到车端完成回执」的处理点。
 */
export function markDone(zoneId, detail) {
  const zone = ZONES.filter(function (z) {
    return z.id === zoneId
  })[0]
  if (!zone) {
    return { ok: false, message: '区域不存在' }
  }
  zone.status = 'done'
  zone.statusText = '已完成'
  zone.progress = 100
  zone.detail = detail || '路线执行完毕，未发现异常'
  return { ok: true, message: '「' + zone.name + '」已完成' }
}

export default {
  getZones: getZones,
  getCars: getCars,
  getRecords: getRecords,
  statusOf: statusOf,
  summarize: summarize,
  dispatchTask: dispatchTask,
  cancelTask: cancelTask,
  cancelAll: cancelAll,
  markDone: markDone
}
