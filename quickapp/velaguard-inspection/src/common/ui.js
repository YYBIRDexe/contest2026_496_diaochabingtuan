/**
 * VelaGuard · 界面小工具（提示 + 时钟）
 *
 * 为什么不直接用 `@system.prompt`：
 *   快应用的 prompt 是**异步系统调用**，在浏览器预览里没有对应实现。
 *   这里做一个仓内实现：提示自己画成浮层（两处行为完全一致，预览即所见），
 *   时钟也由自己维护，不依赖宿主定时器。
 */

let toastText = ''
let toastUntil = 0
let listener = null

/** 显示一条提示（默认 2.2 秒） */
export function toast(msg, ms) {
  toastText = String(msg === undefined || msg === null ? '' : msg)
  toastUntil = Date.now() + (ms || 2200)
  if (listener) {
    listener(toastText)
  }
  return toastText
}

/** 当前该显示的提示文本（过期自动变空） */
export function toastNow() {
  if (Date.now() > toastUntil) {
    return ''
  }
  return toastText
}

export function clearToast() {
  toastText = ''
  toastUntil = 0
  if (listener) {
    listener('')
  }
}

export function onToast(fn) {
  listener = fn
}

/** 两位补零 */
function pad(n) {
  return n < 10 ? '0' + n : '' + n
}

/**
 * 时间文案。
 * 显示**年月日 + 时分秒**，因为设备/模拟器的 RTC 不一定准，
 * 只显示 HH:MM 时出问题根本看不出是哪天（M1 上踩过这个坑）。
 */
export function clockText(d) {
  const t = d || new Date()
  return t.getFullYear() + '-' + pad(t.getMonth() + 1) + '-' + pad(t.getDate()) +
    ' ' + pad(t.getHours()) + ':' + pad(t.getMinutes()) + ':' + pad(t.getSeconds())
}

/** 短时间（HH:MM），给列表行用 */
export function clockShort(d) {
  const t = d || new Date()
  return pad(t.getHours()) + ':' + pad(t.getMinutes())
}

export default {
  toast: toast,
  toastNow: toastNow,
  clearToast: clearToast,
  onToast: onToast,
  clockText: clockText,
  clockShort: clockShort
}
