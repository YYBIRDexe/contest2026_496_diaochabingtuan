/**
 * 页面：语音助手（Voice）
 *
 * 模拟器**没有麦克风**，所以这一页做成**文本对话**——比假装有语音更诚实，
 * 而且 Skill 与工具调用的能力一样能演示到。
 *
 * 两条作答路径（自动选，界面上标出来）：
 *   1. 端侧 Agent：`@system.velaclaw.ask()` → openvela 上的 ai_agent →
 *      按 Skill（inspection.md）理解并调用它自己的工具。
 *      返回里还带 `tool_calls`，所以界面能显示「它调了哪个工具」。
 *   2. 本地指令表：Agent 不可用（没编译进固件／没配 LLM／浏览器预览）时兜底，
 *      巡检控制类问句直接查 store，离线也能答，演示不会卡住。
 */
import store from '../common/store.js'
import agent from '../common/agent.js'

let input = ''
let lastCount = -1

export const title = '语音助手'

export function data(ctx) {
  const msgs = agent.messages()
  const st = agent.status()
  const pendingNow = agent.isPending()

  /* 有新消息时给一个"自动滚到底"的标记，宿主据此把聊天区滚到底 */
  if (msgs.length !== lastCount) {
    lastCount = msgs.length
    ctx.scrollChat = true
  }

  return {
    clock: ctx.clock,
    toast: '',
    msgs: msgs.map(function (m) {
      return {
        id: m.id,
        role: m.role,
        text: m.text,
        toolText: m.toolText,
        sourceText: m.source === 'agent'
          ? '端侧 Agent'
          : (m.source === 'local' ? '本地指令' : ''),
        isMe: m.role === 'me'
      }
    }),
    input: input,
    pending: pendingNow,
    presets: agent.presets(),
    statusText: st.text,
    statusHint: st.hint,
    /* 颜色在 data() 里算好，别把 {{if}} 写进用引号包的 CSS 属性里——
       那样模板解析会错位（写错过一次）。 */
    statusColor: st.ready === true ? '#3ddc84' : '#fbbf24',
    ready: st.ready === true,
    notReady: st.ready === false
  }
}

export const tpl = `
<div class="screen">
  <div class="statusbar">
    <div class="sb-left">
      <span class="sb-time">{{clock}}</span>
      <span class="sb-title">{{title}}</span>
    </div>
    <div class="sb-right"><div class="btn btn-sm btn-ghost" data-act="back">返回</div></div>
  </div>

  <div class="card" style="padding:10px 16px">
    <div class="row-between">
      <span class="small" style="color:{{statusColor}}">{{statusText}}</span>
      <div class="btn btn-sm btn-ghost" data-act="clear">清空</div>
    </div>
    <div class="lrow-sub" style="margin-top:4px">{{statusHint}}</div>
  </div>

  <div class="chat" id="chatbox" data-chat="1">
    {{if:msgs.length}}
    {{each:msgs}}
    <div class="msg {{if1:$item.isMe}}msg-me{{/if1}}">
      <div class="bubble {{if1:$item.isMe}}bubble-me{{else}}bubble-agent{{/if1}}">
        <span>{{$item.text}}</span>
        {{if1:$item.toolText}}<div class="tools">🔧 {{$item.toolText}}</div>{{/if1}}
        {{if1:$item.sourceText}}<div class="tools" style="color:#7d8ea8">来源：{{$item.sourceText}}</div>{{/if1}}
      </div>
    </div>
    {{/each}}
    {{else}}
    <div class="empty">
      说点什么吧。点下面的预设问句可以直接演示六条能力，<br>
      也可以输入「开始巡检」「现在哪些区域没查完」「生成本轮巡检汇总」。
    </div>
    {{/if}}
    {{if:pending}}<div class="msg"><div class="bubble bubble-sys">正在等端侧 Agent 回复…</div></div>{{/if}}
  </div>

  <div class="inputbar">
    <input class="input" id="chatinput" data-input="1" placeholder="输入指令或问题…" value="{{input}}">
    <div class="btn btn-primary" data-act="send" style="margin-left:12px;margin-right:0">发送</div>
  </div>

  <div class="presets">
    {{each:presets}}
    <div class="preset" data-act="ask" data-tid="{{$item.q}}">{{$item.label}}</div>
    {{/each}}
  </div>

  <div class="lrow-sub">
    唤醒词链路（Hello, openvela）在边缘层 M1 上，模拟器无麦克风，
    因此这一版用文本入口代替；两者最终都走同一套 Skill 与工具。
  </div>
</div>
`

export const act = {
  back: function (ctx) { ctx.go('Home'); return false },
  clear: function () {
    agent.reset()
    input = ''
    lastCount = -1
    return true
  },
  send: function (ctx) {
    const text = input
    input = ''
    submit(ctx, text)
    return true
  },
  ask: function (ctx, tid) {
    submit(ctx, tid)
    return true
  }
}

/** 发送一句并等回复；回复到达后重绘 */
function submit(ctx, text) {
  const q = String(text || '').trim()
  if (!q) {
    return
  }
  /* 先把"我的话"画上去，再等回复——避免看起来像没反应 */
  agent.ask(q).then(function () {
    ctx.render()
  })
  ctx.render()
}

/** 宿主在每次重绘后调用：接住输入框的实时输入，并把聊天区滚到底 */
export function afterRender(doc) {
  if (!doc || !doc.getElementById) {
    return
  }
  const el = doc.getElementById('chatinput')
  if (el && !el.__bound) {
    el.__bound = true
    el.addEventListener('input', function () {
      input = el.value
    })
    el.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        const text = input
        input = ''
        el.value = ''
        agent.ask(text).then(function () {
          if (boundRender) {
            boundRender()
          }
        })
        if (boundRender) {
          boundRender()
        }
      }
    })
  }
  const box = doc.getElementById('chatbox')
  if (box) {
    box.scrollTop = box.scrollHeight
  }
}

/**
 * 宿主注入的"请求重绘"函数。
 * 输入框的回车处理发生在宿主的事件循环之外，需要它把重绘接回去。
 */
let boundRender = null

export function setRender(fn) {
  boundRender = fn
}

export function onLeave() {
  /* 不清理历史：回到这一页还能看到刚才的对话 */
}

export default {
  title: title,
  tpl: tpl,
  data: data,
  act: act,
  afterRender: afterRender,
  onLeave: onLeave
}
