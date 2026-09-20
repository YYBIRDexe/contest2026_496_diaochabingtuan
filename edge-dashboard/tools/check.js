'use strict'

/**
 * 工程自检：在不安装 AIoT-IDE 的前提下，尽量提前发现低级错误。
 *
 * 检查项：
 *   1. manifest.json 可解析，router.pages 每一项都有对应的 pages/<名称>/index.ux
 *   2. 每个 .ux 文件都有 template / style / script 三段
 *   3. template 段落里的标签成对闭合（自闭合标签与已知单标签除外）
 *   4. script 段落的 JavaScript 语法可解析
 *   5. 每个 .ux 引用的 style 类名都在本文件 <style> 中定义过
 *   6. manifest 与桌面注册表引用的图标文件都存在
 *
 * 用法：node tools/check.js
 */

const fs = require('fs')
const path = require('path')
const vm = require('vm')

const ROOT = path.join(__dirname, '..')
const SRC = path.join(ROOT, 'src')

let errors = 0
let warnings = 0

function fail(msg) {
  errors += 1
  console.log('  ✗ ' + msg)
}

function warn(msg) {
  warnings += 1
  console.log('  ! ' + msg)
}

function ok(msg) {
  console.log('  ✓ ' + msg)
}

function read(p) {
  return fs.readFileSync(p, 'utf8')
}

/* ------------------------------------------------------------------ *
 * 1. manifest.json
 * ------------------------------------------------------------------ */
console.log('\n[1] manifest.json')

const manifestPath = path.join(SRC, 'manifest.json')
let manifest = null
try {
  manifest = JSON.parse(read(manifestPath))
  ok('JSON 解析通过')
} catch (e) {
  fail('manifest.json 解析失败：' + e.message)
}

const uxFiles = []

if (manifest) {
  const required = ['package', 'name', 'icon', 'versionCode', 'config', 'router']
  required.forEach(function (k) {
    if (manifest[k] === undefined) {
      fail('缺少必填字段 ' + k)
    }
  })

  if (manifest.router && manifest.router.pages) {
    const entry = manifest.router.entry
    if (!manifest.router.pages[entry]) {
      fail('router.entry「' + entry + '」不在 router.pages 中')
    }
    Object.keys(manifest.router.pages).forEach(function (name) {
      const ux = path.join(SRC, 'pages', name, 'index.ux')
      if (!fs.existsSync(ux)) {
        fail('页面 ' + name + ' 缺少 ' + path.relative(ROOT, ux))
      } else {
        uxFiles.push(ux)
      }
      const comp = manifest.router.pages[name].component
      if (comp !== 'index') {
        warn('页面 ' + name + ' 的 component 为「' + comp + '」，请确认文件名为 ' + comp + '.ux')
      }
    })
  }
  ok('共声明 ' + (manifest.router && manifest.router.pages
    ? Object.keys(manifest.router.pages).length
    : 0) + ' 个页面路由')
}

/* ------------------------------------------------------------------ *
 * 2~5. 逐个 .ux 检查
 * ------------------------------------------------------------------ */
console.log('\n[2] .ux 文件结构')

// Vela 的 void / 自闭合标签
const VOID_TAGS = ['image', 'input', 'slider', 'progress', 'switch', 'canvas', 'web', 'video', 'qrcode']

function extract(ux, tag) {
  const re = new RegExp('<' + tag + '>([\\s\\S]*?)</' + tag + '>')
  const m = ux.match(re)
  return m ? m[1] : null
}

uxFiles.forEach(function (file) {
  const rel = path.relative(ROOT, file)
  const ux = read(file)

  const tpl = extract(ux, 'template')
  const sty = extract(ux, 'style')
  const scr = extract(ux, 'script')

  if (tpl === null) {
    fail(rel + ' 缺少 <template>')
  }
  if (sty === null) {
    fail(rel + ' 缺少 <style>')
  }
  if (scr === null) {
    fail(rel + ' 缺少 <script>')
  }
  if (tpl === null || sty === null || scr === null) {
    return
  }

  // --- 3. 标签闭合 ---
  const tagRe = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:[^>"']|"[^"]*"|'[^']*')*?)(\/?)>/g
  const stack = []
  let m
  let rootCount = 0
  while ((m = tagRe.exec(tpl)) !== null) {
    const closing = m[1] === '/'
    const name = m[2]
    const selfClose = m[4] === '/'
    if (closing) {
      const top = stack.pop()
      if (top !== name) {
        fail(rel + ' 标签不匹配：</' + name + '> 对应的是 <' + (top || '空') + '>')
      }
    } else if (selfClose || VOID_TAGS.indexOf(name) >= 0) {
      if (stack.length === 0) {
        rootCount += 1
      }
    } else {
      if (stack.length === 0) {
        rootCount += 1
      }
      stack.push(name)
    }
  }
  if (stack.length > 0) {
    fail(rel + ' 有未闭合标签：<' + stack.join('>, <') + '>')
  }
  if (rootCount !== 1) {
    fail(rel + ' template 必须只有一个根节点，当前检测到 ' + rootCount + ' 个顶层节点')
  }

  // --- 4. script 语法 ---
  try {
    // 用模块目标解析，支持 import / export
    new vm.SourceTextModule(scr, { identifier: rel })
    ok(rel + '  script 语法通过')
  } catch (e) {
    if (e instanceof SyntaxError) {
      fail(rel + '  script 语法错误：' + e.message)
    } else {
      // 运行环境不支持 SourceTextModule，退化为函数解析
      try {
        new vm.Script('(function(){' + scr.replace(/^\s*(import|export)[^\n]*$/gm, '') + '})')
        ok(rel + '  script 语法通过（降级校验）')
      } catch (e2) {
        fail(rel + '  script 语法错误：' + e2.message)
      }
    }
  }

  // --- 5. class 名是否都有定义 ---
  const defined = {}
  const classDefRe = /\.([a-zA-Z][a-zA-Z0-9_-]*)\s*(?=[,{:])/g
  let cm
  while ((cm = classDefRe.exec(sty)) !== null) {
    defined[cm[1]] = true
  }

  const used = {}
  const classAttrRe = /class\s*=\s*"([^"]*)"/g
  while ((cm = classAttrRe.exec(tpl)) !== null) {
    cm[1].split(/\s+/).forEach(function (c) {
      if (c) {
        used[c] = true
      }
    })
  }

  const missing = Object.keys(used).filter(function (c) {
    return !defined[c]
  })
  if (missing.length > 0) {
    fail(rel + ' 使用了未定义的 class：' + missing.join(', '))
  } else {
    ok(rel + '  style 类名完整（' + Object.keys(used).length + ' 个）')
  }

  const unused = Object.keys(defined).filter(function (c) {
    return !used[c]
  })
  if (unused.length > 0) {
    warn(rel + ' 有未被使用的 class：' + unused.join(', '))
  }
})

/* ------------------------------------------------------------------ *
 * 6. 资源文件与路由一致性
 * ------------------------------------------------------------------ */
console.log('\n[3] 资源与路由一致性')

const commonDir = path.join(SRC, 'common')
function checkAsset(iconPath, label) {
  if (!iconPath) {
    return
  }
  const p = path.join(SRC, iconPath.replace(/^\//, ''))
  if (fs.existsSync(p)) {
    ok(label + ' → ' + iconPath)
  } else {
    fail(label + ' 引用的资源不存在：' + iconPath)
  }
}

if (manifest) {
  checkAsset(manifest.icon, 'manifest.icon')
}

;['logo.png', 'icon-voice.png', 'icon-dispatch.png', 'icon-zones.png', 'icon-records.png', 'icon-system.png']
  .forEach(function (f) {
    const p = path.join(commonDir, f)
    if (!fs.existsSync(p)) {
      fail('缺少图标 ' + f + '（请运行 node tools/make-icons.js）')
    }
  })

// store.js 是否可解析
try {
  new vm.SourceTextModule(read(path.join(commonDir, 'store.js')), { identifier: 'store.js' })
  ok('common/store.js 语法通过')
} catch (e) {
  fail('common/store.js 语法错误：' + e.message)
}

/* ------------------------------------------------------------------ *
 * 7. 桌面磁贴与路由必须对得上
 *    否则点了磁贴会跳到一个不存在的页面
 * ------------------------------------------------------------------ */
const homePath = path.join(SRC, 'pages', 'Home', 'index.ux')
if (fs.existsSync(homePath) && manifest && manifest.router) {
  const home = read(homePath)
  const declared = {}
  Object.keys(manifest.router.pages).forEach(function (name) {
    declared[manifest.router.pages[name].path || '/' + name] = name
  })

  // 抓取 appRegistry 里的 uri 字段
  const uris = []
  const uriRe = /uri:\s*'([^']+)'/g
  let um
  while ((um = uriRe.exec(home)) !== null) {
    uris.push(um[1])
  }

  const bad = uris.filter(function (u) {
    return !declared[u]
  })
  if (bad.length > 0) {
    fail('桌面磁贴指向了未声明的路由：' + bad.join(', '))
  } else {
    ok('桌面 ' + uris.length + ' 个磁贴的目标路由均已声明')
  }

  // 每个页面里的 router.push / tid 跳转也应能对上
  uxFiles.forEach(function (file) {
    const rel = path.relative(ROOT, file)
    const body = read(file)
    const pushed = []
    const pRe = /router\.push\(\s*\{\s*uri:\s*'([^']+)'/g
    let pm
    while ((pm = pRe.exec(body)) !== null) {
      pushed.push(pm[1])
    }
    const missing = pushed.filter(function (u) {
      return !declared[u]
    })
    if (missing.length > 0) {
      fail(rel + ' 中 router.push 指向未声明路由：' + missing.join(', '))
    }
  })
}

/* ------------------------------------------------------------------ *
 * 汇总
 * ------------------------------------------------------------------ */
console.log('\n─────────────────────────────')
console.log('检查完成：' + uxFiles.length + ' 个页面，' + errors + ' 个错误，' + warnings + ' 个提示')
process.exit(errors > 0 ? 1 : 0)
