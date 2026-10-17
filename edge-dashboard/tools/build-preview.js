'use strict'

/**
 * 把快应用工程编译成可在浏览器里直接点开的预览页。
 *
 * 目的：openvela 真机 / 模拟器需要 Linux 编译环境与 AIoT-IDE，
 * 在拿到这些之前，先用浏览器把同一套 .ux 源码渲染出来，
 * 确认布局、配色、交互是否符合预期。
 *
 * 做法（不是「另写一份 UI」，而是复用同一份源码）：
 *   - 读取 src/pages/<页面>/index.ux 的 template / style / script
 *   - 把 Vela 模板语法（for / if / {{}} / onclick+tid）转成可反复重渲染的 DOM 描述
 *   - 把 <script> 里的 import 换成注入的桩件，export default 换成 return
 *   - 拼接成一个单文件 HTML，内置一个极简渲染引擎
 *   - store.js 直接以 ESM 方式引入，保证预览与真机共用同一份数据源
 *
 * 用法：node tools/build-preview.js
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..')
const SRC = path.join(ROOT, 'src')
const OUT_DIR = path.join(ROOT, 'preview')

const manifest = JSON.parse(fs.readFileSync(path.join(SRC, 'manifest.json'), 'utf8'))

/* ------------------------------------------------------------------ *
 * 工具
 * ------------------------------------------------------------------ */
function extract(ux, tag) {
  const m = ux.match(new RegExp('<' + tag + '>([\\s\\S]*?)</' + tag + '>'))
  return m ? m[1] : ''
}

/** 找到与 start 处开标签配对的闭标签位置（含嵌套） */
function findBlock(html, attrIndex) {
  const openStart = html.lastIndexOf('<', attrIndex)
  const openEnd = html.indexOf('>', attrIndex)
  if (openStart < 0 || openEnd < 0) {
    return null
  }
  const nameMatch = html.slice(openStart, openEnd).match(/^<([a-zA-Z][a-zA-Z0-9-]*)/)
  if (!nameMatch) {
    return null
  }
  const name = nameMatch[1]
  const re = new RegExp('<' + name + '(?=[\\s/>])|</' + name + '\\s*>', 'g')
  re.lastIndex = openEnd
  let depth = 1
  let m
  while ((m = re.exec(html)) !== null) {
    if (m[0].charAt(1) === '/') {
      depth -= 1
      if (depth === 0) {
        return {
          start: openStart,
          end: re.lastIndex,
          openEnd: openEnd + 1,
          name: name
        }
      }
    } else {
      depth += 1
    }
  }
  return null
}

/** 用点号路径从数据对象取值：a.b.c */
function pick(data, expr) {
  const parts = expr.trim().split('.')
  let cur = data
  for (let i = 0; i < parts.length; i += 1) {
    if (cur === null || cur === undefined) {
      return undefined
    }
    cur = cur[parts[i]]
  }
  return cur
}

/* ------------------------------------------------------------------ *
 * 模板转换
 * ------------------------------------------------------------------ */

/** 处理 for="{{expr}}"：把循环下移到元素自身的 each 属性，不引入包裹元素 */
function expandLoops(tpl) {
  return tpl.replace(/\sfor="\{\{\s*([^}]+?)\s*\}\}"/g, ' data-each="$1"')
}

/** Vela 控件 → HTML 标签映射（样式由 CSS 决定，这里只管语义与默认盒模型） */
const TAG_MAP = {
  text: 'span',
  scroll: 'div',
  image: 'div',
  input: 'div',
  switch: 'div',
  slider: 'div',
  progress: 'div',
  divider: 'div',
  stack: 'div'
}

/** 是否落在引号内部（用于避免在属性值里做文本替换） */
function inQuote(s, i) {
  let q = null
  for (let k = 0; k < i; k += 1) {
    const c = s[k]
    if (q === null) {
      if (c === '"' || c === "'") {
        q = c
      }
    } else if (c === q) {
      q = null
    }
  }
  return q !== null
}

/**
 * 标签感知的模板转换：逐个开标签解析属性，再分别处理
 * 属性绑定（data-bind 类）、事件（data-act / data-tid）与文本插值。
 * 关键点：文本插值只在标签之外的片段进行，否则 {{}} 会被写进属性值里。
 */
function transformTemplate(tpl) {
  const openRe = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:"[^"]*"|[^>"/])*)\s*(\/?)>/g

  const withTags = tpl.replace(openRe, function (full, slash, name, attrStr, selfClose) {
    const mapped = TAG_MAP[name] || name

    // 闭标签只需要换名字
    if (slash) {
      return '</' + mapped + '>'
    }

    // 1. 拆出属性键值对
    const attrRe = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)")?/g
    const parts = []
    const props = {}
    let m
    while ((m = attrRe.exec(attrStr)) !== null) {
      if (m[2] === undefined) {
        props[m[1]] = true
        parts.push(m[1])
      } else {
        props[m[1]] = m[2]
      }
    }

    // 2. 逐个属性决定输出形式
    Object.keys(props).forEach(function (k) {
      const v = props[k]
      if (v === true) {
        return
      }
      if (k === 'for') {
        parts.push('data-each="' + v.replace(/\{\{\s*|\s*\}\}/g, '') + '"')
      } else if (k === 'if') {
        parts.push('data-if="' + v.replace(/\{\{\s*|\s*\}\}/g, '') + '"')
      } else if (k === 'onclick') {
        parts.push('data-act="' + v.trim() + '"')
      } else if (k === 'tid') {
        parts.push('data-tid="' + v.replace(/\{\{\s*|\s*\}\}/g, '') + '"')
      } else if (k === 'style' && v.indexOf('{{') >= 0) {
        parts.push('data-style="' + v.replace(/\{\{\s*|\s*\}\}/g, '') + '"')
      } else if (k === 'class' && v.indexOf('{{') >= 0) {
        const literal = v.replace(/\{\{[^}]*\}\}/g, '').trim()
        const binding = (v.match(/\{\{\s*([^}]+?)\s*\}\}/) || [])[1] || ''
        if (literal) {
          parts.push('class="' + literal + '"')
        }
        parts.push('data-class="' + binding + '"')
      } else {
        parts.push(k + '="' + v + '"')
      }
    })

    return '<' + mapped + (parts.length ? ' ' + parts.join(' ') : '') + '>'
  })

  // 3. 只在标签之外做文本插值
  return withTags
    .split(/(<[^>]*>)/g)
    .map(function (seg) {
      if (seg.charAt(0) === '<') {
        return seg
      }
      return seg.replace(/\{\{\s*([^}]+?)\s*\}\}/g, '<b data-bind="$1"></b>')
    })
    .join('')
}

/* ------------------------------------------------------------------ *
 * 样式作用域化
 * ------------------------------------------------------------------ */
/**
 * 把页面样式作用域化到指定祖先选择器下。
 *
 * 注意：必须用换行把每条规则分开。否则源码里的 /* 注释 *\/ 会被拼到上一条规则
 * 的右花括号后面，形成 "} /* 注释 *\/ .next {"，把紧随其后的选择器整条注释掉。
 */
function scopeCSS(css, scope) {
  // 先整体去掉 /* */ 注释，再进行作用域化。
  // 分节注释（例如 /* ---------- 状态栏 ---------- */）本身不含大括号，
  // 但若带着注释扫描，注释里的文字会被误当作选择器片段；更麻烦的是
  // 这类注释行的定位会污染后续规则，导致整段样式没被加上作用域前缀。
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '')

  const out = []
  let buf = ''
  let depth = 0
  for (let i = 0; i < clean.length; i += 1) {
    const ch = clean[i]
    if (ch === '{') {
      if (depth === 0) {
        const sel = buf.trim()
        if (sel) {
          out.push(sel.split(',').map(function (s) {
            return scope + ' ' + s.trim()
          }).join(', ') + ' {')
        } else {
          // 选择器为空说明当前是 @规则 之类，原样保留
          out.push(buf + '{')
        }
      } else {
        out.push(buf + '{')
      }
      buf = ''
      depth += 1
    } else if (ch === '}') {
      depth -= 1
      out.push(buf + '}')
      buf = ''
    } else {
      buf += ch
    }
  }
  if (buf.trim()) {
    out.push(buf)
  }
  return out.join('\n')
}

/* ------------------------------------------------------------------ *
 * 脚本转换：Vela 模块 → 普通函数体
 * ------------------------------------------------------------------ */

/**
 * 去掉脚本里的注释。
 *
 * 为什么需要：页面脚本里写了大量中文块注释（设计说明、踩坑记录等），
 * 之前只清了 CSS 注释，脚本注释被原样打进产物 —— 既让产物虚增，
 * 又把内部说明泄漏到交付文件里（实测发现「串口控制台执行 ai_agent」
 * 这类注释出现在最终 HTML 中）。
 *
 * 实现要点：不能直接用正则，否则字符串里的 "/*" 会被误判。
 * 这里逐字符扫描，跟踪是否处于字符串内部（含转义），只删真正的注释。
 * 行注释保留（它们可能承载 URL 之类的信息，且体积很小）。
 */
function stripScriptComments(code) {
  let out = ''
  let i = 0
  const n = code.length

  while (i < n) {
    const c = code[i]
    const next = i + 1 < n ? code[i + 1] : ''

    // 字符串字面量：整体复制，内部不解析注释
    if (c === '"' || c === "'" || c === '`') {
      const quote = c
      out += c
      i += 1
      while (i < n) {
        if (code[i] === '\\') {
          out += code[i] + (i + 1 < n ? code[i + 1] : '')
          i += 2
          continue
        }
        out += code[i]
        if (code[i] === quote) {
          i += 1
          break
        }
        i += 1
      }
      continue
    }

    // 块注释：整段丢弃，但保留换行以维持行号
    if (c === '/' && next === '*') {
      const end = code.indexOf('*/', i + 2)
      const stop = end < 0 ? n : end + 2
      const removed = code.slice(i, stop)
      const newlines = (removed.match(/\n/g) || []).length
      out += '\n'.repeat(newlines)
      i = stop
      continue
    }

    out += c
    i += 1
  }

  // 清掉整行只剩空白的情况，避免产物里留下大片空行
  return out.replace(/^[ \t]+$/gm, '')
}

function transformScript(script, pageKey) {
  let s = script
  // 去掉块注释（含设计说明），再处理 import / export
  s = stripScriptComments(s)
  s = s.replace(/^\s*import\s+[^\n]*?from\s*['"][^'"]+['"]\s*$/gm, '')
  s = s.replace(/^\s*import\s+['"][^'"]+['"]\s*$/gm, '')
  s = s.replace(/export\s+default\s*/, 'return ')
  return s
}

/* ------------------------------------------------------------------ *
 * 组装页面
 * ------------------------------------------------------------------ */
const pages = {}
Object.keys(manifest.router.pages).forEach(function (name) {
  const cfg = manifest.router.pages[name]
  const file = path.join(SRC, 'pages', name, cfg.component + '.ux')
  const ux = fs.readFileSync(file, 'utf8')
  const tpl = extract(ux, 'template')
  const sty = extract(ux, 'style')
  const scr = extract(ux, 'script')

  const markup = transformTemplate(expandLoops(tpl))

  pages[name] = {
    name: name,
    path: cfg.path || '/' + name,
    html: markup.trim(),
    // 作用域化在构建期完成，浏览器侧不再需要 CSS 解析器
    // 注意：每个页面的样式都以 [data-page="<页面名>"] 为前缀，
    // 引擎切页时会给 #root 打上对应属性，从而只命中当前页面的样式。
    css: scopeCSS(sty.trim(), '[data-page="' + name + '"]'),
    script: transformScript(scr, name)
  }
})

/* ------------------------------------------------------------------ *
 * 内联数据源
 *
 * 预览页必须是「单文件自包含」的：断网环境下不允许再发任何请求，
 * 因此这里把 src/common/store.js 的内容直接内联进 HTML，
 * 而不是用 ESM 去 import 它（离线时模块加载可能被浏览器拦截）。
 * 转换：去掉 import/export，让 store 变量留在同一段作用域里。
 * ------------------------------------------------------------------ */
function inlineStore() {
  let code = fs.readFileSync(path.join(SRC, 'common', 'store.js'), 'utf8')
  // 去掉 export 关键字，并删掉末尾的 export default { ... } 汇总块
  code = code.replace(/^\s*export\s+default\s*\{[\s\S]*?\}\s*$/m, '')
  code = code.replace(/^\s*export\s+function\s+/gm, 'function ')
  code = code.replace(/^\s*export\s+/gm, '')
  return code
}
const STORE_SOURCE = inlineStore()

/**
 * 数据源适配层也一并内联。
 * 它依赖上面的 store（同一段作用域），所以必须排在 store 之后。
 */
function inlineSource() {
  let code = fs.readFileSync(path.join(SRC, 'common', 'source.js'), 'utf8')
  return code.replace(/^\s*export\s+/gm, '')
}
const SOURCE_SOURCE = inlineSource()

/* ------------------------------------------------------------------ *
 * 生成 HTML
 * ------------------------------------------------------------------ */
const iconFiles = {}
;['logo.png', 'icon-voice.png', 'icon-dispatch.png', 'icon-zones.png', 'icon-records.png', 'icon-system.png']
  .forEach(function (f) {
    const p = path.join(SRC, 'common', f)
    if (fs.existsSync(p)) {
      iconFiles[f] = fs.readFileSync(p).toString('base64')
    }
  })

const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>VelaGuard 巡检桌面 · 浏览器预览</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  /*
   * 触屏观感对齐手机：禁用浏览器默认的文本交互。
   *   user-select: none        长按拖拽不再选中文字、不出现蓝色高亮
   *   -webkit-touch-callout    长按不弹系统式菜单
   *   tap-highlight-color      点按不闪灰色高亮块
   *   -webkit-user-drag        禁止拖拽元素
   *   overscroll-behavior      禁止下拉刷新 / 橡皮筋回弹
   *   touch-action: manipulation 去掉双击缩放带来的 300ms 延迟
   * 界面里的文字都是展示性内容（标签、数值、状态），不需要被选中复制。
   */
  * {
    -webkit-user-select: none;
    -moz-user-select: none;
    -ms-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
    -webkit-tap-highlight-color: transparent;
    -webkit-user-drag: none;
    overscroll-behavior: none;
    touch-action: manipulation;
    /*
     * cursor: none —— 隐藏浏览器层的光标。
     *
     * 为什么 X 层隐藏了还要在这里再隐藏一次：
     * 触控屏上用户仍能看到指针，说明除了 X 的系统光标之外，
     * 浏览器还可能在页面内自绘光标（Firefox 在触屏/kiosk 场景下会这么做）。
     * XDefineCursor 只能管到 X 的光标，管不到浏览器自绘的那个。
     * 所以两层都要设。
     */
    cursor: none !important;
  }
  html, body {
    height: 100%;
    background: #05080f;
    color: #94a3b8;
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    overflow: hidden;
    -webkit-tap-highlight-color: transparent;
    user-select: none;
  }
  #bar {
    height: 46px;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 0 18px;
    background: #0b1220;
    border-bottom: 1px solid #16223a;
    font-size: 13px;
  }
  #bar b { color: #e2e8f0; font-size: 14px; }
  #bar .sep { color: #334155; }
  #bar .spacer { flex: 1; }
  #bar button {
    background: #16223a; color: #cbd5e1; border: 1px solid #23324f;
    border-radius: 6px; padding: 5px 12px; font-size: 12px;
    font-family: inherit;
  }
  #bar button:hover { background: #1d2a44; }
  #bar button.on { background: #2f6df6; color: #fff; border-color: #2f6df6; }
  /* 看板模式：隐藏工具栏，界面独占整屏 */
  body.kiosk #bar { display: none; }
  body.kiosk #stage { top: 0; }
  #stage {
    position: absolute; top: 46px; left: 0; right: 0; bottom: 0;
    display: flex; align-items: center; justify-content: center;
  }
  #frame {
    position: relative;
    overflow: hidden;
    background: #0b1220;
    box-shadow: 0 20px 60px rgba(0,0,0,0.6);
    transform-origin: center center;
  }
  /*
   * #root 是「设备屏幕」的根：让它本身也是列方向弹性容器，
   * 页面根节点才能拿到确定的 1280x800，height:100% 也才有正确的参照。
   */
  #root {
    display: flex;
    flex-direction: column;
    position: absolute;
    left: 0;
    top: 0;
    /* 弹性子项的 min-height 默认是 auto，会让内容撑破 800 高的屏幕框，
       导致 height:100% 解析成 896。清零后页面根节点才严格等于设备屏幕尺寸。 */
    min-height: 0;
    transform-origin: top left;
  }
  #toast {
    position: absolute; left: 50%; bottom: 40px; transform: translateX(-50%);
    background: #2f6df6; color: #fff; padding: 12px 26px; border-radius: 20px;
    font-size: 16px; opacity: 0; transition: opacity .2s; pointer-events: none;
    z-index: 99; max-width: 80%;
  }
  #toast.show { opacity: 1; }
  .pv-icon { display: inline-block; background-size: 100% 100%; }
  .pv-glyph { display: block; }
  /*
   * Vela 控件的盒模型对齐（关键）：
   *   - Vela 的 <text> 是行内盒，没有宽高；
   *   - Vela 的 <div> 默认就是「列方向弹性容器」，也就是 display:flex + column，
   *     所以 .ux 里写 flex-direction: row 才会生效。普通 HTML 的 div 只是静态块，
   *     若不补齐这一层，所有横向排版都会退化成纵向堆叠。
   *   - <scroll> 是可滚动容器。
   * 只有对齐这几点，同一份 .ux 在浏览器与真机上的排版才一致。
   */
  span { display: inline; }
  img { display: block; }
  div, scroll { display: flex; flex-direction: column; }
  scroll { overflow: hidden; }
  .pv-hidden { display: none !important; }
  ${Object.keys(iconFiles).map(function (f) {
    return '.pv-' + f.replace(/\.png$/, '') + ' { background-image: url(data:image/png;base64,' + iconFiles[f] + '); }'
  }).join('\n  ')}
</style>
</head>
<body>
<div id="bar">
  <b>VelaGuard 巡检桌面 · 浏览器预览</b>
  <span class="sep">|</span>
  <span>同一份 .ux 源码渲染，尺寸 1:1（设计基准宽 1280）</span>
  <span class="spacer"></span>
  <span id="pagelist"></span>
  <button id="btn-fit" class="on">适应窗口</button>
  <button id="btn-real">1:1</button>
</div>
<div id="stage">
  <div id="frame">
    <div id="root"></div>
    <div id="toast"></div>
    <pre id="errbox" style="display:none;position:absolute;left:8px;top:8px;right:8px;z-index:200;background:#3b0d0d;color:#ffb4b4;padding:12px;border-radius:8px;font-size:12px;white-space:pre-wrap;max-height:60%;overflow:auto"></pre>
  </div>
</div>

<script>
  // 把模块初始化期的异常显示出来，避免白屏无从排查
  window.__err = ''
  function showErr(msg) {
    window.__err = String(msg)
    var d = document.getElementById('errbox')
    if (d) { d.textContent = String(msg); d.style.display = 'block' }
  }
  window.addEventListener('error', function (e) {
    showErr((e.message || 'error') + ' @ ' + (e.filename || '') + ':' + (e.lineno || 0))
  })
  window.addEventListener('unhandledrejection', function (e) {
    showErr('rejection: ' + (e.reason && e.reason.message ? e.reason.message : e.reason))
  })
</script>
<script type="module">
/* ---- 内联 src/common/store.js（断网可用，不发任何请求） ---- */
${STORE_SOURCE}
/* ---- 数据源结束 ---- */

/* ---- 内联 src/common/source.js（依赖上面的 store，顺序不能调） ---- */
${SOURCE_SOURCE}
/* ---- 适配层结束 ---- */

/**
 * 数据源实例（唯一数据入口）。
 * 模式优先级：URL 参数 ?src= > 无网络时的默认 demo。
 * 页面只通过它读写数据，不知道背后是演示、文件还是真实链路。
 */
const DEFAULT_SRC = (function () {
  const m = String(location.search || '').match(/[?&]src=(demo|file|sim)/)
  return m ? m[1] : 'demo'
})()

const source = createSource(DEFAULT_SRC)

/* 兼容：部分页面还按 store 风格调用，这里给一个等价视图 */
const store = {
  getZones: getZones,
  getCars: getCars,
  getRecords: getRecords,
  statusOf: statusOf,
  summarize: summarize,
  dispatchTask: dispatchTask,
  cancelTask: cancelTask,
  cancelAll: cancelAll,
  markDone: markDone
}

const PAGES = ${JSON.stringify(pages)}
const ICONS = ${JSON.stringify(Object.keys(iconFiles))}
/*
 * 设计基准尺寸。目标设备（M1 + E5 触控屏）实测帧缓冲为 1920x1080，
 * 界面按同尺寸设计即可 1:1 铺满整屏、无黑边。
 * designHeight 缺省时按 16:10 推算，保持向后兼容。
 */
const DESIGN = {
  width: ${manifest.config.designWidth},
  height: ${manifest.config.designHeight || Math.round(manifest.config.designWidth * 0.625)}
}

/* ---------------- 渲染引擎 ---------------- */
const nodeData = new WeakMap()

function el(tag, attrs, children) {
  const n = { tag: tag, attrs: attrs || {}, children: children || [] }
  return n
}

/** 解析运行期标记串为节点树 */
function parse(html) {
  const doc = new DOMParser().parseFromString('<div>' + html + '</div>', 'text/html')
  return convert(doc.body.firstElementChild)
}

function convert(dom, depth) {
  if (!dom) {
    return { text: '' }
  }
  // 只处理元素节点与文本节点；注释（nodeType 8）、文档类型等一律跳过。
  // 模板里的 <!-- --> 说明注释会以 nodeType 8 出现，早期版本未过滤会导致
  // 读取 attributes 报 TypeError，这里显式放行。
  if (dom.nodeType !== 1) {
    if (dom.nodeType === 3) {
      return { text: dom.textContent }
    }
    return { text: '' }
  }

  // 用 getAttributeNames/getAttribute 读取属性：比 attributes 集合更稳，
  // 也避免在不同宿主环境下遇到 attributes 缺失导致的 TypeError。
  const attrs = {}
  const names = typeof dom.getAttributeNames === 'function' ? dom.getAttributeNames() : []
  for (let i = 0; i < names.length; i += 1) {
    attrs[names[i]] = dom.getAttribute(names[i])
  }

  const kids = dom.childNodes || []
  const children = []
  for (let i = 0; i < kids.length; i += 1) {
    children.push(convert(kids[i], (depth || 0) + 1))
  }

  return {
    tag: String(dom.tagName || 'div').toLowerCase(),
    attrs: attrs,
    children: children
  }
}

/** 取属性上的绑定值：data-bind / data-if / data-style / data-class 里是数据路径 */
function pickByPath(data, expr) {
  const parts = String(expr).trim().split('.')
  let cur = data
  for (let i = 0; i < parts.length; i += 1) {
    if (cur === null || cur === undefined) {
      return undefined
    }
    cur = cur[parts[i]]
  }
  return cur
}

function resolvePath(path, scope) {
  if (scope && Object.prototype.hasOwnProperty.call(scope, path)) {
    return scope[path]
  }
  if (path.indexOf('$item') === 0) {
    const rest = path.slice(5).replace(/^\\./, '')
    return rest ? pickByPath(scope.$item, rest) : scope.$item
  }
  if (path === '$index') {
    return scope.$index
  }
  return pickByPath(scope, path)
}

function renderNode(node, scope, out) {
  if (node.text !== undefined) {
    if (node.text.trim()) {
      out.push(document.createTextNode(node.text))
    }
    return
  }

  const attrs = node.attrs

  // data-if
  if (attrs['data-if'] !== undefined) {
    const v = resolvePath(attrs['data-if'], scope)
    if (!v) {
      return
    }
  }

  // data-each：把同一个元素按数组重复，不引入包裹元素（包裹元素会破坏
  // 父级 flex 布局，例如栅格与横向行）。
  // 关键点：递归时必须把 data-each 从节点上摘掉，否则会重复进入这一分支，
  // 造成无限递归（RangeError: Maximum call stack size exceeded）。
  if (attrs['data-each'] !== undefined && node.loopDone !== true) {
    const list = resolvePath(attrs['data-each'], scope)
    const arr = Array.isArray(list) ? list : []
    const clone = { tag: node.tag, attrs: attrs, children: node.children, loopDone: true }
    arr.forEach(function (item, i) {
      const inner = Object.create(scope)
      inner.$item = item
      inner.$index = i
      renderNode(clone, inner, out)
    })
    return
  }

  let tag = node.tag
  if (tag === 'each') {
    tag = 'div'
  }
  let dom
  if (tag === 'image' || tag === 'img') {
    dom = document.createElement('div')
  } else if (tag === 'input') {
    dom = document.createElement('div')
  } else {
    dom = document.createElement(tag)
  }

  Object.keys(attrs).forEach(function (k) {
    const v = attrs[k]
    /*
     * data-touch 走透传：留在 DOM 上（真机读得到），
     * 但实际的事件绑定在 rootEl 上统一做，见 bindInput()。
     */
    if (k === 'data-if' || k === 'data-each' || k === 'data-act' || k === 'data-tid' || k === 'data-touch') {
      return
    }
    if (k === 'data-bind') {
      return
    }
    if (k === 'data-style') {
      const sv = resolvePath(v, scope)
      if (sv) {
        dom.setAttribute('style', sv)
      }
      return
    }
    if (k === 'data-class') {
      const cv = resolvePath(v, scope)
      if (cv) {
        dom.className = (dom.className ? dom.className + ' ' : '') + cv
      }
      return
    }
    if (k === 'class') {
      dom.className = (dom.className ? dom.className + ' ' : '') + v
      return
    }
    if (k === 'scroll-y') {
      dom.style.overflowY = 'auto'
      return
    }
    dom.setAttribute(k, v)
  })

  // 文本绑定：{{expr}} 会被转成内嵌的 <b data-bind>
  node.children.forEach(function (c) {
    if (c.tag === 'b' && c.attrs['data-bind'] !== undefined) {
      const v = resolvePath(c.attrs['data-bind'], scope)
      dom.appendChild(document.createTextNode(v === undefined || v === null ? '' : String(v)))
    } else {
      renderNode(c, scope, { push: function (n) { dom.appendChild(n) } })
    }
  })

  if (attrs['data-act']) {
    /*
     * 触控屏上不需要手型光标，设为 none 与全局 cursor:none 保持一致。
     * （原先设的是 'pointer'，会在触屏上重新露出光标。）
     */
    dom.style.cursor = 'none'
    /*
     * 打一个真实落到 DOM 上的标记属性。
     *
     * 为什么需要：data-act / data-tid / data-style 这些在预览渲染时
     * **只进委托表、不写进 DOM**。于是「先 closest 找到可交互元素、
     * 再查委托表」这类写法在预览里必然失配 —— 表现为按下毫无反应，
     * 而真机上却是好的（真机走引擎自己的事件分发）。
     * 有了这个标记，两种环境下的命中判断才是同一套逻辑。
     *
     * 名字带 vg- 前缀，不会和引擎保留属性冲突。
     */
    dom.setAttribute('data-vg-hit', '1')
  }
  /*
   * tid 也是数据绑定（例如 tid="{{$item.uri}}"），必须求值后再登记；
   * 直接存原始表达式会让处理函数收到字面量 "$item.uri"，
   * 表现为「点了没反应」——这类静默失败很难排查，务必在这里解析。
   */
  const rawTid = attrs['data-tid']
  const tid = rawTid === undefined ? undefined : resolvePath(rawTid, scope)
  /*
   * data-touch：真机上是「按下即响应」的语义。
   * 这里先解析成方法名存进委托表，实际绑定在 rootEl 上统一做（见 bindInput）。
   */
  nodeData.set(dom, {
    act: attrs['data-act'],
    touch: attrs['data-touch'],
    tid: tid,
    scope: scope
  })
  out.push(dom)
}

/** 供自动化测试查询委托表：判断某个元素是否被登记为可交互 */
function debugMeta(node) {
  return nodeData.get(node) || null
}

/* ---------------- 页面实例 ---------------- */
const frame = document.getElementById('frame')
const rootEl = document.getElementById('root')
const toastEl = document.getElementById('toast')
const styleEls = {}

let current = null
let component = null
let data = null
let tree = null
// 包着 data 的 Proxy。测试要改数据必须走它，否则不会重渲染（见 __velaguard.patch 的说明）
let dataProxy = null

function showToast(message) {
  toastEl.textContent = message
  toastEl.classList.add('show')
  clearTimeout(showToast.t)
  showToast.t = setTimeout(function () {
    toastEl.classList.remove('show')
  }, 2000)
}

/** 供页面脚本使用的宿主桩件 */
function makeHost(pageKey) {
  return {
    router: {
      push: function (o) { go(o.uri) },
      replace: function (o) { go(o.uri) },
      back: function () { go('/') },
      clear: function () {}
    },
    prompt: {
      showToast: function (o) { showToast(o && o.message ? o.message : '') }
    },
    velaclaw: {
      ask: function (o) {
        // 浏览器预览没有端侧 AI Agent，统一走 fail 让页面切到本地指令模式
        setTimeout(function () {
          if (o && o.fail) { o.fail({}, 404) }
          if (o && o.complete) { o.complete() }
        }, 200)
      }
    },
    store: store,
    source: source
  }
}

function deepClone(o) {
  return JSON.parse(JSON.stringify(o))
}

function build(pageKey) {
  const page = PAGES[pageKey]
  if (!page) {
    return
  }
  current = pageKey

  // 样式只注入一次（构建期已作用域化到 [data-page="<页面名>"]）
  if (!styleEls[pageKey]) {
    const s = document.createElement('style')
    s.textContent = page.css
    document.head.appendChild(s)
    styleEls[pageKey] = s
  }

  // 编译脚本：import 已在构建期剥离，这里注入宿主桩件
  const host = makeHost(pageKey)
  /* eslint-disable no-new-func */
  const factory = new Function(
    'router', 'prompt', 'velaclaw', 'store', 'source',
    '"use strict";' + page.script
  )
  component = factory(host.router, host.prompt, host.velaclaw, host.store, host.source)

  data = deepClone(component.private || {})
  // 递归代理：页面直接改 this.xxx 也要能触发重渲染
  const proxy = new Proxy(data, {
    set: function (target, key, value) {
      target[key] = value
      queueRender()
      return true
    }
  })
  dataProxy = proxy
  component.data = proxy

  // 把方法绑到 data 上，this 指向代理，页面里 this.x = 1 即可生效
  Object.keys(component).forEach(function (k) {
    if (typeof component[k] === 'function') {
      proxy[k] = component[k].bind(proxy)
    }
  })

  if (typeof component.onInit === 'function') {
    component.onInit.call(proxy)
  }

  tree = parse(page.html)
  doRender()
  if (typeof component.onShow === 'function') {
    component.onShow.call(proxy)
  }

  // 事件委托
  bindInput()
  rootEl.setAttribute('data-page', pageKey)
  document.querySelectorAll('#pagelist button').forEach(function (b) {
    b.classList.toggle('on', b.dataset.page === pageKey)
  })
}

/**
 * 统一的事件委托（点击 + 触摸）。
 *
 * 为什么要区分：真机上 data-act 是「点击」，data-touch 是「按下」。
 * 「按住说话」这类按钮必须按下就有反馈 —— 手指抬起才响的按钮，
 * 在触屏上会让人以为没按到，从而反复按压。浏览器里等价的按下事件是
 * touchstart（无触摸设备时退回 mousedown），为了不让后续合成的 click
 * 再触发一次同一个处理函数，用 _touchHandledAt 记一下时间戳。
 *
 * ⚠️ 本文件整体被包在一个 JS 模板字符串里，注释里**不能出现反引号**，
 *    否则模板字符串会提前结束（构建直接语法报错，实测踩过）。
 */
let _touchHandledAt = 0

function findActNode(target) {
  let n = target
  while (n && n !== rootEl) {
    const meta = nodeData.get(n)
    if (meta && (meta.act || meta.touch)) {
      return { el: n, meta: meta }
    }
    n = n.parentNode
  }
  return null
}

function invokeAct(meta, which) {
  const name = which === 'touch' ? meta.touch : meta.act
  if (!name) {
    return false
  }
  const fn = component && component.data ? component.data[name] : null
  if (typeof fn !== 'function') {
    return false
  }
  fn({
    target: {
      attr: { tid: meta.tid },
      data: {}
    }
  })
  return true
}

function bindInput() {
  /*
   * 真实触摸：touchstart 命中 data-touch 的元素立刻处理。
   * 注意不 preventDefault —— 否则会连带禁掉该元素上的滚动；
   * 用时间戳而不是 preventDefault 来避免「按下 + 抬起的 click」双触发。
   *
   * ⚠️ 判断「可交互」必须用 data-vg-hit（renderNode 真正写进 DOM 的标记），
   *    不能用 closest('[data-act]')：预览渲染时 data-act 只进委托表、
   *    不落到 DOM 上，closest 永远匹配不到，按下就会毫无反应。
   */
  rootEl.ontouchstart = function (e) {
    const t = e.target
    if (t && t.closest && t.closest('[data-vg-hit]')) {
      const hit = findActNode(t)
      if (hit && invokeAct(hit.meta, 'touch')) {
        _touchHandledAt = Date.now()
      }
    }
  }

  /*
   * 无触摸设备（鼠标调试 / headless 测试）时，pointerdown 就是「按下」。
   * 用它把按住的手感也带进桌面浏览器，方便自动化验证。
   */
  rootEl.onpointerdown = function (e) {
    if (e.pointerType === 'touch' && Date.now() - _touchHandledAt < 1500) {
      return
    }
    const t = e.target
    if (t && t.closest && t.closest('[data-vg-hit]')) {
      const hit = findActNode(t)
      if (hit && invokeAct(hit.meta, 'touch')) {
        _touchHandledAt = Date.now()
      }
    }
  }

  rootEl.onclick = function (e) {
    // 按下时已经处理过：跳过这次 click，避免同一按触发两次
    if (Date.now() - _touchHandledAt < 1500) {
      return
    }
    const hit = findActNode(e.target)
    if (hit) {
      invokeAct(hit.meta, 'act')
    }
  }
}

let pending = false
function queueRender() {
  if (pending) {
    return
  }
  pending = true
  requestAnimationFrame(function () {
    pending = false
    doRender()
  })
}

/**
 * 重建前记录滚动位置，重建后还原。
 *
 * 为什么需要：doRender() 是**整棵 DOM 重建**（rootEl.textContent = ''），
 * 所以任何滚动容器的位置每帧都会归零 —— 用户看到的就是
 * 「聊天记录自己跳回顶部」。这是能直接感知的缺陷，必须处理。
 *
 * 按「可滚动元素的出现顺序」配对：重建后节点对象全换了，只能靠序号对应。
 *
 * ⚠️ 两条实测踩出来的规矩（别退回去）：
 *   1. **声明了 data-auto-bottom 的容器，不管当前有没有溢出都要进快照。**
 *      第一版只快照「已经能滚」的元素，于是「内容刚好撑出滚动条」那一次
 *      快照是空的 → restoreScroll 直接 return → 新消息进来后停在顶部不动。
 *      用户的原话就是「弹出新的文字后没有自动下滑」。
 *   2. 快照里要存「重建前是否贴底」，而不是让调用方事后猜。
 */
function snapshotScroll() {
  const out = []
  if (!rootEl) {
    return out
  }
  rootEl.querySelectorAll('*').forEach(function (el) {
    const overflow = el.scrollHeight > el.clientHeight + 2
    // 没溢出的 data-auto-bottom 容器也要记：它下一秒就可能因为新消息溢出
    if (!overflow && !el.hasAttribute('data-auto-bottom')) {
      return
    }
    out.push({
      top: el.scrollTop,
      // 没溢出时 gap 是负的，同样算「贴底」，这是新消息应当跟随的情形
      atBottom: (el.scrollHeight - el.scrollTop - el.clientHeight) < 24
    })
  })
  return out
}

function restoreScroll(snaps) {
  if (!rootEl || !snaps.length) {
    return
  }
  const now = []
  rootEl.querySelectorAll('*').forEach(function (el) {
    if (el.scrollHeight > el.clientHeight + 2 || el.hasAttribute('data-auto-bottom')) {
      now.push(el)
    }
  })
  for (let i = 0; i < snaps.length && i < now.length; i += 1) {
    const s = snaps[i]
    const el = now[i]
    /*
     * 声明了 data-auto-bottom 的容器（如会话记录 .chat）：
     * 重建前若贴着底部，就继续贴底 —— 新消息自然跟随下滚；
     * 用户主动往上翻时 atBottom 为 false，位置如实保留，不会被拽回去。
     */
    if (s.atBottom && el.hasAttribute('data-auto-bottom')) {
      el.scrollTop = el.scrollHeight
    } else {
      el.scrollTop = s.top
    }
  }
}

function doRender() {
  if (!tree || !data) {
    return
  }
  const snaps = snapshotScroll()
  const frag = document.createDocumentFragment()
  tree.children.forEach(function (c) {
    renderNode(c, data, { push: function (n) { frag.appendChild(n) } })
  })
  rootEl.textContent = ''
  rootEl.appendChild(frag)
  restoreScroll(snaps)
}

function go(uri) {
  let key = null
  Object.keys(PAGES).forEach(function (k) {
    if (PAGES[k].path === uri) {
      key = k
    }
  })
  if (!key && uri) {
    key = uri.replace(/^\\//, '')
    if (!PAGES[key]) {
      key = null
    }
  }
  if (key) {
    build(key)
  }
}

/* ---------------- 触屏行为加固 ---------------- */
/*
 * 触控屏上，长按会触发浏览器的右键菜单与文字选择；拖拽会选中
 * 整页文字并出现蓝色高亮。CSS 的 user-select 已处理大部分，
 * 这里再把默认行为与右键菜单显式拦掉，确保任何浏览器下都干净。
 */
document.addEventListener('contextmenu', function (e) { e.preventDefault() })
document.addEventListener('selectstart', function (e) { e.preventDefault() })
document.addEventListener('dragstart', function (e) { e.preventDefault() })

/* 供自动化测试查询：确认上述拦截已生效 */
window.__touchHardening = {
  userSelect: function () { return getComputedStyle(document.body).webkitUserSelect || getComputedStyle(document.body).userSelect },
  contextmenuBlocked: true
}

/* ---------------- 缩放 ---------------- */
let fit = true
// ?scale=1 固定为像素级 1:1（设计评审用）；默认铺满屏幕
if (/[?&]scale=1\b/.test(String(location.search || ''))) {
  fit = false
}
function resize() {
  const stage = document.getElementById('stage')
  /*
   * 铺满目标屏幕时不保留任何边距，否则会留下黑边。
   * 1:1 模式（?scale=1）才留一点呼吸空间，便于评审时看清边界。
   */
  const pad = fit ? 0 : 60
  const availW = stage.clientWidth - pad
  const availH = stage.clientHeight - pad
  /*
   * 缩放策略：**铺满目标屏幕**。
   *
   * 目标设备只有一种屏幕分辨率，界面应当铺满整屏、不留黑边，
   * 所以默认按窗口等比放大/缩小到填满可视区域（只用单一缩放系数，
   * 不会拉伸变形；多出的部分按 16:10 与屏幕比例差异居中留白）。
   *
   * 需要「像素级 1:1」评审时用 ?scale=1。
   */
  const scale = fit
    ? Math.min(availW / DESIGN.width, availH / DESIGN.height)
    : 1
  /*
   * 外框尺寸不写死：它只是给 #root 定位的容器，内容由 #root 的 transform 缩放。
   * 若把外框固定成设计尺寸，在小于设计的窗口里会因 overflow:hidden
   * 把缩放后的底部内容裁掉（表现为按钮点不到）。
   */
  frame.style.width = availW + 'px'
  frame.style.height = availH + 'px'
  frame.style.transform = 'scale(' + scale + ')'
  // 用像素值固定「屏幕」尺寸，避免弹性子项把内容撑高
  rootEl.style.width = DESIGN.width + 'px'
  rootEl.style.height = DESIGN.height + 'px'
  rootEl.style.maxHeight = DESIGN.height + 'px'
  document.getElementById('btn-fit').classList.toggle('on', fit)
  document.getElementById('btn-real').classList.toggle('on', !fit)
}
window.addEventListener('resize', resize)
document.getElementById('btn-fit').onclick = function () { fit = true; resize() }
document.getElementById('btn-real').onclick = function () { fit = false; resize() }

/* ---------------- 页面切换按钮 ---------------- */
const list = document.getElementById('pagelist')
Object.keys(PAGES).forEach(function (k) {
  const b = document.createElement('button')
  b.textContent = k
  b.dataset.page = k
  b.onclick = function () { build(k) }
  list.appendChild(b)
})

/**
 * 启动页：优先用 URL hash（允许 ./start.sh --page voice 直接进入某个 app），
 * 否则用 manifest 里声明的 entry。
 *
 * hash 里可能带多个标记，用逗号分隔，例如 start.sh 生成的 '#kiosk,voice'：
 *   kiosk = 隐藏工具栏（看板模式），voice = 直接进入语音助手页。
 * 所以必须按逗号分词逐个匹配，不能拿整串当页面名
 * （早期版本就是拿 "kiosk,voice" 当页面名，匹配不到，导致 --page 静默失效）。
 */
function initialPage() {
  const raw = decodeURIComponent(String(location.hash || '').replace(/^#/, '')).trim()
  if (!raw) {
    return '${manifest.router.entry}'
  }

  const tokens = raw.split(',').map(function (s) { return s.trim() }).filter(Boolean)

  // 逐个子串查找页面：支持 #voice（页面名）与 #/voice（路由路径）
  for (let i = 0; i < tokens.length; i += 1) {
    const t = tokens[i]
    if (t === 'kiosk') {
      continue
    }
    if (PAGES[t]) {
      return t
    }
    let found = null
    Object.keys(PAGES).forEach(function (k) {
      if (PAGES[k].path === t || PAGES[k].path === '/' + t) {
        found = k
      }
    })
    if (found) {
      return found
    }
  }

  // 兜底：整串当页面名再试一次（兼容旧的单值写法）
  if (PAGES[raw]) {
    return raw
  }
  return '${manifest.router.entry}'
}

build(initialPage())

/**
 * 看板模式：#kiosk 时隐藏顶部工具栏，让界面独占整屏。
 * 触控屏正式部署时由 start.sh 带上该参数；开发调试时不带，保留切页按钮。
 */
if (String(location.hash).indexOf('kiosk') >= 0) {
  document.body.classList.add('kiosk')
}

resize()
window.__velaguard = {
  build: build,
  store: store,
  source: source,
  getData: function () { return data },
  debugMeta: debugMeta,
  /**
   * 通过 Proxy 改数据（自动化测试专用）。
   *
   * ⚠️ 为什么不能直接改 getData() 拿到的东西：
   *   getData() 返回的是**原始对象**，不是包着它的 Proxy。往它上面赋值
   *   绕过了 set 陷阱 → 不会 queueRender → **数据变了但 DOM 不动**。
   *   这个坑很隐蔽：测试断言「数据里有 19 条」会通过，界面上却还是 1 条，
   *   于是「滚动没跳回顶部」之类的断言变成永远成立的空断言（实测踩过）。
   *   要触发真实渲染，就用这里的 patch。
   */
  patch: function (obj) {
    if (!dataProxy || !obj) {
      return 'NO_PROXY'
    }
    Object.keys(obj).forEach(function (k) { dataProxy[k] = obj[k] })
    return 'OK'
  },
  /** 切换数据源并重绘当前页面（供界面按钮与自动化测试使用） */
  setSource: function (name) {
    source.setMode(name)
    if (data && typeof data.refresh === 'function') {
      data.refresh()
    }
    return source.name
  },
  // 给自动化验证用：直接触发页面上的某个事件处理方法
  act: function (name, tid) {
    if (!data || typeof data[name] !== 'function') {
      return 'NO_HANDLER:' + name
    }
    data[name]({ target: { attr: { tid: tid === undefined ? '' : tid }, data: {} } })
    return 'OK'
  }
}
</script>
</body>
</html>
`

fs.mkdirSync(OUT_DIR, { recursive: true })
const outFile = path.join(OUT_DIR, 'index.html')
fs.writeFileSync(outFile, html)
console.log('预览页已生成：' + outFile)
console.log('页面数：' + Object.keys(pages).length + '，图标：' + Object.keys(iconFiles).length)
