/**
 * 页面：区域与任务（Zones）
 *
 * 功能一「巡检区域与任务清单管理」的界面落点：
 * 把端侧预设表**摊开给人看**——每个区域、它绑定的固定路线、
 * 路线由哪些航点组成、每个航点在地图上的坐标、默认由哪台车执行。
 *
 * 这一页故意做成"只读 + 可派单"，改路线请改 src/common/data.js，
 * 改完跑 `node tools/gen-waypoints.js --check` 校验。
 */
import store from '../common/store.js'
import CFG from '../common/data.js'

let toastText = ''

export const title = '区域与任务'

export function data(ctx) {
  const snap = store.snapshot()
  const zones = CFG.ZONES.map(function (z) {
    const pts = CFG.routePoints(z.route)
    const st = snap.zones.filter(function (x) { return x.id === z.id })[0] || {}
    return {
      id: z.id,
      name: z.name,
      route: z.route,
      routeName: CFG.ROUTES[z.route].name,
      routeDesc: CFG.ROUTES[z.route].desc,
      car: z.car,
      statusText: st.statusText || '待执行',
      color: st.color || '#94A3B8',
      length: CFG.routeLength(z.route).toFixed(2),
      stops: pts.map(function (p) {
        return {
          id: p.id,
          name: p.name,
          x: p.x.toFixed(2),
          y: p.y.toFixed(2),
          dwell: p.dwell > 0 ? (p.dwell + ' s') : '过'
        }
      })
    }
  })

  return {
    clock: ctx.clock,
    toast: toastText,
    zones: zones,
    totalLen: CFG.allRouteLength().toFixed(2),
    limits: CFG.LIMITS
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

  <div class="card">
    <div class="lrow-title">端侧预设表（不依赖云端与数据库）</div>
    <div class="lrow-sub" style="margin-top:6px">
      四个区域 → 四条固定路线 → 四台车。整条巡检路线 {{totalLen}} m，
      单步上限 {{limits.step_distance_max_m}} m，单任务时限 {{limits.task_deadline_s}} s，
      失联判定 {{limits.receipt_timeout_s}} s。
    </div>
  </div>

  {{each:zones}}
  <div class="card">
    <div class="row-between">
      <div class="row">
        <div class="dot" style="background:{{$item.color}}"></div>
        <span class="lrow-title">{{$item.name}}</span>
        <span class="small muted" style="margin-left:10px">{{$item.car}} · {{$item.length}} m</span>
      </div>
      <span style="color:{{$item.color}};font-size:20px;font-weight:700">{{$item.statusText}}</span>
    </div>
    <div class="lrow-sub" style="margin-top:6px">{{$item.routeName}} · {{$item.routeDesc}}</div>
    <div class="row" style="margin-top:8px">
      <div class="btn btn-sm btn-primary" data-act="dispatch" data-tid="{{$item.id}}">派单</div>
      <div class="btn btn-sm" data-act="go" data-tid="Map">在地图上看</div>
    </div>
    <div style="margin-top:10px">
      {{each1:$item.stops}}
      <div class="kv">
        <span class="kv-k mono">{{$item.id}} · {{$item.name}}</span>
        <span class="kv-v mono">({{$item.x}}, {{$item.y}})  停留 {{$item.dwell}}</span>
      </div>
      {{/each1}}
    </div>
  </div>
  {{/each}}

  <div class="lrow-sub">
    路线是一串「航点编号 + 停留时间」的白名单，任务单里只带路线编号、不带参数，
    所以车端无法被诱导执行任意动作。改路线请改 src/common/data.js。
  </div>

  <div class="dock">
    <div class="btn btn-primary" data-act="startRound">开始本轮巡检</div>
    <div class="btn" data-act="go" data-tid="Map">看地图</div>
  </div>
</div>
{{if:toast}}<div class="toast">{{toast}}</div>{{/if}}
`

export const act = {
  back: function (ctx) { ctx.go('Home'); return false },
  go: function (ctx, tid) { ctx.go(tid); return false },
  dispatch: function (ctx, tid) {
    toastText = store.dispatch(tid).message
    return true
  },
  startRound: function () {
    toastText = store.startRound().message
    return true
  }
}

export function onLeave() {
  toastText = ''
}

export default { title: title, tpl: tpl, data: data, act: act, onLeave: onLeave }
