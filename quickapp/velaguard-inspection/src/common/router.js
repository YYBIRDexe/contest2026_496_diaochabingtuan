/**
 * VelaGuard · 仓内路由
 *
 * 为什么自己写路由，而不用 `@system.router`：
 *   官方 Feature Framework 的 modules 清单里**没有** router 这个 JS 模块
 *   （只有 C 层的 ApplicationRoute / ApplicationStackPagePush），
 *   也就是说 `.ux` 里 `import router from '@system.router'` 在模拟器上
 *   不一定能解析。本工程用一个仓内路由 + 单页条件渲染绕开这个不确定性：
 *
 *     · openvela 上：app.ux 一个页面，六个视图靠 `curPage` 切换，零系统依赖
 *     · 浏览器预览里：同一个路由再同步一下 hash，前进/后退键也能用
 *
 * 代价是六个视图共用一个页面文件（编译时由 tools/build-openvela-app.js 拼装），
 * 换来的是"不依赖未验证的系统模块"。
 */

const PAGE_TITLES = {
  Home: 'VelaGuard 巡检桌面',
  Dispatch: '巡检调度台',
  Map: '地图与路线',
  Zones: '区域与路线',
  Records: '巡检记录',
  Voice: '语音助手'
}

let current = 'Home'
let stack = ['Home']
let listener = null

function notify() {
  if (listener) {
    listener(current)
  }
}

export function init(page) {
  current = PAGE_TITLES[page] ? page : 'Home'
  stack = ['Home']
  return current
}

export function push(page) {
  if (!PAGE_TITLES[page]) {
    return { ok: false, message: '页面不存在：' + page }
  }
  if (page === current) {
    return { ok: true, page: current }
  }
  stack.push(page)
  current = page
  notify()
  return { ok: true, page: current }
}

export function back() {
  if (stack.length <= 1) {
    return { ok: false, page: current }
  }
  stack.pop()
  current = stack[stack.length - 1]
  notify()
  return { ok: true, page: current }
}

export function replace(page) {
  if (!PAGE_TITLES[page]) {
    return { ok: false, page: current }
  }
  stack[stack.length - 1] = page
  current = page
  notify()
  return { ok: true, page: current }
}

export function get() {
  return current
}

export function title(page) {
  return PAGE_TITLES[page || current] || ''
}

export function home() {
  stack = ['Home']
  current = 'Home'
  notify()
  return current
}

export function onRoute(fn) {
  listener = fn
}

export function pages() {
  return Object.keys(PAGE_TITLES)
}

export default {
  init: init,
  push: push,
  back: back,
  replace: replace,
  get: get,
  title: title,
  home: home,
  onRoute: onRoute,
  pages: pages
}
