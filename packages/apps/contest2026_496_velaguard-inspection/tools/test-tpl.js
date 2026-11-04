/**
 * 模板引擎单测
 * 用法：node tools/test-tpl.js
 *
 * 模板引擎是"一处出错、六个页面全崩"的地方，所以它必须在写页面之前就有测试。
 */
const path = require('path')
const esm = require('./esm.js')

const COMMON = path.resolve(__dirname, '..', 'src', 'common')
const tpl = esm.makeLoader(COMMON).value('./tpl.js')

let pass = 0
let fail = 0
function ok(name, cond, extra) {
  if (cond) { pass += 1; console.log('  ok   ' + name) } else {
    fail += 1; console.log('  FAIL ' + name + (extra ? '  → ' + extra : ''))
  }
}
function eq(name, a, b) {
  ok(name, a === b, 'got ' + JSON.stringify(a) + ', want ' + JSON.stringify(b))
}

console.log('=== tpl.js 单测 ===')

/* ---------- 1. 插值 ---------- */
eq('普通插值', tpl.render('A={{a}}', { a: 'x' }), 'A=x')
eq('数字插值', tpl.render('N={{n}}', { n: 42 }), 'N=42')
eq('undefined 变空串', tpl.render('[{{nope}}]', {}), '[]')
eq('表达式可算', tpl.render('{{a + b}}', { a: 1, b: 2 }), '3')
eq('可调函数', tpl.render('{{f(x)}}', { x: 'q', f: function (v) { return 'F:' + v } }), 'F:q')
eq('可读嵌套属性', tpl.render('{{o.k}}', { o: { k: 'v' } }), 'v')

/* ---------- 2. 默认转义（安全底线） ---------- */
eq('默认转义尖括号', tpl.render('{{a}}', { a: '<b>' }), '&lt;b&gt;')
eq('默认转义引号', tpl.render('{{a}}', { a: '"x"' }), '&quot;x&quot;')
eq('默认转义单引号', tpl.render('{{a}}', { a: "'x'" }), '&#39;x&#39;')
eq('默认转义 &', tpl.render('{{a}}', { a: 'a&b' }), 'a&amp;b')
eq('原始插值不转义', tpl.render('{{{a}}}', { a: '<b>ok</b>' }), '<b>ok</b>')

/* ---------- 3. 条件块 ---------- */
eq('if 真', tpl.render('{{if:x}}YES{{/if}}', { x: true }), 'YES')
eq('if 假', tpl.render('{{if:x}}YES{{/if}}', { x: false }), '')
eq('if 空串为假', tpl.render('{{if:x}}YES{{/if}}', { x: '' }), '')
eq('if 数字 0 为假', tpl.render('{{if:x}}YES{{/if}}', { x: 0 }), '')
eq('if 非空串为真', tpl.render('{{if:x}}YES{{/if}}', { x: 'a' }), 'YES')
eq('if-else 真', tpl.render('{{if:x}}A{{else}}B{{/if}}', { x: 1 }), 'A')
eq('if-else 假', tpl.render('{{if:x}}A{{else}}B{{/if}}', { x: 0 }), 'B')
eq('if 含表达式', tpl.render('{{if:n > 2}}big{{/if}}', { n: 5 }), 'big')

/* ---------- 4. 循环 ---------- */
eq('each 基本', tpl.render('{{each:list}}[{{$item}}]{{/each}}', { list: ['a', 'b'] }), '[a][b]')
eq('each 空列表', tpl.render('{{each:list}}[{{$item}}]{{/each}}', { list: [] }), '')
eq('each 用 $index', tpl.render('{{each:l}}{{$index}}:{{$item}} {{/each}}', { l: ['x', 'y'] }),
  '0:x 1:y ')
eq('each 读对象字段', tpl.render('{{each:l}}{{h($item.n)}}{{/each}}',
  { l: [{ n: 'a' }, { n: 'b' }], h: function (v) { return v.toUpperCase() } }), 'AB')
eq('each 里能用外层变量', tpl.render('{{each:l}}{{p}}{{$item}}{{/each}}',
  { l: [1, 2], p: '#' }), '#1#2')
eq('each 里的值也转义', tpl.render('{{each:l}}{{$item}}{{/each}}', { l: ['<i>'] }), '&lt;i&gt;')

/* ---------- 5. 嵌套 ---------- */
eq('if 里套 each', tpl.render('{{if:on}}{{each:l}}{{$item}}{{/each}}{{/if}}',
  { on: true, l: ['a', 'b'] }), 'ab')
eq('each 里套条件（带序号标签）',
  tpl.render('{{each:l}}{{if1:$item.ok}}O{{/if1}}{{/each}}',
    { l: [{ ok: true }, { ok: false }] }),
  'O')
eq('两层 each', tpl.render(
  '{{each:rows}}{{each1:$item.cols}}{{$item}}{{/each1}}|{{/each}}',
  { rows: [{ cols: [1, 2] }, { cols: [3] }] }),
  '12|3|')
eq('if 里套 if（带序号标签）',
  tpl.render('{{if:a}}{{if1:b}}AB{{/if1}}{{/if}}', { a: 1, b: 1 }), 'AB')

/* ---------- 6. 未闭合与错误表达式不静默 ---------- */
const errs = []
const out = tpl.render('{{nosuch.field}}', { __errors: errs })
eq('错误表达式输出空串', out, '')
ok('错误表达式被记录', errs.length === 1, JSON.stringify(errs))

const probs = tpl.checkTemplate('{{if:a}}x')
ok('checkTemplate 抓到未闭合', probs.length > 0, JSON.stringify(probs))
eq('checkTemplate 对合法模板返回空', tpl.checkTemplate('{{if:a}}x{{/if}}{{each:l}}{{$item}}{{/each}}').length, 0)

/* ---------- 7. 真实片段：页面里要用的那种嵌套 ---------- */
const ctx = {
  zones: [
    { id: 'Z1', name: '入口大厅', statusText: '已完成', color: '#3DDC84', progress: 100, taskId: 'T-1', detail: 'ok' },
    { id: 'Z2', name: '主通道', statusText: '进行中', color: '#4DA3FF', progress: 40, taskId: 'T-2', detail: 'go' }
  ]
}
const html = tpl.render(
  '{{each:zones}}<div class="z">{{$item.name}}·{{$item.statusText}}' +
  '{{if1:$item.progress > 50}} 已过半{{/if1}}' +
  '{{if1:$item.taskId}} [{{$item.taskId}}]{{/if1}}</div>{{/each}}', ctx)
ok('真实片段渲染正确',
  html.indexOf('入口大厅·已完成 已过半 [T-1]') >= 0 &&
  html.indexOf('主通道·进行中 [T-2]') >= 0, html)
ok('未过半的区域不显示"已过半"', html.indexOf('主通道·进行中 已过半') < 0, html)

/* 循环里套循环 + 条件（巡检记录页要用的三层结构） */
const deep = tpl.render(
  '{{each:recs}}<h>{{$item.round}}' +
  '{{each1:$item.zones}}<s>{{$item.name}}' +
  '{{if2:$item.result !== "done"}}!{{/if2}}' +
  '</s>{{/each1}}</h>{{/each}}',
  { recs: [{ round: '第1轮', zones: [{ name: 'A', result: 'done' }, { name: 'B', result: 'blocked' }] }] })
ok('三层嵌套（each>each>if）正确',
  deep.indexOf('<h>第1轮<s>A</s><s>B!</s></h>') >= 0, deep)

console.log('')
console.log('结果：' + pass + ' 通过，' + fail + ' 失败')
process.exit(fail === 0 ? 0 : 1)
