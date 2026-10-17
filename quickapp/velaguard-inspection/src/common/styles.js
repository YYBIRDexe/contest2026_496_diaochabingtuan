/**
 * 公共样式（渲染进宿主页面的 <style>）
 *
 * 尺寸都按 **720×1280 竖屏**（openvela 官方 goldfish 模拟器的屏）设计，
 * 触摸目标不小于 48px。浏览器预览用同一份 CSS，所以预览即所见。
 *
 * 只用最普通的 CSS 子集（flex / 圆角 / 颜色 / 字号），
 * 不用伪类、CSS 变量、动画——快应用的样式引擎对这些支持有限。
 */
export const BASE_CSS = `
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #0b1220; }
body {
  font-family: -apple-system, "Noto Sans CJK SC", "Source Han Sans SC", sans-serif;
  color: #e2e8f0;
  -webkit-user-select: none;
  user-select: none;
}
#app { width: 720px; min-height: 1280px; background: #0b1220; position: relative; }

.screen { padding: 18px 20px 10px 20px; }

/* ---------- 状态栏 ---------- */
.statusbar { display: flex; justify-content: space-between; align-items: center; height: 62px; }
.sb-left { display: flex; align-items: center; }
.sb-time { font-size: 30px; font-weight: 700; color: #fff; }
.sb-title { font-size: 20px; color: #64748b; margin-left: 14px; }
.sb-right { display: flex; align-items: center; }
.sb-battery { font-size: 20px; color: #94a3b8; margin-left: 12px; }

/* ---------- 通用组件 ---------- */
.chip {
  display: flex; align-items: center; justify-content: center;
  min-height: 48px; padding: 0 18px; border-radius: 24px; margin-left: 10px;
  font-size: 20px;
}
.btn {
  display: flex; align-items: center; justify-content: center;
  min-height: 56px; padding: 0 22px; border-radius: 28px;
  background: #23324f; color: #cbd5e1; font-size: 22px; margin-right: 12px;
}
.btn-primary { background: #2f6df6; color: #fff; font-weight: 700; }
.btn-danger { background: #7f1d1d; color: #fecaca; }
.btn-ghost { background: transparent; border: 1px solid #334155; }
.btn-sm { min-height: 44px; padding: 0 16px; font-size: 19px; border-radius: 22px; }

.card { background: #16223a; border-radius: 22px; padding: 16px 18px; margin-bottom: 12px; }
.row { display: flex; align-items: center; }
.row-between { display: flex; align-items: center; justify-content: space-between; }
.section-title { font-size: 21px; color: #7d8ea8; margin: 14px 0 8px 0; }
.muted { color: #7d8ea8; }
.small { font-size: 18px; }
.mono { font-family: Consolas, "DejaVu Sans Mono", monospace; }

.bar { height: 8px; border-radius: 4px; background: #24314d; overflow: hidden; margin-top: 10px; }
.bar-in { height: 8px; border-radius: 4px; }

/* ---------- 桌面磁贴 ---------- */
.grid { display: flex; flex-wrap: wrap; }
.tile {
  width: 330px; height: 128px; margin: 0 16px 14px 0;
  border-radius: 22px; background: #16223a;
  display: flex; align-items: center; padding: 0 16px;
}
.tile:nth-child(2n) { margin-right: 0; }
.tile-icon {
  width: 62px; height: 62px; border-radius: 18px; flex: none;
  display: flex; align-items: center; justify-content: center;
  font-size: 28px; font-weight: 700; color: #fff; margin-right: 14px;
}
.tile-name { font-size: 23px; font-weight: 700; color: #e2e8f0; }
.tile-sub { font-size: 18px; color: #7d8ea8; margin-top: 4px; }

/* ---------- 底部快捷坞 ---------- */
.dock { display: flex; align-items: center; height: 76px; margin-top: 8px; }
.dock .btn { margin-right: 12px; }

/* ---------- 英雄卡（本轮概览） ---------- */
.hero { background: #16223a; border-radius: 24px; padding: 14px 20px 16px 20px; }
.hero-main { font-size: 27px; font-weight: 700; color: #e2e8f0; margin: 6px 0 4px 0; }
.stats { display: flex; margin-top: 6px; }
.stat { flex: 1; display: flex; flex-direction: column; align-items: center; }
.stat-num { font-size: 30px; font-weight: 700; }
.stat-label { font-size: 18px; color: #7d8ea8; margin-top: 2px; }

/* ---------- 地图 ---------- */
.mapwrap { background: #0e1729; border-radius: 20px; overflow: hidden; }
.mapsvg { display: block; }

/* ---------- 列表 ---------- */
.lrow {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; background: #16223a; border-radius: 18px; margin-bottom: 10px;
}
.lrow-main { flex: 1; }
.lrow-title { font-size: 22px; font-weight: 700; color: #e2e8f0; }
.lrow-sub { font-size: 18px; color: #7d8ea8; margin-top: 3px; }
.dot { width: 12px; height: 12px; border-radius: 6px; margin-right: 10px; flex: none; }

/* ---------- 聊天 ---------- */
.chat { height: 640px; overflow-y: auto; padding-right: 4px; }
.msg { margin-bottom: 12px; display: flex; }
.msg-me { justify-content: flex-end; }
.bubble {
  max-width: 560px; padding: 12px 16px; border-radius: 18px;
  font-size: 21px; line-height: 1.5; white-space: pre-wrap; word-break: break-word;
}
.bubble-me { background: #2f6df6; color: #fff; }
.bubble-agent { background: #16223a; color: #e2e8f0; }
.bubble-sys { background: #1e293b; color: #94a3b8; font-size: 18px; }
.tools { font-size: 17px; color: #3ddc84; margin-top: 6px; }

/* ---------- 输入区 ---------- */
.inputbar { display: flex; align-items: center; margin-top: 10px; }
.input {
  flex: 1; height: 62px; border-radius: 31px; background: #16223a;
  border: 1px solid #24314d; color: #e2e8f0; font-size: 21px; padding: 0 20px;
  outline: none;
}
.presets { display: flex; flex-wrap: wrap; margin-top: 10px; }
.preset {
  padding: 10px 16px; border-radius: 20px; background: #1b2942;
  color: #a9c1e0; font-size: 19px; margin: 0 10px 10px 0;
}

/* ---------- 提示浮层 ---------- */
.toast {
  position: fixed; left: 50%; bottom: 120px; transform: translateX(-50%);
  max-width: 620px; padding: 14px 22px; border-radius: 20px;
  background: #2f6df6; color: #fff; font-size: 21px; z-index: 99;
  box-shadow: 0 6px 20px rgba(0,0,0,0.4);
}
.empty { padding: 40px 0; text-align: center; color: #64748b; font-size: 21px; }
.kv { display: flex; justify-content: space-between; font-size: 19px; padding: 5px 0; }
.kv-k { color: #7d8ea8; }
.kv-v { color: #cbd5e1; }
`

export default { BASE_CSS: BASE_CSS }
