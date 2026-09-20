"use strict"

/**
 * 检查产物里语音助手的关键实现是否就位，以及降级路径是否完整。
 *
 * 为什么单独写：产物是单行压缩文件，grep 输出会被截断，肉眼核不准。
 *
 * 两个检查对象，别搞混：
 *   h  = preview/index.html（构建产物）—— 查行为与话术
 *   ux = src/pages/VoiceAssistant/index.ux（源码）—— 查模板属性
 * 模板上的 data-touch / data-act 这类属性**不会出现在产物里**
 * （构建期只把它们登记进委托表），只有源码里能看到。
 *
 * 用法：node tools/check-voice.js
 */

const fs = require("fs")
const path = require("path")

const FILE = path.join(__dirname, "..", "preview", "index.html")
const h = fs.readFileSync(FILE, "utf8")
const UX_FILE = path.join(__dirname, "..", "src", "pages", "VoiceAssistant", "index.ux")
const ux = fs.readFileSync(UX_FILE, "utf8")

let pass = 0
let fail = 0

function check(name, cond, detail) {
  if (cond) { pass += 1; console.log("  \u2713 " + name) }
  else { fail += 1; console.log("  \u2717 " + name + (detail ? "  → " + detail : "")) }
}

function count(s) {
  return h.split(s).length - 1
}

/**
 * 去掉构建产物里的注释后再匹配（模板注释 + JS 注释都要去掉）。
 *
 * 为什么要这么绕：源码注释里会提到旧文案（例如解释「按住说话」这个交互
 * 为什么改掉），那条注释本身也会被构建进产物。若不去掉，检查会把这些
 * 说明文字当成「界面还在用这个词」，得到假失败 —— 实际踩过。
 */
const hNoComment = h
  .replace(/<!--[\s\S]*?-->/g, "")
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "")

function countUI(s) {
  return hNoComment.split(s).length - 1
}

console.log("=== 语音助手产物检查 ===\n")

/* 1. 语音服务接入 */
console.log("[1] 语音服务接入")
check("引用本机语音服务 127.0.0.1:8124", count("127.0.0.1:8124") >= 1)
check("调用 /api/voice/talk 触发设备完整语音链路", count("/api/voice/talk") >= 1)
check("调用 /api/voice/state 查服务状态", count("/api/voice/state") >= 1)
check("调用 /api/record 本地 vosk 兜底", count("/api/record") >= 1)
check("调用 /api/beep 提示音", count("/api/beep") >= 1)
/* 两段式：第二次按下必须能真正把录音停掉，所以要分开的两个端点 */
check("调用 /api/voice/start 开始录音（两段式第一段）", count("/api/voice/start") >= 1)
check("调用 /api/voice/stop 立即结束录音（两段式第二段）", count("/api/voice/stop") >= 1)

/* 2. 降级路径（服务缺失 / 设备服务未运行时要给明确原因，不能假装成功） */
console.log("\n[2] 降级路径")
check("服务不可用时给出明确原因", h.indexOf("语音服务未启动") >= 0)
check("设备语音服务未运行时如实提示", h.indexOf("设备语音服务未运行") >= 0)
check("失败时把原因显示出来", h.indexOf("没成功：") >= 0)
check("老版本桥（无 start 端点）退回 talk", h.indexOf("r.status === 404") >= 0)

/* 3. 说话按钮：按一下开始、再按一下结束（触屏上长按会被判成滑动，不能按住） */
console.log("\n[3] 说话按钮交互")
check("按钮文案已改为「说话」", h.indexOf("micText: '说话'") >= 0 ||
  h.indexOf("micText: \\'说话\\'") >= 0)
check("顶栏/快捷坞不再有「按住说话」", countUI("按住说话") === 0,
  "界面上仍有 " + countUI("按住说话") + " 处")
check("第一次按下即开始（voiceStart）", h.indexOf("voiceStart()") >= 0)
check("第二次按下立即结束（voiceStop）", h.indexOf("voiceStop()") >= 0)
/* 模板属性只在源码里，见文件头的说明 */
check("按键走「按下即响应」（data-touch）", ux.indexOf('data-touch="onMic"') >= 0,
  'src/pages/VoiceAssistant/index.ux 里没有 data-touch="onMic"')
check("会话区带 id 供脚本贴底", ux.indexOf('id="chatList"') >= 0)
check("结束中显示「识别中」而不是假的听状态", h.indexOf("'识别中'") >= 0)
check("区分「说完自动结束」与「手按结束」", h.indexOf("vad-auto") >= 0)

/* 3. 话术：不能出现用户看不懂或误导的说法 */
console.log("\n[4] 话术准确性")
check("已移除「串口控制台执行 ai_agent」", count("串口控制台执行") === 0,
  "count=" + count("串口控制台执行"))
check("已移除「外部 AI 不可用」", count("外部 AI 不可用") === 0,
  "count=" + count("外部 AI 不可用"))
check("保留本地指令模式标识", h.indexOf("本地指令模式") >= 0)

/* 4. 旧的假识别实现必须彻底移除 */
console.log("\n[5] 移除旧实现")
check("已移除模拟识别的 recognize()", count("recognize()") === 0)
check("已移除「再次点击结束」话术", count("再次点击结束") === 0)

/* 5. 触控体验 */
console.log("\n[6] 触控体验")
/*
 * 会话区是弹性子项：min-height 默认 auto 会被内容撑高，
 * 把下面的输入栏顶出屏幕、滚动条也跟着跑到屏幕外。
 * 所以这里要的是 min-height: 0（固定高度靠实测，见 test-overflow.js 的 674px 断言）。
 */
check("会话区 min-height 已清零（弹性子项不被内容撑高）",
  h.indexOf("min-height: 0") >= 0, "未找到 min-height: 0")
check("会话区声明 touch-action: pan-y（触屏滑动不被手势判定抢走）",
  h.indexOf("touch-action: pan-y") >= 0)
check("全局 cursor: none", h.indexOf("cursor: none !important") >= 0)

console.log("\n─────────────────────────────")
console.log("语音助手检查：" + pass + " 通过，" + fail + " 失败")
process.exit(fail > 0 ? 1 : 0)
