#!/usr/bin/env bash
#
# VelaGuard 验收脚本 —— 在 M1 上直接运行，输出结构化报告。
#
# 它做四件事：
#   1. 体检：屏幕/显示会话、浏览器、依赖
#   2. 部署：通过 HTTP 提供界面（真实数据链路需要 http）
#   3. 抓图：用浏览器无头模式截取 1280x800 的真实渲染结果
#   4. 报告：把关键信息按 === SECTION === 输出，便于远端解析
#
# 用法（在 M1 上）：
#   ./accept.sh              # 体检 + 部署 + 抓图
#   ./accept.sh --no-shot    # 只体检与部署
#
set -uo pipefail

APP_DIR="${1:-$HOME/velaguard}"
PORT="${VELAGUARD_PORT:-8123}"
SHOT_DIR="${APP_DIR}/shots"

say() { echo "$@"; }
sec() { echo ""; echo "=== $1 ==="; }

sec "SYSTEM"
say "host:     $(hostname 2>/dev/null)"
say "kernel:   $(uname -srm)"
if [[ -r /etc/os-release ]]; then
  say "os:       $(. /etc/os-release; echo "$PRETTY_NAME")"
fi
say "arch:     $(uname -m)"
say "uptime:   $(uptime -p 2>/dev/null || uptime)"
say "mem:      $(free -h 2>/dev/null | awk '/^Mem:/{print $2" total, "$7" available"}')"
say "disk:     $(df -h "$HOME" 2>/dev/null | awk 'NR==2{print $2" total, "$4" free"}')"

sec "DISPLAY"
say "DISPLAY=${DISPLAY:-<empty>}"
say "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<empty>}"
if command -v xrandr >/dev/null 2>&1; then
  if [[ -n "${DISPLAY:-}" ]]; then
    say "screens:"
    xrandr --current 2>/dev/null | grep -E '^\s+[0-9]+x[0-9]+' | sed 's/^/  /' | head -20
    say "connected outputs:"
    xrandr --current 2>/dev/null | grep -E ' connected' | sed 's/^/  /'
  else
    say "xrandr: 跳过（无 DISPLAY）"
  fi
else
  say "xrandr: 未安装"
fi
if command -v xinput >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
  say "input devices:"
  xinput list 2>/dev/null | grep -Ei 'touch|pointer|keyboard|slave' | sed 's/^/  /' | head -20
else
  say "xinput: 不可用"
fi
say "framebuffer:"
ls -1 /dev/fb* 2>/dev/null | sed 's/^/  /' || say "  （无 /dev/fb*）"

sec "BROWSER"
BROWSER_BIN=""
for b in chromium chromium-browser google-chrome google-chrome-stable firefox epiphany-browser epiphany midori; do
  if command -v "$b" >/dev/null 2>&1; then
    ver="$("$b" --version 2>/dev/null | head -1)"
    say "found: $b  ($ver)"
    [[ -z "$BROWSER_BIN" ]] && BROWSER_BIN="$b"
  fi
done
[[ -z "$BROWSER_BIN" ]] && say "NONE: 没有找到任何浏览器"
say "picked: ${BROWSER_BIN:-<none>}"

sec "RUNTIME"
for c in node python3 unclutter; do
  if command -v "$c" >/dev/null 2>&1; then
    say "$c: $(command -v $c)  $("$c" --version 2>&1 | head -1)"
  else
    say "$c: 未安装"
  fi
done

sec "APP"
say "app_dir: $APP_DIR"
if [[ -f "$APP_DIR/preview/index.html" ]]; then
  say "index.html: $(stat -c%s "$APP_DIR/preview/index.html" 2>/dev/null) bytes"
else
  say "MISSING: $APP_DIR/preview/index.html"
fi
if [[ -f "$APP_DIR/tools/serve.js" ]]; then
  say "serve.js:   存在"
else
  say "serve.js:   缺失（真实数据链路需要它）"
fi
if [[ -f "$APP_DIR/data/state.json" ]]; then
  say "state.json: 存在（$(stat -c%s "$APP_DIR/data/state.json") bytes）"
else
  say "state.json: 不存在（将回退到内置示例数据）"
fi

# ---------------------------------------------------------------- 部署
sec "SERVE"
if [[ ! -f "$APP_DIR/preview/index.html" ]]; then
  say "skip: 没有界面文件"
else
  if ! command -v node >/dev/null 2>&1; then
    say "skip: 没有 node，无法起数据服务（真实数据链路不可用）"
  else
    # 关掉可能已在跑的旧实例
    pkill -f "tools/serve.js $PORT" 2>/dev/null || true
    sleep 1
    ( cd "$APP_DIR" && nohup node tools/serve.js "$PORT" >/tmp/velaguard-serve.log 2>&1 & )
    sleep 2
    if curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/preview/index.html" 2>/dev/null | grep -q 200; then
      say "serving: http://127.0.0.1:$PORT/  OK"
    else
      say "FAIL: 服务未起来，日志："
      tail -20 /tmp/velaguard-serve.log 2>/dev/null | sed 's/^/  /'
    fi
    state_code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/data/state.json" 2>/dev/null)"
    say "state api: HTTP $state_code"
  fi
fi

# ---------------------------------------------------------------- 抓图
if [[ "${2:-}" == "--no-shot" ]]; then
  sec "SHOT"
  say "skip: 按参数要求跳过"
  exit 0
fi

sec "SHOT"
if [[ -z "$BROWSER_BIN" ]]; then
  say "skip: 没有浏览器"
  exit 0
fi

mkdir -p "$SHOT_DIR"
TARGET="http://127.0.0.1:$PORT/"
if ! curl -s -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
  TARGET="file://$APP_DIR/preview/index.html"
fi
say "target: $TARGET"

case "$BROWSER_BIN" in
  firefox)
    say "note: Firefox 无头截图参数与 Chromium 不同，这里跳过自动抓图"
    say "      可在桌面会话里直接打开：$TARGET"
    ;;
  *)
    # 无头截图：--kiosk 与 --screenshot 不能同用，用固定窗口尺寸
    if "$BROWSER_BIN" --headless=new --disable-gpu --hide-scrollbars \
        --window-size=1280,800 --virtual-time-budget=8000 \
        --screenshot="$SHOT_DIR/kiosk-1280x800.png" "$TARGET" >/tmp/velaguard-shot.log 2>&1; then
      if [[ -f "$SHOT_DIR/kiosk-1280x800.png" ]]; then
        say "shot: $SHOT_DIR/kiosk-1280x800.png  ($(stat -c%s "$SHOT_DIR/kiosk-1280x800.png") bytes)"
      else
        say "FAIL: 截图未生成"
        tail -10 /tmp/velaguard-shot.log 2>/dev/null | sed 's/^/  /'
      fi
    else
      say "FAIL: 浏览器调用失败"
      tail -10 /tmp/velaguard-shot.log 2>/dev/null | sed 's/^/  /'
    fi
    ;;
esac

sec "DONE"
say "验收采集完成。请把以上输出（以及 shots/ 下的截图）回传。"
