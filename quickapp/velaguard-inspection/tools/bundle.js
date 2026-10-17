/**
 * 打包器：把 src/ 下的 ESM 源码打成一个自包含的单文件 bundle
 *
 * 用法：
 *   node tools/bundle.js --target browser --out build/bundle.browser.js
 *   node tools/bundle.js --target openvela --out build/bundle.js
 *
 * 为什么要自己打：
 *   目标环境有两个，还都不能用常见的打包器——
 *     · 浏览器预览：要一个能直接 <script> 引的单文件（离线、零依赖）
 *     · openvela 快应用：**不认 import 语句**，也不保证有模块加载器
 *   两边只共同拥有一件事：一个纯函数式的查表 `__mod(name)`。
 *   所以这里把所有模块转成「注册进一张表」的形式，
 *   页面源码里的 `import x from '../common/y.js'` 全部改写成 `__mod('y')`，
 *   源码本身一行都不用动，也不需要条件编译。
 *
 * 目标差异只有一处：openvela 版的 `@system.velaclaw` 必须写在编译产物里
 * （它只能出现在 app.ux 的脚本中）。
 */
const fs = require('fs')
const path = require('path')
const esm = require('./esm.js')

const ROOT = path.resolve(__dirname, '..')
const SRC = path.join(ROOT, 'src')

/* ------------------------------------------------------------------ *
 * 1. 收集模块
 * ------------------------------------------------------------------ */
function collect() {
  const modules = {}

  function add(name, relPath, kind) {
    const abs = path.join(SRC, relPath)
    if (!fs.existsSync(abs)) {
      throw new Error('模块不存在：' + abs)
    }
    modules[name] = {
      name: name,
      kind: kind,
      file: relPath,
      code: esm.toCjs(fs.readFileSync(abs, 'utf8'))
    }
  }

  /* common 下的模块：文件 basename 作为模块名（'store' / 'data' / ...） */
  const commonDir = path.join(SRC, 'common')
  fs.readdirSync(commonDir).forEach(function (f) {
    if (!/\.js$/.test(f)) { return }
    const name = f.replace(/\.js$/, '')
    add(name, path.join('common', f), 'common')
  })

  /* 页面模块：以文件名（Home / Dispatch / ...）作为模块名 */
  const pagesDir = path.join(SRC, 'pages')
  fs.readdirSync(pagesDir).forEach(function (f) {
    if (!/\.js$/.test(f)) { return }
    const name = f.replace(/\.js$/, '')
    add(name, path.join('pages', f), 'page')
  })

  add('app-shell', 'app-shell.js', 'shell')
  return modules
}

/* ------------------------------------------------------------------ *
 * 2. 改写 import：'../common/store.js' → __mod('store')；'./x.js' → __mod('x')
 * ------------------------------------------------------------------ */
function rewriteImports(code) {
  return code.replace(
    /(const\s+[A-Za-z_$][\w$]*\s*=\s*)__imp\(__req\((['"])([^'"]+)\2\)\)/g,
    function (m, head, quote, spec) {
      const base = spec.replace(/^.*\//, '').replace(/\.js$/, '')
      return head + '__imp(__mod(' + JSON.stringify(base) + '))'
    }
  )
}

/* ------------------------------------------------------------------ *
 * 3. 生成 bundle
 * ------------------------------------------------------------------ */
function build(target, outPath) {
  const modules = collect()
  const names = Object.keys(modules)

  const parts = []
  parts.push('/*')
  parts.push(' * VelaGuard bundle —— **自动生成，请勿手改**')
  parts.push(' *')
  parts.push(' * 由 tools/bundle.js 从 src/ 下的源码生成，目标：' + target)
  parts.push(' * 生成时间：' + new Date().toISOString())
  parts.push(' *')
  parts.push(' * 结构：所有模块注册进 __REG，用 __mod(name) 取用；')
  parts.push(' *      页面里的 import 已改写成 __mod(...)，因此本文件不依赖任何模块加载器。')
  parts.push(' */')
  parts.push('(function (global) {')
  parts.push("  'use strict';")
  parts.push('  var __REG = {};      /* name → { factory, exports, done } */')
  parts.push('  function __resolve(name) {')
  parts.push("    var r = __REG[name];")
  parts.push("    if (!r) { throw new Error('模块未注册：' + name); }")
  parts.push('    if (!r.done) {')
  parts.push('      /* 先标记再执行，循环依赖时不会无限递归 */')
  parts.push('      r.done = true;')
  parts.push('      r.factory(function (spec) {')
  parts.push('        return __mod(rawName(spec));')
  parts.push('      }, __imp, r, r.exports);')
  parts.push('    }')
  parts.push('    return r.exports;')
  parts.push('  }')
  parts.push('  function rawName(spec) {')
  parts.push('    return String(spec).replace(/^.*\\//, "").replace(/\\.js$/, "");')
  parts.push('  }')
  parts.push('  function __mod(name) { return __resolve(name); }')
  parts.push('  function __imp(ns) {')
  parts.push("    if (ns && Object.prototype.hasOwnProperty.call(ns, 'default') && ns.default !== undefined) {")
  parts.push('      return ns.default;')
  parts.push('    }')
  parts.push('    return ns;')
  parts.push('  }')
  parts.push('  /* 只登记工厂，不执行 —— 真正的求值推迟到第一次被取用。')
  parts.push('     早期版本在这里就立即执行所有模块，而模块是按名字母序跑的，')
  parts.push("     于是 agent 先跑、它需要的 store 还没注册，直接报\"模块未注册\"（白屏）。 */")
  parts.push('  function __def(name, fn) {')
  parts.push('    __REG[name] = { factory: fn, exports: {}, done: false };')
  parts.push('  }')
  parts.push('')
  parts.push('  /* ---------- 注册并执行所有模块 ---------- */')

  const pageEntries = []
  names.forEach(function (name) {
    const m = modules[name]
    const code = rewriteImports(m.code)
    parts.push('  __def(' + JSON.stringify(name) + ', function (__req, __imp, module, exports) {')
    parts.push(code)
    /*
     * 必须显式闭合模块函数体。
     * 模块的顶层 const/let 只能活在自己的作用域里；少了这一行，
     * 所有模块的声明会落到同一个作用域，一打包就
     * "Identifier 'xxx' has already been declared" → 整页白屏（踩过）。
     */
    parts.push('  });')
    parts.push('')
    if (m.kind === 'page') {
      pageEntries.push("      " + JSON.stringify(name) + ': __imp(__mod(' + JSON.stringify(name) + '))')
    }
  })

  /*
   * 外壳与页面模块一样，已经在上面的循环里 __def 过了。
   * 这里**只取用**、不再重复发射一遍（重复发射会让同一份代码出现两次）。
   * 惰性求值保证：外壳被取用时，它依赖的 router / store / data 都已经登记好了。
   */
  parts.push('  var __shell = __imp(__mod("app-shell"));')
  parts.push('')
  parts.push('  var __pages = {')
  parts.push(pageEntries.join(',\n'))
  parts.push('  };')
  parts.push('')

  /* ---------- 目标差异：openvela 版的 velaclaw 必须在编译产物里 import ---------- */
  if (target === 'openvela') {
    parts.push('  /* ---------- openvela：端侧 Agent 通道 ----------')
    parts.push('   * @system.velaclaw 只能出现在快应用的脚本里，所以写在这一层。')
    parts.push('   * 通道事实（取自竞赛分支源码，不是文档转述）：')
    parts.push('   *   IDL: promise<AskResponse> ask(AskParam)')
    parts.push('   *        AskResponse = { reply, extra_info, tool_calls: [{name, result}] }')
    parts.push('   *   传输: POSIX 消息队列 /velaclaw_qapp_in、/velaclaw_qapp_out')
    parts.push('   *   快应用侧**没有** @system.websocket，也没有让 Agent 调任意工具的通道。')
    parts.push('   */')
    parts.push("  var __velaclaw = null;")
    parts.push('  try {')
    parts.push("    __velaclaw = __req('@system.velaclaw');")
    parts.push('    __velaclaw = __imp(__velaclaw);')
    parts.push('  } catch (e) {')
    parts.push('    __velaclaw = null;')
    parts.push('  }')
    parts.push('  function __askAgent(query) {')
    parts.push('    return new Promise(function (resolve, reject) {')
    parts.push('      if (!__velaclaw || typeof __velaclaw.ask !== "function") {')
    parts.push("        reject(new Error('@system.velaclaw 不可用（固件未开 CONFIG_FEATURE_SYSTEM_VELACLAW）'));")
    parts.push('        return;')
    parts.push('      }')
    parts.push("      var timer = setTimeout(function () {")
    parts.push("        reject(new Error('端侧 Agent 超时未回复'));")
    parts.push('      }, 60000);')
    parts.push('      try {')
    parts.push('        __velaclaw.ask({')
    parts.push('          query: String(query),')
    parts.push('          success: function (res) {')
    parts.push('            clearTimeout(timer);')
    parts.push('            resolve(res || {});')
    parts.push('          },')
    parts.push('          fail: function (msg, code) {')
    parts.push('            clearTimeout(timer);')
    parts.push("            reject(new Error('端侧 Agent 返回失败：' + (msg || '') + ' code=' + (code || '')));")
    parts.push('          },')
    parts.push('          complete: function () { clearTimeout(timer); }')
    parts.push('        });')
    parts.push('      } catch (e2) {')
    parts.push('        clearTimeout(timer);')
    parts.push('        reject(e2);')
    parts.push('      }')
    parts.push('    });')
    parts.push('  }')
  } else {
    parts.push('  /* ---------- 浏览器预览：没有端侧 Agent，交给本地指令表兜底 ---------- */')
    parts.push('  function __askAgent() {')
    parts.push("    return Promise.reject(new Error('浏览器预览环境没有 @system.velaclaw'));")
    parts.push('  }')
  }

  parts.push('')
  parts.push('  /* ---------- 对外句柄 ---------- */')
  parts.push('  /* 一律走 __imp 解包，否则外部拿到的是命名空间而不是模块本身 */')
  parts.push('  global.VelaGuard = {')
  parts.push('    mod: function (name) { return __imp(__mod(name)); },')
  parts.push('    raw: __mod,')
  parts.push('    pages: __pages,')
  parts.push('    createApp: __shell.createApp,')
  parts.push('    askAgent: __askAgent,')
  parts.push('    data: __imp(__mod("data")),')
  parts.push('    store: __imp(__mod("store")),')
  parts.push('    agent: __imp(__mod("agent")),')
  parts.push('    ui: __imp(__mod("ui")),')
  parts.push('    router: __imp(__mod("router")),')
  parts.push('    tpl: __imp(__mod("tpl")),')
  parts.push('    map: __imp(__mod("map")),')
  parts.push('    baseCss: __imp(__mod("styles")).BASE_CSS')
  parts.push('  };')
  parts.push('})(typeof globalThis !== "undefined" ? globalThis : this);')
  parts.push('')

  const out = parts.join('\n')
  fs.mkdirSync(path.dirname(outPath), { recursive: true })
  fs.writeFileSync(outPath, out, 'utf8')
  return { path: outPath, size: fs.statSync(outPath).size, modules: names.length }
}

/* ------------------------------------------------------------------ */
const args = process.argv.slice(2)
function argOf(flag, dflt) {
  const i = args.indexOf(flag)
  return i >= 0 && args[i + 1] ? args[i + 1] : dflt
}

const target = argOf('--target', 'browser')
const dfltOut = target === 'openvela'
  ? path.join(ROOT, 'build', 'velaguard.bundle.js')
  : path.join(ROOT, 'build', 'bundle.browser.js')
const outPath = path.resolve(argOf('--out', dfltOut))

const r = build(target, outPath)
console.log('=== bundle (' + target + ') ===')
console.log('模块数 : ' + r.modules)
console.log('产物   : ' + r.path)
console.log('体积   : ' + (r.size / 1024).toFixed(1) + ' KB')
