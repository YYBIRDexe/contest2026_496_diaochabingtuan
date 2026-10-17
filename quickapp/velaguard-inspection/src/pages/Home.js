/**
 * 页面：桌面（Home）
 *
 * 手机式桌面：状态栏 → 本轮概览卡 → 六个应用磁贴 → 区域状态条 → 底部快捷坞。
 * 保留原「手机触控式程序」的形态，磁贴换成与本版功能对应的六个入口。
 */
import store from '../common/store.js'

export const title = 'VelaGuard 巡检桌面'

/** 应用注册表：加一个 app 只要在这里加一条 */
export const APPS = [
  { name: '巡检调度台', sub: '派单与状态', glyph: '调', page: 'Dispatch', color: '#2F6DF6' },
  { name: '地图与路线', sub: '固定路线', glyph: '图', page: 'Map', color: '#0EA5A4' },
  { name: '区域与任务', sub: '4 区 4 路线', glyph: '区', page: 'Zones', color: '#7C5CFF' },
  { name: '巡检记录', sub: '按轮次回看', glyph: '记', page: 'Records', color: '#F59E0B' },
  { name: '语音助手', sub: '端侧 AI 对话', glyph: '语', page: 'Voice', color: '#EC4899' },
  { name: '系统与链路', sub: '数据源与通道', glyph: '设', page: 'System', color: '#64748B' }
]

let toastText = ''

export function data(ctx) {
  const snap = store.snapshot()
  const s = snap.summary
  const online = snap.cars.filter(function (c) { return c.online }).length
  const battery = snap.cars.reduce(function (m, c) { return c.online && c.battery > m ? c.battery : m }, 0)
  const mem = store.memoryOfLastRound()

  let line
  if (s.round === 0) {
    line = '尚未开始巡检，点下方「开始本轮巡检」'
  } else if (s.needAction > 0) {
    line = s.total + ' 区中 ' + s.counts.done + ' 区已完成，' + s.counts.blocked +
      ' 区阻塞待处置，' + s.counts.offline + ' 区车辆离线'
  } else if (s.counts.running > 0) {
    line = '巡检进行中，已收回 ' + s.counts.done + ' 区结果'
  } else if (s.counts.done === s.total) {
    line = '四区全部完成，本轮无异常'
  } else {
    line = s.total + ' 区中 ' + s.counts.done + ' 区已完成'
  }

  return {
    clock: ctx.clock,
    toast: toastText,
    apps: APPS,
    tileStyle: function (a) { return 'background-color: ' + a.color },
    round: s.round,
    line: line,
    counts: s.counts,
    onlineText: online + ' / ' + snap.cars.length + ' 车在线',
    battery: battery,
    zoneChips: snap.zones,
    memory: mem ? mem.text : '',
    totalLen: (ctx.allRouteLength || 0).toFixed(1)
  }
}

export const tpl = `
<div class="screen">
  <div class="statusbar">
    <div class="sb-left">
      <span class="sb-time">{{clock}}</span>
      <span class="sb-title">{{title}}</span>
    </div>
    <div class="sb-right">
      <div class="chip" style="background:rgba(61,220,132,0.16)">
        <span style="color:#3ddc84">模拟器演示</span>
      </div>
      <span class="sb-battery">{{onlineText}} · 电池 {{battery}}%</span>
    </div>
  </div>

  <div class="hero">
    <div class="row-between">
      <span class="small muted">本轮巡检 · 第 {{round}} 轮</span>
      <span class="small muted">固定路线 {{totalLen}} m</span>
    </div>
    <div class="hero-main">{{line}}</div>
    <div class="stats">
      <div class="stat"><span class="stat-num" style="color:#3DDC84">{{counts.done}}</span><span class="stat-label">已完成</span></div>
      <div class="stat"><span class="stat-num" style="color:#4DA3FF">{{counts.running}}</span><span class="stat-label">进行中</span></div>
      <div class="stat"><span class="stat-num" style="color:#FF6B6B">{{counts.blocked}}</span><span class="stat-label">阻塞</span></div>
      <div class="stat"><span class="stat-num" style="color:#94A3B8">{{counts.pending}}</span><span class="stat-label">待执行</span></div>
      <div class="stat"><span class="stat-num" style="color:#FBBF24">{{counts.offline}}</span><span class="stat-label">离线</span></div>
    </div>
  </div>

  {{if:memory}}
  <div class="card" style="border-left:4px solid #f59e0b">
    <span class="small" style="color:#fbbf24">跨轮次提醒：{{memory}}</span>
  </div>
  {{/if}}

  <div class="section-title">全部应用</div>
  <div class="grid">
    {{each:apps}}
    <div class="tile" data-act="go" data-tid="{{$item.page}}">
      <div class="tile-icon" style="{{tileStyle($item)}}">{{$item.glyph}}</div>
      <div>
        <div class="tile-name">{{$item.name}}</div>
        <div class="tile-sub">{{$item.sub}}</div>
      </div>
    </div>
    {{/each}}
  </div>

  <div class="section-title">区域状态</div>
  <div class="grid">
    {{each:zoneChips}}
    <div class="lrow" style="width:330px;margin-right:16px">
      <div class="lrow-main">
        <div class="row">
          <div class="dot" style="background:{{$item.color}}"></div>
          <span class="lrow-title">{{$item.name}}</span>
        </div>
        <div class="lrow-sub">{{$item.detail}}</div>
      </div>
      <span style="color:{{$item.color}};font-size:20px;font-weight:700">{{$item.statusText}}</span>
    </div>
    {{/each}}
  </div>

  <div class="dock">
    <div class="btn btn-primary" data-act="startRound">开始本轮巡检</div>
    <div class="btn" data-act="closeRound">收轮归档</div>
    <div class="btn btn-danger" data-act="cancelAll">一键取消</div>
  </div>
</div>
{{if:toast}}<div class="toast">{{toast}}</div>{{/if}}
`

/**
 * 页面动作。返回 true 表示需要重绘。
 * 这些动作与 Skill（inspection.md）里给 Agent 的工具语义是一一对应的。
 *
 * ⚠️ `go` / `back` 这类**导航动作每个页面都必须定义**：
 * 外壳是按 data-act 查**当前页面**的 act 表来派发的，少写一个，
 * 那个按钮就是"点了没反应"。首页磁贴的跳转当初就是这么坏的，
 * 而且渲染测试完全看不出来（DOM 里 data-act 都在），
 * 只有**真实点击**才暴露——所以测试里补了点击用例。
 */
export const act = {
  go: function (ctx, tid) { ctx.go(tid); return false },
  back: function (ctx) { ctx.go('Home'); return false },
  startRound: function () {
    const r = store.startRound()
    const mem = store.memoryOfLastRound()
    toastText = r.message + (mem ? '；' + mem.text : '')
    return true
  },
  closeRound: function () {
    const r = store.closeRound()
    toastText = r.message
    return true
  },
  cancelAll: function () {
    toastText = store.cancelAll().message
    return true
  }
}

export function onLeave() {
  toastText = ''
}

export default { title: title, tpl: tpl, data: data, act: act, onLeave: onLeave, APPS: APPS }
