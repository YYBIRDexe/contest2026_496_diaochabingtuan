"use strict"

/**
 * 把仍是 1280 基准的三个页面按 1920 设计基准放大。
 *
 * 背景：Home 页在切到 1920×1080 基准时已手工调过字号与间距，
 * 但 VoiceAssistant / Records / System 仍是 1280 时代的尺寸，
 * 在 1920 屏上显得小一圈、不协调。
 *
 * 做法：对这些 .ux 文件里 `<style>` 段的尺寸类属性统一乘以 1.5（1280→1920），
 * 只改 px 数值，不碰结构与非尺寸属性。
 *
 * 用法：node tools/scale-pages.js [--dry]
 */

const fs = require("fs")
const path = require("path")

const DRY = process.argv.indexOf("--dry") >= 0
const SCALE = 1.5

const SRC = path.join(__dirname, "..", "src", "pages")
const TARGETS = ["VoiceAssistant", "Records", "System"]

/* 需要缩放的属性（只处理 .ux 的 <style> 段） */
const PROPS = [
  "font-size",
  "padding",
  "padding-top", "padding-right", "padding-bottom", "padding-left",
  "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
  "width", "height", "min-width", "min-height", "max-width", "max-height",
  "border-radius",
  "gap",
  "left", "top", "right", "bottom"
]

function scalePxValue(v) {
  return String(Math.round(parseFloat(v) * SCALE))
}

/** 缩放一条声明里的所有 px 值（支持多值简写，如 padding: 1px 2px 3px 4px） */
function scaleDeclaration(prop, value) {
  if (PROPS.indexOf(prop) < 0) {
    return value
  }
  return value.replace(/(-?\d+(?:\.\d+)?)px/g, function (m, num) {
    return scalePxValue(num) + "px"
  })
}

/** 只处理 <style> 段，避免误改 <template> 里的数字 */
function transformUx(text) {
  const m = text.match(/<style>([\s\S]*?)<\/style>/)
  if (!m) {
    return { text: text, changed: 0 }
  }
  let changed = 0
  const newStyle = m[1].replace(/([a-z-]+)\s*:\s*([^;{}]+);/g, function (full, prop, value) {
    if (PROPS.indexOf(prop.trim()) < 0) {
      return full
    }
    if (value.indexOf("px") < 0) {
      return full
    }
    const nv = scaleDeclaration(prop.trim(), value)
    if (nv !== value) {
      changed += 1
      return prop + ": " + nv + ";"
    }
    return full
  })
  return {
    text: text.slice(0, m.index) + "<style>" + newStyle + "</style>" +
      text.slice(m.index + m[0].length),
    changed: changed
  }
}

/* ------------------------------------------------------------------ */
console.log("=== 缩放页面尺寸到 1920 基准（×" + SCALE + "）" + (DRY ? " [演练]" : "") + " ===")

TARGETS.forEach(function (name) {
  const file = path.join(SRC, name, "index.ux")
  if (!fs.existsSync(file)) {
    console.log("  跳过（不存在）: " + name)
    return
  }
  const before = fs.readFileSync(file, "utf8")
  const r = transformUx(before)

  // 统计缩放前后的字号范围，便于核对
  const sizesBefore = (before.match(/font-size:\s*(\d+)px/g) || []).map(function (s) {
    return parseInt(s.replace(/\D/g, ""), 10)
  })
  const sizesAfter = (r.text.match(/font-size:\s*(\d+)px/g) || []).map(function (s) {
    return parseInt(s.replace(/\D/g, ""), 10)
  })

  console.log("\n  " + name)
  console.log("    修改声明数: " + r.changed)
  if (sizesBefore.length) {
    console.log("    字号: " + Math.min.apply(null, sizesBefore) + "-" +
      Math.max.apply(null, sizesBefore) + "px  →  " +
      Math.min.apply(null, sizesAfter) + "-" + Math.max.apply(null, sizesAfter) + "px")
  }

  if (!DRY && r.changed > 0) {
    fs.writeFileSync(file, r.text, "utf8")
    console.log("    已写入")
  }
})

console.log("\n完成。")
