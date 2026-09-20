"use strict"

/**
 * 从构建产物里抠出 VoiceAssistant 页面的脚本，便于和设备上跑的旧版本对比。
 * 用法：node tools/vnc/scripts/dump-voice-page.js <index.html>
 */

const fs = require("fs")
const s = fs.readFileSync(process.argv[2], "utf8")

// 构建产物里每个页面的脚本都在 PAGES 里，形态是 "VoiceAssistant":{...,"script":"..."}
const key = '"VoiceAssistant"'
const i = s.indexOf(key)
if (i < 0) { console.log("没找到 VoiceAssistant"); process.exit(1) }
const seg = s.slice(i, i + 60000)
const m = seg.match(/"script":"((?:[^"\\]|\\.)*)"/)
if (!m) { console.log("这个页面没有独立脚本字段"); }
else {
  console.log(JSON.parse('"' + m[1] + '"'))
}
