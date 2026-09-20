"use strict"
/* 复查补丁插入位置是否正确（在 deliver() 的日志写入之前、函数体内部） */
const fs = require("fs")
const p = process.argv[2]
const s = fs.readFileSync(p, "utf8")
const i = s.indexOf('rec["said"] = spoke["reply"]')
if (i < 0) { console.log("没找到补丁标记"); process.exit(1) }
console.log("=== 插入点前后 ===")
console.log(s.slice(i - 620, i + 300))
console.log("\n=== 校验 ===")
console.log("补丁出现次数:", (s.match(/rec\["said"\] = spoke\["reply"\]/g) || []).length)
console.log("仍在 deliver 出口 4 之前:", s.indexOf('rec["said"]') < s.indexOf("# 出口 4：日志"))
