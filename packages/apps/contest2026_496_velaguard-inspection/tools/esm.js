/**
 * 极小的 ESM 载入器（仅供 Node 侧测试与编译工具使用）
 *
 * 为什么要它：src/ 下的源码是给 openvela 快应用用的 ES Module 语法，
 * 而测试要在 Node 里跑**同一份源码**。这里只做语法层面的转换，
 * 不复制代码，避免出现"测试过了但源码不是那份"的假验证。
 *
 * 支持的语法子集（本工程实际用到的全部）：
 *   import X from './y.js'        → const X = __req('./y.js')
 *   export const / export function → 去掉 export 前缀
 *   export default {...}          → module.exports.default = {...}
 */
const fs = require('fs')
const path = require('path')

function toCjs(code) {
  let out = code
  /*
   * 默认导入要取 .default，但**只在模块真的有 default 导出时**才取。
   * 反例：store.js 只有命名导出，如果无条件取 .default 就会拿到 undefined。
   * 交给运行时的 __imp 判断，编译期不做假设。
   */
  out = out.replace(/^\s*import\s+([A-Za-z_$][\w$]*)\s+from\s+['"]([^'"]+)['"];?\s*$/gm,
    function (m, name, spec) {
      return 'const ' + name + ' = __imp(__req(' + JSON.stringify(spec) + '));'
    })
  /*
   * 去掉 export 前缀。**必须把 async 也算进去**：
   * 漏了 `export async function` 会让产物里残留一个 export 关键字，
   * 浏览器直接 SyntaxError、整页白屏（第一次打包就是这么挂的）。
   */
  out = out.replace(/^export\s+(async\s+function|function|const|let|var|class)\s+/gm, '$1 ')
  out = out.replace(/^export\s+default\s+/gm, 'module.exports.default = ')
  /* 兜底：任何仍然残留的行首 export 都去掉，宁可产物里少一个导出，
     也不要交给浏览器一个语法错误。 */
  out = out.replace(/^export\s+/gm, '')
  return out
}

/** 默认导入的解包规则：有 default 取 default，否则当命名空间用 */
function unwrapDefault(ns) {
  if (ns && Object.prototype.hasOwnProperty.call(ns, 'default') && ns.default !== undefined) {
    return ns.default
  }
  return ns
}

/**
 * 建一个针对某个 baseDir 的载入器。
 *
 * 模块名用相对路径（如 './store.js'）。解析规则：**相对发起导入的那个文件所在目录**，
 * 与真实 ESM 一致——否则 src/pages/X.js 里的 '../common/store.js' 会被解析到
 * baseDir/common/store.js 而不是 src/common/store.js（踩过）。
 * 找不到时再退一步用 baseDir，方便工具脚本从任意位置引用 src 下的模块。
 */
function makeLoader(baseDir) {
  const cache = {}

  function resolve(spec, fromDir) {
    const tries = []
    if (fromDir) { tries.push(path.resolve(fromDir, spec)) }
    tries.push(path.resolve(baseDir, spec))
    for (let i = 0; i < tries.length; i += 1) {
      if (fs.existsSync(tries[i])) { return tries[i] }
    }
    throw new Error('模块不存在：' + spec + '（试过 ' + tries.join(' , ') + '）')
  }

  function req(spec, fromDir) {
    const abs = resolve(spec, fromDir)
    if (cache[abs]) {
      return cache[abs].exports
    }
    const mod = { exports: {} }
    cache[abs] = mod
    const code = toCjs(fs.readFileSync(abs, 'utf8'))
    /* __req 带上"当前文件所在目录"，让嵌套的相对导入按真实规则解析 */
    const localReq = function (s) { return req(s, path.dirname(abs)) }
    const fn = new Function('__req', '__imp', 'module', 'exports', 'require', '__filename', code)
    fn(localReq, unwrapDefault, mod, mod.exports, require, abs)
    return mod.exports
  }

  /** 载入并自动解包 default（有 default 就返回 default，否则返回命名空间） */
  function value(spec, fromDir) {
    return unwrapDefault(req(spec, fromDir))
  }

  return { req: req, value: value }
}

module.exports = { toCjs: toCjs, makeLoader: makeLoader, unwrapDefault: unwrapDefault }
