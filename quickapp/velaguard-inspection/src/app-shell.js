/**
 * 宿主无关的应用外壳（浏览器预览 与 openvela 快应用**共用这一份**）
 *
 * 它负责：
 *   · 定时 tick：每 250 ms 推进 store 的时钟与路线动画，并重绘
 *   · 路由：切页 / 返回，并同步浏览器 hash（openvela 上没有 hash，自动跳过）
 *   · 事件代理：把 [data-act] 的点击派发到对应页面的 act 表
 *   · 时钟、提示浮层、重绘后钩子（输入框焦点、聊天区滚动）
 *   · 把页面的 `import x from '../common/y.js'` 通过**注入的模块表**解析
 *
 * 为什么页面源码要用 import + 本文件在运行时解析：
 *   openvela 的快应用**不认 import 语句**（QuickJS + 快应用框架的模块机制有限），
 *   而浏览器不认全局变量式的模块。用 `__mod(name)` 解析后，两边都只依赖
 *   「一个查表函数」这一件事，页面源码因此可以完全不动。
 *
 * @param {object} env
 *   env.mod(name)       → 模块对象（'store' / 'data' / ...）
 *   env.pages           → { Home: {tpl,data,act,...}, ... }
 *   env.baseCss         → 公共样式串
 *   env.doc             → document（或快应用上的等价物）
 *   env.now()           → 当前时间戳（毫秒）
 *   env.clockText(ts)   → 时间文案
 *   env.setInterval / clearInterval
 *   env.onPageRendered(pageName, doc)  → 每次重绘后回调（可选）
 */
export function createApp(env) {
  const mod = env.mod
  const router = mod('router')
  const store = mod('store')
  const data = mod('data')
  const ui = mod('ui')

  const doc = env.doc
  let timer = null
  let curPage = 'Home'
  let scrollChat = false
  let lastTick = env.now()

  /** 当前页面的模块 */
  function pageMod(name) {
    return env.pages[name]
  }

  /** 组装模板上下文 */
  function buildCtx() {
    return {
      clock: env.clockText(env.now()),
      allRouteLength: data.allRouteLength(),
      /* 供页面调用：跳页 */
      go: function (page) {
        navigate(page)
      },
      /* 供页面调用：请求重绘（异步流程结束后用） */
      render: function () {
        renderPage()
      }
    }
  }

  /**
   * 派发一个动作（宿主的事件绑定层最终都会调到这里）。
   * actName 来自元素的 data-act，tid 来自 data-tid。
   */
  function dispatch(actName, tid) {
    const p = pageMod(curPage)
    if (!p || !p.act || !p.act[actName]) {
      return false
    }
    const ctx = buildCtx()
    const need = p.act[actName](ctx, tid)
    if (need) {
      renderPage()
    }
    return true
  }

  /** 渲染当前页面 */
  function renderPage() {
    const p = pageMod(curPage) || pageMod('Home')
    const tpl = mod('tpl')
    const ctx = buildCtx()
    ctx.scrollChat = scrollChat
    const view = p.data ? p.data(ctx) : {}
    /* 把 ctx 里的辅助函数并进视图数据，模板里可以直接用 */
    view.go = ctx.go
    view.render = ctx.render
    view.title = p.title || ''

    let html = tpl.render(p.tpl, view)
    /*
     * 交给宿主的绑定层处理交互。
     * 浏览器侧挂事件代理；openvela 侧把 data-act 改写成 onclick 字符串
     * （快应用没有 DOM 事件代理，只能在字符串阶段就把处理器写进节点）。
     */
    if (env.bindActions) {
      html = env.bindActions(html, p)
    }
    env.setContent(html)

    /* 重绘后钩子：输入框、滚动位置等 DOM 相关的事交给宿主/页面自己处理 */
    if (env.afterRender) {
      env.afterRender(curPage, p)
    }
    if (p.afterRender) {
      p.afterRender(env.doc)
    }
    if (env.onPageRendered) {
      env.onPageRendered(curPage, env.doc)
    }
    scrollChat = false
  }

  /** 统一的重绘入口（合并同一帧内的多次请求） */
  let pendingRender = false
  function requestRender() {
    if (pendingRender) {
      return
    }
    pendingRender = true
    env.setTimeout(function () {
      pendingRender = false
      renderPage()
    }, 0)
  }

  /** 切页 */
  function navigate(page) {
    if (pageMod(page)) {
      curPage = page
    } else {
      return
    }
    if (env.setHash) {
      env.setHash(page)
    }
    const p = pageMod(curPage)
    /* 离开页面时给旧页面一次清理机会 */
    renderPage()
  }

  /** 时钟与动画推进 */
  function tick() {
    const now = env.now()
    const dt = Math.max(0, Math.min(1, (now - lastTick) / 1000))
    lastTick = now
    const events = store.tick(dt)
    const p = pageMod(curPage)
    /* 有事件时弹提示（主动告警的界面落点） */
    if (events && events.length) {
      ui.toast(events[0].text, 3200)
    }
    /* 只在地图/桌面/调度台这几页重绘，避免无谓开销 */
    if (curPage === 'Map' || curPage === 'Home' || curPage === 'Dispatch' || events.length) {
      renderPage()
    }
  }

  return {
    start: function (initial) {
      curPage = pageMod(initial) ? initial : 'Home'
      renderPage()
      if (timer) {
        env.clearInterval(timer)
      }
      timer = env.setInterval(tick, 250)
      return curPage
    },
    stop: function () {
      if (timer) {
        env.clearInterval(timer)
        timer = null
      }
    },
    render: renderPage,
    navigate: navigate,
    dispatch: dispatch,
    current: function () { return curPage },
    requestRender: requestRender
  }
}

export default { createApp: createApp }
