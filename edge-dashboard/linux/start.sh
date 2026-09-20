#!/usr/bin/env bash
#
# VelaGuard 巡检桌面 —— Linux 全屏启动脚本
#
# 目标设备：M1 实训箱上的 Linux（Horizon X3M / Ubuntu）+ 外接触控显示器
#
# 特点：
#   - 自动探测浏览器：chromium / google-chrome / firefox / epiphany
#   - kiosk 全屏、隐藏鼠标指针、禁止息屏
#   - 两种数据模式：
#       file://  → 自包含单文件，零依赖，但只有演示数据（浏览器禁止跨源 fetch）
#       http://  → 可接 M1 真实巡检数据（推荐正式部署用）
#
# 用法：
#   ./start.sh                       # 全屏看板（file://，演示数据）
#   ./start.sh --serve               # 本机起服务 + 全屏（可接真实数据）
#   ./start.sh --url http://主机:8080/   # 连到别处已起好的服务
#   ./start.sh --windowed            # 窗口模式（调试用）
#   ./start.sh --page voice          # 启动后直接进入指定页面
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "${SCRIPT_DIR}")"
PAGE_FILE="${PKG_DIR}/preview/index.html"

WINDOWED=0
START_PAGE=""
SERVE=0
URL_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --windowed) WINDOWED=1; shift ;;
    --serve)    SERVE=1; shift ;;
    --url)      URL_OVERRIDE="${2:-}"; shift 2 ;;
    --page)     START_PAGE="${2:-}"; shift 2 ;;
    -h|--help)
      sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------- 前置检查
if [[ ! -f "${PAGE_FILE}" ]]; then
  echo "找不到界面文件：${PAGE_FILE}" >&2
  echo "请先在开发机上执行  node tools/build-preview.js  生成预览页并同步到本机。" >&2
  exit 1
fi

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo "当前没有图形会话（DISPLAY / WAYLAND_DISPLAY 均为空）。" >&2
  echo "请在 M1 的桌面环境下运行本脚本，或先执行 export DISPLAY=:0" >&2
  exit 1
fi

# ---------------------------------------------------------------- 数据服务
SERVE_PID=""
SPEECH_PID=""
PORT="${VELAGUARD_PORT:-8123}"
SPEECH_PORT="${VELAGUARD_SPEECH_PORT:-8124}"

cleanup() {
  [[ -n "${SERVE_PID}" ]] && kill "${SERVE_PID}" 2>/dev/null || true
  [[ -n "${SPEECH_PID}" ]] && kill "${SPEECH_PID}" 2>/dev/null || true
  [[ -n "${UNCLUTTER_PID:-}" ]] && kill "${UNCLUTTER_PID}" 2>/dev/null || true
  [[ -n "${HIDE_CURSOR_PID:-}" ]] && kill "${HIDE_CURSOR_PID}" 2>/dev/null || true
}
trap cleanup EXIT

if [[ "${SERVE}" -eq 1 ]]; then
  if ! command -v node >/dev/null 2>&1; then
    echo "警告：未找到 node，无法启用 --serve（数据接口需要它）。" >&2
    echo "      将以 file:// 模式启动，只能显示演示数据。" >&2
  else
    echo "启动本地数据服务（端口 ${PORT}）…"
    ( cd "${PKG_DIR}" && node tools/serve.js "${PORT}" ) &
    SERVE_PID=$!
    sleep 2
  fi
fi

# ---------------------------------------------------------------- 语音服务
# 语音助手的离线识别（vosk 中文模型）。
# 幂等：自启动目录里没有单独一项，但重复运行 start.sh 时不应起第二个实例。
# 麦克风采不到声音属硬件限制，服务会如实返回 silent=true，界面据此降级提示。
SPEECH_BRIDGE="${PKG_DIR}/linux/speech-bridge.py"
if [[ -f "${SPEECH_BRIDGE}" ]] && command -v python3 >/dev/null 2>&1; then
  if pgrep -f "speech-bridge.py" >/dev/null 2>&1; then
    echo "语音服务已在运行（端口 ${SPEECH_PORT}）"
  else
    echo "启动离线语音服务（vosk，端口 ${SPEECH_PORT}）…"
    ( cd "${PKG_DIR}/linux" && python3 speech-bridge.py --port "${SPEECH_PORT}" ) \
      >/tmp/speech.log 2>&1 &
    SPEECH_PID=$!
  fi
else
  echo "提示：未找到 speech-bridge.py 或 python3，语音助手将无法录音识别。"
fi

# ---------------------------------------------------------------- 浏览器探测
detect_browser() {
  local candidates=(
    chromium chromium-browser google-chrome google-chrome-stable
    firefox epiphany-browser epiphany midori
  )
  local b
  for b in "${candidates[@]}"; do
    if command -v "$b" >/dev/null 2>&1; then
      echo "$b"
      return 0
    fi
  done
  return 1
}

BROWSER="$(detect_browser || true)"
if [[ -z "${BROWSER}" ]]; then
  cat >&2 <<'EOF'
没有找到可用的浏览器。

本界面是一个 HTML 应用，需要一个浏览器内核来显示。请任选一种方式安装：

  1) 系统自带源（需要网络）
       sudo apt update && sudo apt install -y chromium-browser

  2) 若设备完全离线，可在有网的机器上下载对应架构的 .deb 包，拷进来安装：
       sudo dpkg -i chromium-browser_*.deb

  3) 若设备上已有 Firefox：
       ./start.sh          # 脚本会自动探测到 firefox 并使用 kiosk 模式

安装完成后重新运行本脚本即可。
EOF
  exit 1
fi

echo "使用浏览器：${BROWSER}"

# ---------------------------------------------------------------- 组装启动参数
if [[ -n "${URL_OVERRIDE}" ]]; then
  URL="${URL_OVERRIDE}"
elif [[ -n "${SERVE_PID}" ]]; then
  # ?src=file → 界面启动就用「M1 数据」源（每 5 秒读 state.json），
  # 而不是停在演示数据上。设备上由 linux/car_state.py 每 5 秒真探测四台车写入。
  URL="http://127.0.0.1:${PORT}/preview/index.html?src=file"
else
  URL="file://${PAGE_FILE}"
fi

# 追加页面 hash（kiosk 隐藏工具栏，或直达某个 app）
HASH=""
[[ "${WINDOWED}" -eq 0 ]] && HASH="kiosk"
[[ -n "${START_PAGE}" ]] && HASH="${HASH:+${HASH},}${START_PAGE}"
[[ -n "${HASH}" ]] && URL="${URL}#${HASH}"

ARGS=()

# --allow-file-access-from-files 只在 file:// 模式下有用；
# 实测在 http:// 模式下加上它会让 Firefox 显示**纯白页**
# （窗口标题停在 "Mozilla Firefox"，页面根本没加载）。
# 所以严格按协议判断，不要无条件加。
case "${URL}" in
  file://*)
    ARGS+=(--allow-file-access-from-files)
    ;;
esac

case "${BROWSER}" in
  firefox)
    if [[ "${WINDOWED}" -eq 0 ]]; then
      ARGS+=(--kiosk)
    fi
    ARGS+=("${URL}")
    ;;
  *)
    if [[ "${WINDOWED}" -eq 0 ]]; then
      ARGS+=(
        --kiosk
        --start-fullscreen
        --window-position=0,0
        --disable-infobars
        --disable-session-crashed-bubble
        --disable-features=TranslateUI
        --noerrdialogs
        --fast
        --fast-start
      )
    else
      ARGS+=(--window-size=1280,800)
    fi
    ARGS+=(--disable-background-timer-throttling)
    ARGS+=(--disable-renderer-backgrounding)
    ARGS+=(--disable-backgrounding-occluded-windows)
    ARGS+=("${URL}")
    ;;
esac

# ---------------------------------------------------------------- 环境加固
HIDE_CURSOR="${PKG_DIR}/linux/hide-cursor"

# 隐藏鼠标光标：触控屏不需要指针。
# 用自带编译的 hide-cursor（递归给整棵窗口树设 1x1 透明光标）。
# 必须在**图形会话内**运行才能拿到有效 X 授权（Xorg 用
# -auth /var/run/lightdm/root/:0，属 root，SSH 里拿不到）。
#
# 必须加 --watch：X 的光标是**逐窗口**属性，浏览器新建窗口、面板重绘都会
# 产生没有透明光标的新窗口，指针移上去光标就恢复可见。
# 常驻模式每秒重扫窗口树，把新窗口补齐。
#
# 幂等处理：自启动目录里也有一项会起 hide-cursor --watch（这样即使看板没启动，
# 光标也是隐藏的）。两边都可能在跑，所以先检查是否已有实例，避免重复占用。
if [[ "${WINDOWED}" -eq 0 ]]; then
  if pgrep -f "hide-cursor --watch" >/dev/null 2>&1; then
    echo "透明光标已在运行（复用现有进程）"
  elif [[ -x "${HIDE_CURSOR}" ]]; then
    "${HIDE_CURSOR}" --watch >/tmp/hide-cursor.log 2>&1 &
    HIDE_CURSOR_PID=$!
    sleep 1
    if kill -0 "${HIDE_CURSOR_PID}" 2>/dev/null; then
      echo "已隐藏鼠标光标（PID ${HIDE_CURSOR_PID}）"
    else
      echo "警告：隐藏光标失败，详见 /tmp/hide-cursor.log"
      cat /tmp/hide-cursor.log 2>/dev/null | sed 's/^/  /'
    fi
  elif command -v unclutter >/dev/null 2>&1; then
    unclutter -idle 0 -root >/dev/null 2>&1 &
    UNCLUTTER_PID=$!
    echo "已启动 unclutter"
  else
    echo "提示：未找到 hide-cursor 也未装 unclutter，鼠标光标将保持可见。"
    echo "      可在开发机执行 node tools/vnc/deploy-cursor.js 编译安装。"
  fi
fi

# 关闭 X 屏保与 DPMS（仅 X11 会话）
if [[ -n "${DISPLAY:-}" ]]; then
  command -v xset >/dev/null 2>&1 && {
    xset s off 2>/dev/null || true
    xset -dpms 2>/dev/null || true
    xset s noblank 2>/dev/null || true
  }
fi

echo "启动 VelaGuard 巡检桌面：${URL}"
exec "${BROWSER}" "${ARGS[@]}"
