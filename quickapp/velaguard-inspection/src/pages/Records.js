/**
 * 页面：巡检记录（Records）
 *
 * 功能四「巡检覆盖的基础汇总」的台账部分：每轮四个区域的完成情况 + 一句话结论。
 * 首期边界（写进方案里的）：**只汇总任务状态**，不传实时视频、不下视觉识别结论。
 */
import store from '../common/store.js'
import CFG from '../common/data.js'

let toastText = ''

export const title = '巡检记录'

export function data(ctx) {
  const snap = store.snapshot()
  const mem = store.memoryOfLastRound()
  const statusDict = CFG.STATUS

  return {
    clock: ctx.clock,
    toast: toastText,
    round: snap.round,
    summaryLine: snap.summaryLine,
    counts: snap.summary.counts,
    total: snap.summary.total,
    hasRecords: snap.records.length > 0,
    recordCount: snap.records.length,
    records: snap.records.map(function (r) {
      return {
        round: r.round,
        time: r.time,
        summary: r.summary,
        zones: r.zones.map(function (z) {
          const st = statusDict[z.result] || statusDict.pending
          return {
            name: z.name,
            resultText: z.resultText || st.text,
            color: st.color
          }
        })
      }
    }),
    memory: mem ? mem.text : ''
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

  <div class="hero">
    <span class="small muted">本轮（第 {{round}} 轮）</span>
    <div class="hero-main">{{summaryLine}}</div>
    <div class="stats">
      <div class="stat"><span class="stat-num" style="color:#3DDC84">{{counts.done}}</span><span class="stat-label">已完成</span></div>
      <div class="stat"><span class="stat-num" style="color:#FF6B6B">{{counts.blocked}}</span><span class="stat-label">阻塞</span></div>
      <div class="stat"><span class="stat-num" style="color:#FBBF24">{{counts.offline}}</span><span class="stat-label">离线</span></div>
      <div class="stat"><span class="stat-num" style="color:#94A3B8">{{counts.pending}}</span><span class="stat-label">待执行</span></div>
    </div>
  </div>

  {{if:memory}}
  <div class="card" style="border-left:4px solid #f59e0b">
    <span class="small" style="color:#fbbf24">跨轮次记忆：{{memory}}</span>
  </div>
  {{/if}}

  <div class="section-title">历史轮次（{{recordCount}} 条）</div>
  {{if:hasRecords}}
  {{each:records}}
  <div class="card">
    <div class="row-between">
      <span class="lrow-title">{{$item.round}}</span>
      <span class="small muted">{{$item.time}}</span>
    </div>
    <div class="lrow-sub" style="margin-top:6px">{{$item.summary}}</div>
    <div class="row" style="margin-top:10px;flex-wrap:wrap">
      {{each1:$item.zones}}
      <div class="chip" style="background:#1b2942;min-height:42px">
        <span style="color:{{$item.color}};font-size:19px">{{$item.name}} {{$item.resultText}}</span>
      </div>
      {{/each1}}
    </div>
  </div>
  {{/each}}
  {{else}}
  <div class="empty">还没有归档的轮次。巡检跑完一轮后点「收轮归档」。</div>
  {{/if}}

  <div class="lrow-sub">
    首期只汇总**任务状态**（已完成 / 未开始 / 阻塞 / 离线），不传实时视频、不下视觉识别结论。
  </div>

  <div class="dock">
    <div class="btn btn-primary" data-act="closeRound">收轮归档</div>
    <div class="btn" data-act="go" data-tid="Dispatch">调度台</div>
  </div>
</div>
{{if:toast}}<div class="toast">{{toast}}</div>{{/if}}
`

export const act = {
  back: function (ctx) { ctx.go('Home'); return false },
  go: function (ctx, tid) { ctx.go(tid); return false },
  closeRound: function () {
    toastText = store.closeRound().message
    return true
  }
}

export function onLeave() {
  toastText = ''
}

export default { title: title, tpl: tpl, data: data, act: act, onLeave: onLeave }
