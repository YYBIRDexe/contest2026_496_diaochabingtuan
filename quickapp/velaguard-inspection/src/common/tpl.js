/**
 * VelaGuard · 极简模板引擎（数据 → HTML 字符串）
 *
 * 为什么不用 .ux 的声明式模板 + 框架级重渲染：
 *   那套要求在 openvela 的真快应用运行时里跑，而这个工程还要在
 *   Windows 浏览器里预览、在 Node 里单测。改成「渲染成字符串」后，
 *   同一份模板只依赖一个**纯函数**，三处行为完全一致，也就能被断言。
 *
 * 语法（够用就好，绝不扩张）：
 *   {{expr}}            插值，**默认 HTML 转义**
 *   {{{expr}}}          插值，不转义（只给已经自己拼好的 SVG 用）
 *   {{if:cond}} … {{/if}}                 条件块
 *   {{if:cond}} … {{else}} … {{/if}}      条件块带 else
 *   {{each:list}} … {{/each}}             循环，循环体里可用 $item / $index
 *
 * 块可以任意嵌套，`if`/`each` 都可以带序号（`{{if1:…}}{{/if1}}`）以便配对更直观。
 *
 * ------------------------------------------------------------------ *
 * 实现要点（踩过的坑，别改回去）
 *
 * 渲染必须是**递归**的：在**当前这一层**找块，遇到 each 就把循环体
 * 「带着 $item 再渲染一遍」，遇到 if 就按条件决定展开哪一支。
 *
 * 早期版本是"整体扫描、反复展开最内层块"的扁平算法，必然出错：
 *   模板 {{each:l}}{{if:$item.ok}}O{{/if}}{{/each}}
 *   里的 if 在 each 提供 $item **之前**就被求值了，条件为假 → 整块被吃掉。
 *   表现就是"循环里嵌的条件/循环永远不显示"，而且外层 each 越深越明显。
 * 递归写法从结构上避免了这个问题：内层块只在拿到 $item 的上下文里才被渲染。
 */

/** HTML 转义 */
export function escapeHtml(s) {
  if (s === undefined || s === null) {
    return ''
  }
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 表达式求值。出错不抛，返回空串并把错误记进 ctx.__errors（测试据此发现拼错的名字） */
function evaluate(expr, ctx) {
  try {
    const fn = new Function('__c', 'with (__c) { return (' + expr + '); }')
    const v = fn(ctx)
    return v === undefined || v === null ? '' : v
  } catch (e) {
    if (ctx && ctx.__errors && ctx.__errors.push) {
      ctx.__errors.push({ expr: expr, message: e && e.message ? e.message : String(e) })
    }
    return ''
  }
}

/* ------------------------------------------------------------------ *
 * 词法：把模板切成「文本 / 块开关」，并算出每个块配对的闭合标签
 * ------------------------------------------------------------------ */
const TOKEN_RE = /\{\{(if\d*|each\d*):([^}]*)\}\}|\{\{\/(if\d*|each\d*)\}\}/g

function tokenize(tpl) {
  const tokens = []
  TOKEN_RE.lastIndex = 0
  let m
  while ((m = TOKEN_RE.exec(tpl)) !== null) {
    if (m[1] !== undefined) {
      tokens.push({ kind: 'open', tag: m[1], arg: m[2].trim(), start: m.index, end: m.index + m[0].length })
    } else {
      tokens.push({ kind: 'close', tag: m[3], start: m.index, end: m.index + m[0].length })
    }
  }
  /* 栈配对：给每个 open 记下它对应的 close 下标 */
  const stack = []
  for (let i = 0; i < tokens.length; i += 1) {
    const tk = tokens[i]
    if (tk.kind === 'open') {
      stack.push(tk)
      continue
    }
    let at = -1
    for (let j = stack.length - 1; j >= 0; j -= 1) {
      if (stack[j].tag === tk.tag) { at = j; break }
    }
    if (at < 0) {
      continue
    }
    stack[at].pairIndex = i
    stack.splice(at, 1)
  }
  return tokens
}

/** 渲染一段模板（在当前 ctx 下） */
function renderSequence(tpl, ctx) {
  const tokens = tokenize(tpl)
  let out = ''
  let pos = 0
  let i = 0

  while (i < tokens.length) {
    const tk = tokens[i]

    if (tk.kind === 'close' || tk.pairIndex === undefined) {
      /* 孤立/未配对的标签：原样当文本输出，便于测试发现写错 */
      out += interpolate(tpl.slice(pos, tk.end), ctx)
      pos = tk.end
      i += 1
      continue
    }

    /* 标签之前的普通文本 */
    out += interpolate(tpl.slice(pos, tk.start), ctx)

    const bodyStart = tk.end
    const bodyEnd = tokens[tk.pairIndex].start
    const body = tpl.slice(bodyStart, bodyEnd)

    if (tk.tag.indexOf('each') === 0) {
      const list = evaluate(tk.arg, ctx)
      if (list && typeof list.length === 'number') {
        const parts = []
        for (let k = 0; k < list.length; k += 1) {
          /* 每轮用一个继承自 ctx 的子上下文，挂上 $item / $index */
          const sub = Object.create(ctx || null)
          sub.$item = list[k]
          sub.$index = k
          sub.__errors = ctx ? ctx.__errors : []
          parts.push(renderSequence(body, sub))
        }
        out += parts.join('')
      }
    } else {
      const elseTag = '{{else}}'
      const eIdx = body.indexOf(elseTag)
      const truthy = !!evaluate(tk.arg, ctx)
      if (eIdx >= 0) {
        out += renderSequence(truthy ? body.slice(0, eIdx) : body.slice(eIdx + elseTag.length), ctx)
      } else if (truthy) {
        out += renderSequence(body, ctx)
      }
    }

    pos = tokens[tk.pairIndex].end
    i = tk.pairIndex + 1
  }

  out += interpolate(tpl.slice(pos), ctx)
  return out
}

/** 把一段纯文本里的 {{ }} / {{{ }}} 求值掉 */
function interpolate(text, ctx) {
  if (text.indexOf('{{') < 0) {
    return text
  }
  let out = text.replace(/\{\{\{([^}]+)\}\}\}/g, function (m, expr) {
    const v = evaluate(expr.trim(), ctx)
    return v === '' ? '' : String(v)
  })
  out = out.replace(/\{\{([^}]+)\}\}/g, function (m, expr) {
    const v = evaluate(expr.trim(), ctx)
    return v === '' ? '' : escapeHtml(v)
  })
  return out
}

/**
 * 渲染模板。
 * @param {string} tpl  模板串
 * @param {object} ctx  数据对象（页面的 data() 结果，可再挂辅助函数）
 * @returns {string} HTML
 */
export function render(tpl, ctx) {
  const data = ctx || {}
  if (!data.__errors) {
    data.__errors = []
  }
  return renderSequence(String(tpl), data)
}

/** 检查模板块是否配对——编译期就能发现问题，不留到运行时 */
export function checkTemplate(tpl) {
  const problems = []
  const tokens = tokenize(String(tpl))
  const stack = []
  for (let i = 0; i < tokens.length; i += 1) {
    const tk = tokens[i]
    if (tk.kind === 'open') {
      stack.push(tk)
    } else {
      let at = -1
      for (let j = stack.length - 1; j >= 0; j -= 1) {
        if (stack[j].tag === tk.tag) { at = j; break }
      }
      if (at < 0) {
        problems.push('多余的闭合标签：{{/' + tk.tag + '}}')
      } else {
        stack.splice(at, 1)
      }
    }
  }
  for (let i = 0; i < stack.length; i += 1) {
    problems.push('未闭合的块：{{' + stack[i].tag + ':' + stack[i].arg + '}}')
  }
  const open3 = tpl.match(/\{\{\{/g)
  const close3 = tpl.match(/\}\}\}/g)
  if ((open3 ? open3.length : 0) !== (close3 ? close3.length : 0)) {
    problems.push('{{{ }}} 数量不匹配')
  }
  return problems
}

export default { render: render, escapeHtml: escapeHtml, checkTemplate: checkTemplate }
