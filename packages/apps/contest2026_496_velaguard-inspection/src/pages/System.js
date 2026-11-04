/**
 * 页面：系统与链路（System）
 *
 * 把"这一版到底跑在哪、连的是什么"如实摊开，方便评委/队友一眼看清，
 * 也避免把模拟器里的演示说成真车在跑。
 *
 * 重点写清三件事：
 *   1. 三条链路各是谁：端侧（openvela）／边缘层（M1）／车端（ROS 2 小车）
 *   2. 这一版**实际启用了哪条**（默认：端侧自包含演示，不碰真车）
 *   3. 与真车对接时缺什么（车端路线执行节点 + 回执通道）
 */
import store from '../common/store.js'
import CFG from '../common/data.js'
import agent from '../common/agent.js'

let toastText = ''

export const title = '系统与链路'

export function data(ctx) {
  const snap = store.snapshot()
  const st = agent.status()

  const links = [
    {
      name: '端侧 · openvela',
      what: '任务状态机、异常判定、主动告警、覆盖汇总、跨轮次记忆',
      how: '本快应用 + 仓内路由（不依赖未验证的系统 router 模块）',
      state: '已启用',
      color: '#3DDC84'
    },
    {
      name: '端侧 AI · ai_agent',
      what: '口语化理解与播报文本生成；按 Skill 调用它自己的工具',
      how: '@system.velaclaw（POSIX 消息队列，非 WebSocket）',
      state: st.ready === true ? '已连接' : (st.ready === false ? '不可用（本地指令模式）' : '未探测'),
      color: st.ready === true ? '#3DDC84' : (st.ready === false ? '#FBBF24' : '#94A3B8')
    },
    {
      name: '边缘层 · M1（Ubuntu）',
      what: '语音采集与播报、触控看板、四车下发通道',
      how: 'WebSocket 28789（Agent 侧）／本地 HTTP（看板侧）',
      state: '独立运行（本版不依赖）',
      color: '#4DA3FF'
    },
    {
      name: '车端 · ROS 2 小车',
      what: '路线执行、本地感知与安全（遇障停车）',
      how: 'ROS 2 topic；本版**未连接**，用地图动画演示',
      state: '待对接',
      color: '#FBBF24'
    }
  ]

  return {
    clock: ctx.clock,
    toast: toastText,
    links: links,
    mapName: CFG.MAP.name,
    mapSrc: 'classroom.pgm（350×197 格）',
    resolution: CFG.MAP.resolution + ' m/格',
    origin: '[' + CFG.MAP.origin.join(', ') + ']',
    bounds: 'x ' + CFG.MAP.bounds.x.join(' ~ ') + '   y ' + CFG.MAP.bounds.y.join(' ~ '),
    cars: snap.cars.map(function (c) {
      return {
        id: c.id,
        name: c.name,
        ip: c.ip,
        online: c.online ? '#3DDC84' : '#FBBF24',
        battery: c.battery,
        mode: c.mode,
        statusText: c.online ? '在线' : '离线'
      }
    }),
    limits: CFG.LIMITS,
    agentText: st.text,
    agentHint: st.hint,
    round: snap.round
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

  <div class="section-title">跑在哪</div>
  <div class="card">
    <div class="kv"><span class="kv-k">运行平台</span><span class="kv-v">openvela Vela Emulator</span></div>
    <div class="kv"><span class="kv-k">板级配置</span><span class="kv-v mono">goldfish-arm64-v8a-ap</span></div>
    <div class="kv"><span class="kv-k">应用形态</span><span class="kv-v">Vela 快应用（QuickJS + LVGL + Yoga）</span></div>
    <div class="kv"><span class="kv-k">屏幕</span><span class="kv-v">720 × 1280 竖屏</span></div>
    <div class="kv"><span class="kv-k">本轮</span><span class="kv-v">第 {{round}} 轮</span></div>
  </div>

  <div class="section-title">三条链路各是谁</div>
  {{each:links}}
  <div class="card" style="padding:12px 16px">
    <div class="row-between">
      <span class="lrow-title">{{$item.name}}</span>
      <span style="color:{{$item.color}};font-size:19px;font-weight:700">{{$item.state}}</span>
    </div>
    <div class="lrow-sub" style="margin-top:6px">{{$item.what}}</div>
    <div class="lrow-sub" style="margin-top:2px">{{$item.how}}</div>
  </div>
  {{/each}}

  <div class="section-title">端侧 AI 通道</div>
  <div class="card">
    <div class="kv"><span class="kv-k">状态</span><span class="kv-v">{{agentText}}</span></div>
    <div class="lrow-sub" style="margin-top:6px">{{agentHint}}</div>
    <div class="lrow-sub" style="margin-top:6px">
      快应用与端侧 Agent 之间**没有 WebSocket**：官方给的是 @system.velaclaw.ask()，
      走 POSIX 消息队列。所以语音页不做 WS 客户端，直接调 ask()。
    </div>
  </div>

  <div class="section-title">地图基准</div>
  <div class="card">
    <div class="kv"><span class="kv-k">底图</span><span class="kv-v">{{mapSrc}}</span></div>
    <div class="kv"><span class="kv-k">分辨率</span><span class="kv-v">{{resolution}}</span></div>
    <div class="kv"><span class="kv-k">原点</span><span class="kv-v mono">{{origin}}</span></div>
    <div class="kv"><span class="kv-k">可行区域</span><span class="kv-v mono">{{bounds}}</span></div>
    <div class="lrow-sub" style="margin-top:6px">
      来自车端当前生效的 ROS 地图，由 tools/ros-map-to-vector.js 自动转成矢量轮廓。
    </div>
  </div>

  <div class="section-title">阈值与限值</div>
  <div class="card">
    <div class="kv"><span class="kv-k">单步距离上限</span><span class="kv-v">{{limits.step_distance_max_m}} m</span></div>
    <div class="kv"><span class="kv-k">失联判定</span><span class="kv-v">{{limits.receipt_timeout_s}} s 无回执</span></div>
    <div class="kv"><span class="kv-k">单任务时限</span><span class="kv-v">{{limits.task_deadline_s}} s</span></div>
    <div class="kv"><span class="kv-k">低电量不派单</span><span class="kv-v">{{limits.battery_min}} %</span></div>
    <div class="kv"><span class="kv-k">演示推进速度</span><span class="kv-v">{{limits.demo_speed_mps}} m/s（真车 0.12 m/s）</span></div>
  </div>

  <div class="section-title">车辆</div>
  {{each:cars}}
  <div class="lrow">
    <div class="lrow-main">
      <div class="row">
        <div class="dot" style="background:{{$item.online}}"></div>
        <span class="lrow-title">{{$item.name}}</span>
        <span class="small muted" style="margin-left:10px">{{$item.ip}}</span>
      </div>
      <div class="lrow-sub">电量 {{$item.battery}}% · 通道 {{$item.mode}}</div>
    </div>
    <span style="color:{{$item.online}};font-size:19px">{{$item.statusText}}</span>
  </div>
  {{/each}}

  <div class="lrow-sub">
    诚实声明：模拟器没有摄像头、激光雷达、麦克风、GPIO。本版所有"感知"均由演示数据代替，
    不声称模拟器具备任何物理外设能力；与真车对接需要车端的路线执行节点与回执通道。
  </div>

  <div class="dock">
    <div class="btn" data-act="go" data-tid="Home">返回桌面</div>
    <div class="btn" data-act="go" data-tid="Voice">语音助手</div>
  </div>
</div>
{{if:toast}}<div class="toast">{{toast}}</div>{{/if}}
`

export const act = {
  back: function (ctx) { ctx.go('Home'); return false },
  go: function (ctx, tid) { ctx.go(tid); return false }
}

export function onLeave() {
  toastText = ''
}

export default { title: title, tpl: tpl, data: data, act: act, onLeave: onLeave }
