/**
 * 页面：地图与路线（Map）
 *
 * 这一页是「在已建模好的地图上有一条预设好的固定路线」的界面落点：
 *   · 底图 = **车端真实 ROS 地图**（classroom.pgm，350×197 格）转出的矢量轮廓
 *   · 四条固定路线画在真实地图坐标系上（米）
 *   · 小车标记沿路线**逐段移动**，位置直接来自 store 里推进的状态
 *
 * 演示动效由宿主每 250 ms 推进一次 store 并重绘，本页只负责"把当前坐标画出来"。
 */
import store from '../common/store.js'
import CFG from '../common/data.js'
import map from '../common/map.js'

let toastText = ''

export const title = '地图与路线'

export function data(ctx) {
  const snap = store.snapshot()
  const pos = store.vehiclePositions()
  const svg = map.renderMap({
    zones: snap.zones,
    tasks: pos,
    width: 680,
    height: map.MAP_LAYOUT.height
  })

  const running = snap.zones.filter(function (z) { return z.status === 'running' }).length

  return {
    clock: ctx.clock,
    toast: toastText,
    svg: svg,
    mapName: CFG.MAP.name,
    gridInfo: CFG.MAP.width.toFixed(1) + ' × ' + CFG.MAP.height.toFixed(1) +
      ' m（' + CFG.MAP.resolution + ' m/格，原点 [' + CFG.MAP.origin.join(', ') + ']）',
    source: '底图来自车端当前生效地图 classroom.pgm 的矢量轮廓（自动生成，仅用于画图）',
    zones: snap.zones.map(function (z) {
      const p = pos[z.id]
      return {
        id: z.id,
        name: z.name,
        car: z.car,
        color: z.color,
        statusText: z.statusText,
        routeName: z.routeName,
        progress: p ? p.progress : 0,
        detail: p
          ? ('第 ' + (p.leg + 1) + ' / ' + (p.totalLegs + 1) + ' 个航点 · ' + z.detail)
          : '尚未派单',
        lengthM: z.lengthM
      }
    }),
    running: running,
    totalLen: CFG.allRouteLength().toFixed(1),
    gaps: CFG.MAP.gaps.length + ' 处外边界缺口（门洞/通道）'
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

  <div class="mapwrap">{{{svg}}}</div>

  <div class="row-between" style="margin-top:10px">
    <span class="small muted">{{mapName}}</span>
    <span class="small muted">{{gridInfo}}</span>
  </div>
  <div class="small muted" style="margin-top:2px">{{source}}</div>

  <div class="section-title">四条固定路线 · 总长 {{totalLen}} m · 进行中 {{running}} 区</div>
  {{each:zones}}
  <div class="card" style="padding:12px 16px">
    <div class="row-between">
      <div class="row">
        <div class="dot" style="background:{{$item.color}}"></div>
        <span class="lrow-title">{{$item.name}}</span>
        <span class="small muted" style="margin-left:10px">{{$item.car}} · {{$item.routeName}}（{{$item.lengthM}} m）</span>
      </div>
      <span style="color:{{$item.color}};font-size:20px;font-weight:700">{{$item.statusText}}</span>
    </div>
    <div class="lrow-sub" style="margin-top:6px">{{$item.detail}}</div>
    <div class="bar"><div class="bar-in" style="width:{{$item.progress}}%;background:{{$item.color}}"></div></div>
  </div>
  {{/each}}

  <div class="lrow-sub">
    {{gaps}}。「停止 / 急停」永远优先于任何行进动作；车端本地安全逻辑最高优先，本端不接管电机。
  </div>

  <div class="dock">
    <div class="btn btn-primary" data-act="startRound">开始本轮巡检</div>
    <div class="btn btn-danger" data-act="cancelAll">一键取消</div>
    <div class="btn" data-act="go" data-tid="Dispatch">调度台</div>
  </div>
</div>
{{if:toast}}<div class="toast">{{toast}}</div>{{/if}}
`

export const act = {
  back: function (ctx) { ctx.go('Home'); return false },
  go: function (ctx, tid) { ctx.go(tid); return false },
  startRound: function () {
    toastText = store.startRound().message
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

export default { title: title, tpl: tpl, data: data, act: act, onLeave: onLeave }
