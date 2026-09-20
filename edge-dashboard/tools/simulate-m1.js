'use strict'

/**
 * 模拟 M1 侧的巡检数据源：周期性改写 data/state.json。
 *
 * 用途：在没有真机的情况下，端到端验证「外部数据 → 界面」这条链路。
 *
 *   终端 A：node tools/serve.js 8123
 *   终端 B：node tools/simulate-m1.js
 *   浏览器：http://127.0.0.1:8123/  然后点状态栏的数据源标签切到「M1 数据」
 *
 * 真机上把这份逻辑换成你的采集程序即可——只要写出的 JSON 字段一致，
 * 界面不需要任何改动。
 *
 * 用法：node tools/simulate-m1.js [写入间隔毫秒]
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..')
const DATA_DIR = path.join(ROOT, 'data')
const STATE_FILE = path.join(DATA_DIR, 'state.json')

const INTERVAL = Number(process.argv[2] || 3000)

const ZONES = [
  { id: 'Z1', name: '入口大厅', route: 'R-01', routeDesc: '前台 → 闸机 → 电梯口', car: 'CAR-1' },
  { id: 'Z2', name: '主通道', route: 'R-02', routeDesc: 'A 段 → B 段 → C 段', car: 'CAR-2' },
  { id: 'Z3', name: '展项区', route: 'R-03', routeDesc: '展台 1 → 展台 4 绕行', car: 'CAR-3' },
  { id: 'Z4', name: '设备区', route: 'R-04', routeDesc: '配电柜 → 机柜背面', car: 'CAR-4' }
]

const CARS = [
  { id: 'CAR-1', zone: '入口大厅', ip: '192.168.4.11', battery: 86 },
  { id: 'CAR-2', zone: '主通道', ip: '192.168.4.12', battery: 72 },
  { id: 'CAR-3', zone: '展项区', ip: '192.168.4.13', battery: 64 },
  { id: 'CAR-4', zone: '设备区', ip: '192.168.4.14', battery: 58 }
]

const BLOCK_REASONS = [
  '展台前有纸箱挡道，已停车待处置',
  '通道有临时推车占位，等待清理',
  '地面上有散落线缆，已停车'
]

const OK_REASONS = [
  '路线执行完毕，未发现异常',
  '地面无杂物，通行正常',
  '设备区无积水，柜门关闭正常'
]

// 每台车独立推进：未开始 → 进行中 → 已完成 / 阻塞
const runtime = ZONES.map(function () {
  return { status: 'idle', progress: 0, detail: '等待派单', round: 1 }
})

let round = 1
let step = 0

function buildState() {
  const zones = ZONES.map(function (z, i) {
    const r = runtime[i]
    return {
      id: z.id,
      name: z.name,
      route: z.route,
      routeDesc: z.routeDesc,
      car: z.car,
      status: r.status,
      progress: r.progress,
      detail: r.detail,
      duration: r.status === 'idle' ? '—' : r.progress + '% 用时约 ' + Math.max(1, Math.round(r.progress / 30)) + ' 分'
    }
  })

  const cars = CARS.map(function (c) {
    return {
      id: c.id,
      zone: c.zone,
      ip: c.ip,
      online: true,
      battery: c.battery
    }
  })

  return {
    round: round,
    generatedAt: new Date().toISOString(),
    zones: zones,
    cars: cars,
    records: [
      {
        round: '第 ' + round + ' 轮',
        time: '进行中',
        zones: zones.map(function (z) {
          return { name: z.name, result: z.status }
        }),
        summary: '模拟数据：已完成 ' + zones.filter(function (z) {
          return z.status === 'done'
        }).length + ' / ' + zones.length
      }
    ]
  }
}

function advance() {
  step += 1
  let anyActive = false

  runtime.forEach(function (r, i) {
    if (r.status === 'idle' && step % 4 === (i % 4)) {
      r.status = 'running'
      r.progress = 5
      r.detail = '任务单已下发，车端开始执行'
      anyActive = true
      return
    }
    if (r.status === 'running') {
      r.progress = Math.min(100, r.progress + 20 + Math.floor(Math.random() * 15))
      if (r.progress >= 100) {
        // 约 1/4 概率遇到阻塞，其余正常完成
        if (Math.random() < 0.25) {
          r.status = 'blocked'
          r.progress = 30 + Math.floor(Math.random() * 40)
          r.detail = BLOCK_REASONS[Math.floor(Math.random() * BLOCK_REASONS.length)]
        } else {
          r.status = 'done'
          r.progress = 100
          r.detail = OK_REASONS[Math.floor(Math.random() * OK_REASONS.length)]
        }
      } else {
        r.detail = '正在执行，已完成 ' + r.progress + '%'
        anyActive = true
      }
    }
  })

  // 一轮跑完（没有 idle/running 了）就开新一轮
  const busy = runtime.some(function (r) {
    return r.status === 'idle' || r.status === 'running'
  })
  if (!busy) {
    round += 1
    runtime.forEach(function (r) {
      r.status = 'idle'
      r.progress = 0
      r.detail = '等待派单'
    })
    console.log('—— 新一轮巡检开始（第 ' + round + ' 轮）——')
  } else if (!anyActive) {
    // 全被阻塞时，下一轮自动重派，避免卡死
    runtime.forEach(function (r) {
      if (r.status === 'blocked') {
        r.status = 'idle'
        r.progress = 0
        r.detail = '阻塞任务已撤下，等待重派'
      }
    })
  }
}

function write() {
  advance()
  const state = buildState()
  fs.mkdirSync(DATA_DIR, { recursive: true })
  // 先写临时文件再改名，避免界面读到半截 JSON
  const tmp = STATE_FILE + '.tmp'
  fs.writeFileSync(tmp, JSON.stringify(state, null, 2), 'utf8')
  fs.renameSync(tmp, STATE_FILE)

  const summary = state.zones.map(function (z) {
    return z.name + ':' + z.status
  }).join('  ')
  console.log('[' + new Date().toLocaleTimeString() + '] ' + summary)
}

console.log('模拟 M1 数据源')
console.log('  写入：' + STATE_FILE)
console.log('  间隔：' + INTERVAL + 'ms')
console.log('  停止：Ctrl+C')
console.log('')
console.log('配套使用：node tools/serve.js 8123，然后浏览器打开 http://127.0.0.1:8123/')
console.log('')

write()
setInterval(write, INTERVAL)

process.on('SIGINT', function () {
  console.log('\n已停止模拟。data/state.json 保留最后一次状态，界面仍可读取。')
  process.exit(0)
})
