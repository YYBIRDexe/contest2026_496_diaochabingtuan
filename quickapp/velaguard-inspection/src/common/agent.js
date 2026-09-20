/**
 * VelaGuard · 语音助手（快应用 ↔ 端侧 ai_agent）
 *
 * 通道结论（都来自竞赛分支源码，不是照文档抄的）：
 *   · 快应用要跟端侧 Agent 说话，**唯一**官方通道是 `@system.velaclaw.ask()`
 *     —— IDL：`promise<AskResponse> ask(AskParam)`
 *        AskResponse = { reply, extra_info, tool_calls: [{name, result}] }
 *     传输是 POSIX 消息队列（/velaclaw_qapp_in、/velaclaw_qapp_out），
 *     **不是** WebSocket 28789（快应用侧根本没有 @system.websocket 模块）。
 *   · 快应用**不能**让 Agent 去调任意工具：桥里的
 *     `velaclaw_quickapp_bridge_call_tool()` 是个返回 not_implemented 的桩。
 *     所以「查车/派单」这类动作要靠 Agent 自己按 Skill 去调它的工具，
 *     本页只负责把问题送进去、把回复和**它调了哪些工具**显示出来。
 *
 * 模拟器没有麦克风，所以这一页是**文本对话**：输入框 + 预设问句按钮。
 * 这比假装有语音更诚实，也不影响 Skill 与工具调用能力的演示。
 *
 * 本地兜底：Agent 不可用（没编译进固件 / 没配 LLM / 预览环境）时，
 * 巡检控制类问句走**本地指令表**直接查 store —— 离线也能答，
 * 演示不会因为网络或额度失效而卡住。
 */
import store from './store.js'
import CFG from './data.js'

const HISTORY_MAX = 60

let history = []
let pending = false
let agentReady = null   // null=未探测 / true=可用 / false=不可用
let lastError = ''
let seq = 0

/* ------------------------------------------------------------------ *
 * 本地指令表（兜底用；与巡检四个功能一一对应）
 * ------------------------------------------------------------------ */
const LOCAL_RULES = [
  {
    name: '开始巡检',
    keywords: ['开始巡检', '开始本轮', '巡检一下', '检查一下', '开始检查'],
    run: function () {
      const meta = store.memoryOfLastRound()
      const r = store.startRound()
      let text = r.message + '。'
      /* 上下文主动：本轮开始前主动提醒上轮未完成的区域 */
      if (meta) {
        text += '提醒：' + meta.text
      }
      return text
    }
  },
  {
    name: '查询进度',
    keywords: ['哪些区域', '没查完', '进度', '查到哪', '巡检状态'],
    run: function () {
      const zs = store.zoneStates()
      const parts = zs.map(function (z) { return z.name + z.statusText })
      return '当前：' + parts.join('、') + '。'
    }
  },
  {
    name: '生成汇总',
    keywords: ['汇总', '报告', '小结', '总结', '覆盖'],
    run: function () {
      const r = store.closeRound()
      return r.message
    }
  },
  {
    name: '为什么阻塞',
    keywords: ['为什么', '阻塞', '卡住', '异常'],
    run: function () {
      const zs = store.zoneStates()
      const bad = zs.filter(function (z) {
        return z.status === 'blocked' || z.status === 'offline'
      })
      if (bad.length === 0) {
        return '本轮没有阻塞或离线的区域。'
      }
      return bad.map(function (z) {
        return z.name + '：' + z.detail
      }).join('；') + '。'
    }
  },
  {
    name: '一键取消',
    keywords: ['取消', '停下', '停止', '别查了'],
    run: function () {
      return store.cancelAll().message
    }
  },
  {
    name: '车队状态',
    keywords: ['在线', '几台车', '车状态', '电池', '电量'],
    run: function () {
      const snap = store.snapshot()
      const on = snap.cars.filter(function (c) { return c.online })
      const off = snap.cars.filter(function (c) { return !c.online })
      let text = on.length + ' / ' + snap.cars.length + ' 台车在线'
      if (on.length) {
        text += '（' + on.map(function (c) { return c.name + ' 电量 ' + c.battery + '%' }).join('，') + '）'
      }
      if (off.length) {
        text += '；' + off.map(function (c) { return c.name }).join('、') + ' 离线'
      }
      return text + '。'
    }
  },
  {
    name: '路线说明',
    keywords: ['路线', '怎么走', '地图', '航点'],
    run: function () {
      const parts = CFG.ALL_ROUTE.map(function (rid) {
        const r = CFG.ROUTES[rid]
        return r.name + '（' + CFG.routeLength(rid).toFixed(1) + ' 米，' + r.desc + '）'
      })
      return '本轮固定路线共 ' + CFG.allRouteLength().toFixed(1) + ' 米：' + parts.join('；') + '。'
    }
  }
]

function tryLocal(q) {
  const s = String(q || '')
  for (let i = 0; i < LOCAL_RULES.length; i += 1) {
    const rule = LOCAL_RULES[i]
    for (let k = 0; k < rule.keywords.length; k += 1) {
      if (s.indexOf(rule.keywords[k]) >= 0) {
        return { matched: rule.name, text: rule.run() }
      }
    }
  }
  return null
}

/* ------------------------------------------------------------------ *
 * 消息记录
 * ------------------------------------------------------------------ */
function push(role, text, extra) {
  seq += 1
  history.push({
    id: seq,
    role: role,          // 'me' | 'agent' | 'sys'
    text: text,
    tools: (extra && extra.tools) || [],
    source: (extra && extra.source) || '',
    time: (extra && extra.time) || ''
  })
  if (history.length > HISTORY_MAX) {
    history.shift()
  }
  return history[history.length - 1]
}

export function messages() {
  return history.map(function (m) {
    return {
      id: m.id,
      role: m.role,
      text: m.text,
      tools: m.tools.slice(),
      toolText: m.tools.length ? ('调用了 ' + m.tools.join('、')) : '',
      source: m.source,
      time: m.time
    }
  })
}

export function isPending() {
  return pending
}

export function status() {
  if (agentReady === true) {
    return { ready: true, text: '端侧 Agent 已连接', hint: '由 openvela 的 ai_agent 作答，并展示它调用的工具' }
  }
  if (agentReady === false) {
    return { ready: false, text: '本地指令模式', hint: lastError || '端侧 Agent 不可用，巡检控制类问句由本地指令表作答' }
  }
  return { ready: null, text: '正在探测端侧 Agent…', hint: '首次发送时会确认通道是否可用' }
}

export function reset(newHistory) {
  history = newHistory || []
  seq = history.length
  pending = false
  agentReady = null
  lastError = ''
}

/* ------------------------------------------------------------------ *
 * 与端侧 Agent 通信
 *
 * askSender 由宿主注入：它内部使用 `@system.velaclaw` 并调用 ask()。
 * 这样 common/ 下不需要出现 @system.* 导入，浏览器预览与单测都能直接加载本文件。
 * ------------------------------------------------------------------ */
let askSender = null

export function setAskSender(fn) {
  askSender = fn
}

/**
 * 发送一句问话。
 * 返回 Promise<{ok, text, tools, source}>
 *   source: 'agent' 表示端侧 Agent 作答；'local' 表示本地指令表作答
 */
export async function ask(text) {
  const q = String(text || '').trim()
  if (!q) {
    return { ok: false, text: '请先输入内容' }
  }
  if (pending) {
    return { ok: false, text: '上一条还在处理中' }
  }

  pending = true
  push('me', q)

  /* 1) 有端侧通道就优先用端侧 Agent（这样 Skill / 工具调用才真的被演示到） */
  if (askSender && agentReady !== false) {
    try {
      const res = await askSender(q)
      agentReady = true
      lastError = ''
      const reply = (res && res.reply) || ''
      const tools = ((res && res.tool_calls) || []).map(function (t) {
        return t && t.name ? t.name : '未知工具'
      })
      pending = false
      const msg = push('agent', reply || '（端侧 Agent 没有返回内容）', {
        tools: tools,
        source: 'agent'
      })
      return { ok: true, text: msg.text, tools: tools, source: 'agent' }
    } catch (e) {
      agentReady = false
      lastError = '端侧通道不可用：' + (e && e.message ? e.message : String(e))
    }
  }

  /* 2) 兜底：本地指令表 */
  const local = tryLocal(q)
  pending = false
  if (local) {
    const msg = push('agent', local.text, { source: 'local' })
    return { ok: true, text: msg.text, tools: [], source: 'local', matched: local.matched }
  }

  const msg = push('agent',
    '这句话我理解不了。可以说「开始巡检」「现在哪些区域没查完」「生成汇总」，' +
    '或者「2 号车前进」这类指令。（认不出就不下发，这是设计目标，不是失败）',
    { source: 'local' })
  return { ok: true, text: msg.text, tools: [], source: 'local', matched: null }
}

/** 预设问句：直接对应 Skill 的 When to use，点一下就演示一条能力 */
export function presets() {
  return [
    { label: '开始巡检', q: '开始本轮巡检' },
    { label: '没查完的', q: '现在哪些区域没查完' },
    { label: '查车队', q: '现在四台车都在线吗，电量多少' },
    { label: '查路线', q: '本轮固定路线是怎么走的' },
    { label: '生成汇总', q: '生成本轮巡检汇总' },
    { label: '一键取消', q: '取消本轮全部未完成任务' }
  ]
}

export default {
  ask: ask,
  messages: messages,
  isPending: isPending,
  status: status,
  reset: reset,
  setAskSender: setAskSender,
  presets: presets,
  tryLocal: tryLocal
}
