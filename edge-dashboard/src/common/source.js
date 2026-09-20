/**
 * VelaGuard 数据源适配层
 *
 * 目的：把「界面」与「数据从哪来」彻底解耦。
 *
 * 界面只认一种东西——**状态快照（snapshot）**：
 *
 *   {
 *     zones:     [...],   // 区域列表，字段见 store.js 的 ZONES
 *     cars:      [...],   // 车辆列表
 *     records:   [...],   // 历史轮次
 *     summary:   {...},   // 汇总计数 { total, counts, doneText, needAction }
 *     source:    'demo' | 'file' | 'sim',
 *     sourceText:'演示数据' 等中文说明
 *     connected: true/false,
 *     lastUpdate: Date,
 *     lastUpdateText: '刚刚' / 'HH:MM:SS'
 *   }
 *
 * 三种实现（可通过 URL 参数或界面切换，见 control）：
 *
 *   1. demo —— 用 store.js 的端侧预设表演示，派单/取消直接改内存。
 *              完全离线可用，是不接车也能演示的兜底模式。
 *
 *   2. file —— 轮询读取 data/state.json，作为真实数据的接入点。
 *              把 M1 上的采集程序写到这个文件，界面就会跟着变。
 *              （M1 是 Linux，最省事的落地方式）
 *              另外还支持 data/command.json 下发指令（单向的文件桥）。
 *
 *   3. sim  —— 在线模拟：按脚本自动推进任务状态（派单→进行中→完成/阻塞），
 *              用来验证「界面是否真的会跟着数据变」，不作为交付模式。
 *
 * 接真机时只需新增/替换一个 adapter；界面代码一行不用改。
 */

/* ================================================================== *
 * 1. 演示数据源：包在 store 外面，接口与其它数据源一致
 * ================================================================== */
function createDemoAdapter() {
  return {
    name: 'demo',
    sourceText: '演示数据',
    available: true,
    unavailableReason: '',
    async start() {},
    stop() {},

    get() {
      return {
        zones: store.getZones(),
        cars: store.getCars(),
        records: store.getRecords(),
        summary: store.summarize(),
        source: 'demo',
        sourceText: '演示数据',
        connected: true,
        lastUpdate: new Date(),
        lastUpdateText: '本地'
      }
    },

    dispatch(zoneId) {
      return store.dispatchTask(zoneId)
    },
    cancel(zoneId) {
      return store.cancelTask(zoneId)
    },
    cancelAll() {
      return store.cancelAll()
    }
  }
}

/* ================================================================== *
 * 2. 文件数据源：轮询 state.json 读取真实状态，通过 HTTP 接口下发指令
 *
 * 这是接 M1 真实数据的推荐入口：M1 侧只需要定期把巡检状态写成 JSON。
 *
 * 注意两点（都踩过）：
 *   a) URL 用绝对路径 '/data/state.json'。
 *      用相对路径 'data/state.json' 会以「当前页面」为基准解析成
 *      /preview/data/state.json，直接 404。
 *   b) 必须经 HTTP 提供，不能放在 file:// 下。
 *      浏览器禁止 file:// 页面发起 fetch（跨源限制），
 *      所以 file:// 打开时该数据源不可用，会自动回退到演示数据。
 *      正式部署请用 `node tools/serve.js` 或 M1 上的本地 Web 服务。
 * ================================================================== */
function createFileAdapter(options) {
  const opts = options || {}
  const stateUrl = opts.stateUrl || '/data/state.json'
  const commandUrl = opts.commandUrl || '/api/command'
  /*
   * 轮询间隔：**5 秒**（用户要求「每 5s 根据检测的参数更新一次页面数据」）。
   * 设备侧由 linux/car_state.py 每 5 秒真去探测四台车（在线/电量）并写
   * state.json，两边节奏对齐，页面上看到的永远是最近 5 秒内的实测值。
   */
  const period = opts.period || 5000

  let timer = null
  let last = null
  let listener = null

  /** file:// 下 fetch 会被浏览器拒绝，提前判定，避免无意义的报错刷屏 */
  function usable() {
    return String(location.protocol).indexOf('http') === 0
  }

  function unavailableReason() {
    return 'file:// 下无法读取数据接口，请用 http 方式打开（node tools/serve.js）'
  }

  /** 把外部 JSON 规整成状态快照，缺字段时用演示数据兜底，避免界面崩掉 */
  function normalize(raw) {
    if (!raw || !raw.zones) {
      return null
    }
    const zones = raw.zones.map(function (z) {
      return {
        id: z.id,
        name: z.name,
        route: z.route || '—',
        routeDesc: z.routeDesc || '—',
        car: z.car || '—',
        status: z.status || 'idle',
        statusText: z.statusText || store.statusOf(z.status || 'idle').text,
        progress: typeof z.progress === 'number' ? z.progress : 0,
        detail: z.detail || '',
        duration: z.duration || '—'
      }
    })
    const cars = (raw.cars || []).map(function (c) {
      return {
        id: c.id,
        zoneId: c.zoneId || '',
        zone: c.zone || '—',
        ip: c.ip || '—',
        online: !!c.online,
        battery: typeof c.battery === 'number' ? c.battery : 0,
        link: c.online ? '良好' : '离线'
      }
    })
    const counts = { done: 0, running: 0, blocked: 0, idle: 0, offline: 0 }
    zones.forEach(function (z) {
      const offlineCar = cars.filter(function (c) {
        return c.id === z.car && !c.online
      })[0]
      if (offlineCar) {
        counts.offline += 1
      } else if (counts[z.status] !== undefined) {
        counts[z.status] += 1
      }
    })
    return {
      zones: zones,
      cars: cars,
      records: raw.records || store.getRecords(),
      summary: {
        total: zones.length,
        counts: counts,
        doneText: counts.done + ' / ' + zones.length,
        needAction: counts.blocked + counts.offline
      },
      source: 'file',
      sourceText: 'M1 数据',
      connected: true,
      lastUpdate: new Date(),
      lastUpdateText: '刚刚'
    }
  }

  async function poll() {
    if (!usable()) {
      if (last) {
        last.connected = false
        last.lastUpdateText = 'file:// 不可用'
      }
      return
    }
    try {
      const res = await fetch(stateUrl + '?t=' + Date.now(), { cache: 'no-store' })
      if (!res.ok) {
        throw new Error('HTTP ' + res.status)
      }
      const snap = normalize(await res.json())
      if (snap) {
        last = snap
        if (listener) {
          listener(snap)
        }
      }
    } catch (e) {
      // 文件不存在或读不到：标记断连，但不抛错、不清空已有数据
      if (last) {
        last.connected = false
        last.lastUpdateText = '连接断开'
      }
    }
  }

  return {
    name: 'file',
    sourceText: 'M1 数据',
    start() {
      poll()
      timer = setInterval(poll, period)
    },
    stop() {
      if (timer) {
        clearInterval(timer)
        timer = null
      }
    },
    get() {
      return last
    },
    /** 该数据源在当前环境下是否可用（供界面给出准确提示） */
    get available() {
      return usable()
    },
    get unavailableReason() {
      return usable() ? '' : unavailableReason()
    },
    onUpdate(fn) {
      listener = fn
    },

    /**
     * 下发指令：写一个命令文件。
     * 注意——单靠 file:// 页面无法写文件（浏览器沙箱限制），
     * 正式使用时把 commandUrl 指向一个本地 HTTP 接口即可。
     */
    async dispatch(zoneId) {
      return await sendCommand({ action: 'dispatch', zoneId: zoneId, at: Date.now() })
    },
    async cancel(zoneId) {
      return await sendCommand({ action: 'cancel', zoneId: zoneId, at: Date.now() })
    },
    async cancelAll() {
      return await sendCommand({ action: 'cancelAll', at: Date.now() })
    }
  }

  async function sendCommand(payload) {
    try {
      const res = await fetch(commandUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!res.ok) {
        throw new Error('HTTP ' + res.status)
      }
      return { ok: true, message: '指令已下发' }
    } catch (e) {
      return {
        ok: false,
        message: '指令通道未接通（需要本地 HTTP 接口，file:// 下无法写文件）'
      }
    }
  }
}

/* ================================================================== *
 * 3. 在线模拟数据源：按脚本推进状态，验证「数据变→界面变」
 * ================================================================== */
function createSimAdapter(options) {
  const opts = options || {}
  const period = opts.period || 4000
  let timer = null
  let listener = null
  let step = 0

  /** 推进一步：让进行中的任务前进到完成，或把未开始的派出去 */
  function tick() {
    const zones = store.getZones()
    let changed = false

    zones.forEach(function (z) {
      if (z.status === 'running') {
        z.progress = Math.min(100, z.progress + 17)
        changed = true
        if (z.progress >= 100) {
          store.markDone(z.id)
        }
      } else if (z.status === 'idle' && step % 3 === 0) {
        store.dispatchTask(z.id)
        changed = true
      } else if (z.status === 'blocked' && step % 4 === 3) {
        store.cancelTask(z.id)
        changed = true
      }
    })

    step += 1
    // 注意：不能在回调里用 this，必须走闭包里的 self
    if (changed && listener) {
      listener(self.get())
    }
  }

  const self = {
    name: 'sim',
    sourceText: '在线模拟',
    available: true,
    unavailableReason: '',
    start() {
      step = 0
      timer = setInterval(tick, period)
    },
    stop() {
      if (timer) {
        clearInterval(timer)
        timer = null
      }
    },
    get() {
      return {
        zones: store.getZones(),
        cars: store.getCars(),
        records: store.getRecords(),
        summary: store.summarize(),
        source: 'sim',
        sourceText: '在线模拟',
        connected: true,
        lastUpdate: new Date(),
        lastUpdateText: '刚刚'
      }
    },
    onUpdate(fn) {
      listener = fn
    },
    dispatch(zoneId) {
      return store.dispatchTask(zoneId)
    },
    cancel(zoneId) {
      return store.cancelTask(zoneId)
    },
    cancelAll() {
      return store.cancelAll()
    }
  }
  return self
}

/* ================================================================== *
 * 4. 统一入口：负责选择数据源、暴露订阅、并提供模式切换
 * ================================================================== */
function createSource(initialMode) {
  const adapters = {
    demo: createDemoAdapter(),
    file: createFileAdapter({}),
    sim: createSimAdapter({})
  }

  let current = null
  let listener = null

  function attach(name) {
    if (current) {
      // 必须先停掉旧适配器，否则它的轮询定时器会在后台一直跑，
      // 频繁切源会不断累积定时器（隐性资源泄漏）。
      if (current.stop) {
        current.stop()
      }
      if (current.onUpdate) {
        current.onUpdate(null)
      }
    }
    current = adapters[name] || adapters.demo
    if (current.onUpdate) {
      current.onUpdate(function (snap) {
        if (listener) {
          listener(snap)
        }
      })
    }
    if (current.start) {
      current.start()
    }
    return current
  }

  const source = {
    get name() {
      return current ? current.name : 'demo'
    },

    /** 当前状态快照，可能为 null（file 模式首次还没读到） */
    get() {
      return current ? current.get() : null
    },

    /** 订阅数据变化；返回取消订阅函数 */
    onUpdate(fn) {
      listener = fn
      return function () {
        listener = null
      }
    },

    /** 切换数据源 */
    setMode(name) {
      attach(name)
      if (listener) {
        listener(source.get())
      }
      return source.name
    },

    /** 当前数据源在该环境下是否可用（file:// 下 file 源不可用） */
    get available() {
      return current ? current.available !== false : true
    },
    get unavailableReason() {
      return current && current.unavailableReason ? current.unavailableReason : ''
    },

    /* --- 业务操作：委托给当前数据源，界面不需要知道用的是哪种 --- */
    async dispatch(zoneId) {
      return await current.dispatch(zoneId)
    },
    async cancel(zoneId) {
      return await current.cancel(zoneId)
    },
    async cancelAll() {
      return await current.cancelAll()
    }
  }

  attach(initialMode || 'demo')
  return source
}
