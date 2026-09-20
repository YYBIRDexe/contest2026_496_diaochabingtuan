/**
 * 页面：巡检调度台（Dispatch）
 *
 * 功能二「任务派单与结果回收」的界面落点：
 *   · 车辆卡：在线 / 电量 / 当前任务
 *   · 任务清单：任务序号、目标区域、路线、五种状态、进度
 *   · 每个任务可 开始 / 取消 / 改派 / 顺延（功能三的人工处置）
 *   · 车辆卡可一键切换在线/离线，用来演示「离线车不得被派单」
 *   · 底部可注入故障，用来演示「事件主动告警」与「阈值主动判失联」
 */
import store from '../common/store.js'
import CFG from '../common/data.js'

let toastText = ''

export const title = '巡检调度台'

export function data(ctx) {
  const snap = store.snapshot()
  const zoneList = snap.zones.map(function (z) {
    return {
      id: z.id,
      name: z.name,
      route: z.route,
      routeName: z.routeName,
      routeDesc: z.routeDesc,
      /* 注意区分两个字段：
       *   car     = 区域登记表里绑定的那台车
       *   taskCar = 本区域**当前任务实际派给**的车（改派后会不同）
       * 界面上"任务由谁执行"要用 taskCar，用 car 会出现
       * "改派成功了但界面还写着原车"的假象（测试抓到过）。 */
      car: z.car,
      taskCar: z.taskCar,
      carName: z.carName,
      taskCarName: z.taskCarName,
      status: z.status,
      statusText: z.statusText,
      color: z.color,
      detail: z.detail,
      progress: z.progress,
      taskId: z.taskId || '—',
      lengthM: z.lengthM,
      canStart: z.status === 'pending',
      canCancel: z.status === 'running' || z.status === 'pending' || z.status === 'blocked',
      canReassign: z.status === 'blocked' || z.status === 'offline',
      canPostpone: z.status === 'blocked' || z.status === 'offline'
    }
  })
  const cars = snap.cars.map(function (c) {
    const busy = zoneList.filter(function (z) {
      return z.car === c.id && (z.status === 'running' || z.status === 'pending')
    })[0]
    return {
      id: c.id,
      name: c.name,
      ip: c.ip,
      online: c.online,
      battery: c.battery,
      statusText: c.online ? (busy ? busy.statusText + '：' + busy.name : '空闲') : '离线',
      color: c.online ? (busy ? busy.color : '#3DDC84') : '#FBBF24',
      toggleText: c.online ? '置离线' : '置在线'
    }
  })

  return {
    clock: ctx.clock,
    toast: toastText,
    zones: zoneList,
    cars: cars,
    round: snap.round,
    total: snap.summary.total,
    timeout: CFG.LIMITS.receipt_timeout_s
  }
}

export const tpl = `
<div class="screen">
  <div class="statusbar">
    <div class="sb-left">
      <span class="sb-time">{{clock}}</span>
      <span class="sb-title">{{title}} · 第 {{round}} 轮</span>
    </div>
    <div class="sb-right"><div class="btn btn-sm btn-ghost" data-act="back">返回</div></div>
  </div>

  <div class="section-title">车队（{{total}} 区 / 4 车）</div>
  {{each:cars}}
  <div class="lrow">
    <div class="lrow-main">
      <div class="row">
        <div class="dot" style="background:{{$item.color}}"></div>
        <span class="lrow-title">{{$item.name}}</span>
        <span class="small muted" style="margin-left:10px">{{$item.ip}}</span>
      </div>
      <div class="lrow-sub">{{$item.statusText}}{{if1:$item.online}} · 电量 {{$item.battery}}%{{/if1}}</div>
    </div>
    <div class="btn btn-sm btn-ghost" data-act="toggleCar" data-tid="{{$item.id}}">{{$item.toggleText}}</div>
  </div>
  {{/each}}

  <div class="section-title">任务清单</div>
  {{each:zones}}
  <div class="card">
    <div class="row-between">
      <div class="row">
        <div class="dot" style="background:{{$item.color}}"></div>
        <span class="lrow-title">{{$item.name}}</span>
        <span class="small muted" style="margin-left:10px">{{$item.taskId}}</span>
      </div>
      <span style="color:{{$item.color}};font-size:20px;font-weight:700">{{$item.statusText}}</span>
    </div>
    <div class="lrow-sub" style="margin-top:8px">
      {{$item.taskCarName}} · {{$item.routeName}}（{{$item.lengthM}} m）· {{$item.routeDesc}}
    </div>
    <div class="lrow-sub" style="margin-top:4px">{{$item.detail}}</div>
    <div class="bar"><div class="bar-in" style="width:{{$item.progress}}%;background:{{$item.color}}"></div></div>
    <div class="row" style="margin-top:12px">
      {{if:$item.canStart}}<div class="btn btn-sm btn-primary" data-act="start" data-tid="{{$item.id}}">开始</div>{{/if}}
      {{if:$item.canReassign}}<div class="btn btn-sm btn-primary" data-act="reassign" data-tid="{{$item.id}}">改派</div>{{/if}}
      {{if:$item.canPostpone}}<div class="btn btn-sm" data-act="postpone" data-tid="{{$item.id}}">顺延</div>{{/if}}
      {{if:$item.canCancel}}<div class="btn btn-sm btn-danger" data-act="cancel" data-tid="{{$item.id}}">取消</div>{{/if}}
    </div>
  </div>
  {{/each}}

  <div class="section-title">异常注入（演示功能三用）</div>
  <div class="row">
    <div class="btn btn-sm" data-act="inject" data-tid="Z1">1 号车遇障</div>
    <div class="btn btn-sm" data-act="inject" data-tid="Z2">2 号车遇障</div>
    <div class="btn btn-sm" data-act="silence" data-tid="Z3">3 号车失联</div>
    <div class="btn btn-sm btn-ghost" data-act="resetCars">车辆恢复在线</div>
  </div>
  <div class="lrow-sub" style="margin-top:8px">
    「遇障」让该区域立刻转阻塞；「失联」让该车不再回执，下一次判定即按阈值判失联（{{timeout}} 秒）。
  </div>

  <div class="dock">
    <div class="btn btn-primary" data-act="startRound">开始本轮巡检</div>
    <div class="btn btn-danger" data-act="cancelAll">一键取消</div>
    <div class="btn" data-act="go" data-tid="Map">看地图</div>
  </div>
</div>
{{if:toast}}<div class="toast">{{toast}}</div>{{/if}}
`

export const act = {
  back: function (ctx) { ctx.go('Home'); return false },
  go: function (ctx, tid) { ctx.go(tid); return false },
  start: function (ctx, tid) {
    toastText = store.start(tid).message
    return true
  },
  cancel: function (ctx, tid) {
    toastText = store.cancel(tid).message
    return true
  },
  reassign: function (ctx, tid) {
    const r = store.reassign(tid)
    toastText = r.message
    /* 自证探针：自动化测试靠它区分"点击没到"与"改派没换车" */
    if (typeof globalThis !== 'undefined' && globalThis.__vgProbe) {
      globalThis.__vgProbe.push('reassign(' + tid + ') → ' + r.message)
    }
    return true
  },
  postpone: function (ctx, tid) {
    toastText = store.postpone(tid).message
    return true
  },
  cancelAll: function () {
    toastText = store.cancelAll().message
    return true
  },
  startRound: function () {
    toastText = store.startRound().message
    return true
  },
  toggleCar: function (ctx, tid) {
    const c = CFG.carById(tid)
    toastText = store.setCarOnline(tid, !c.online).message
    return true
  },
  inject: function (ctx, tid) {
    toastText = store.injectObstacle(tid, '前方有障碍，已停车待处置').message
    return true
  },
  silence: function (ctx, tid) {
    toastText = store.silence(tid).message
    return true
  },
  resetCars: function () {
    toastText = store.resetCars().message
    return true
  }
}

export function onLeave() {
  toastText = ''
}

export default { title: title, tpl: tpl, data: data, act: act, onLeave: onLeave }
