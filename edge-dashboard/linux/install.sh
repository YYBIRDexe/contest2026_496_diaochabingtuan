#!/usr/bin/env bash
#
# VelaGuard 巡检桌面 —— 在 M1（Linux）上安装为开机自启的全屏看板
#
# 做的事情：
#   1. 把界面文件与启动脚本复制到用户目录 ~/velaguard
#   2. 写入桌面自启动项（登录后自动全屏启动）
#   3. 可选：禁用息屏 / 屏保，保证长时间显示
#
# 用法（把整个 VelaGuard-Desktop 目录拷到 M1 后执行）：
#   cd VelaGuard-Desktop/linux
#   ./install.sh              # 安装自启动
#   ./install.sh --uninstall  # 卸载自启动
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "${SCRIPT_DIR}")"

TARGET_DIR="${HOME}/velaguard"
AUTOSTART_DIR="${HOME}/.config/autostart"
DESKTOP_FILE="${AUTOSTART_DIR}/velaguard.desktop"

uninstall() {
  echo "==> 卸载 VelaGuard 自启动项"
  rm -f "${DESKTOP_FILE}"
  rm -f "${AUTOSTART_DIR}/velaguard-hide-cursor.desktop"
  echo "已移除自启动项（保留 ${TARGET_DIR}，如需彻底删除请手动 rm -rf）"
  exit 0
}

if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall
fi

# ---------------------------------------------------------------- 1. 前置检查
echo "==> 检查界面文件"
if [[ ! -f "${PKG_DIR}/preview/index.html" ]]; then
  echo "错误：找不到 ${PKG_DIR}/preview/index.html" >&2
  echo "请先在开发机上执行  node tools/build-preview.js  再把整个目录拷过来。" >&2
  exit 1
fi

# ---------------------------------------------------------------- 2. 复制文件
echo "==> 安装到 ${TARGET_DIR}"
mkdir -p "${TARGET_DIR}/preview" "${TARGET_DIR}/src" "${TARGET_DIR}/docs" "${TARGET_DIR}/linux"

cp -f "${PKG_DIR}/preview/index.html" "${TARGET_DIR}/preview/"
cp -rf "${PKG_DIR}/src/." "${TARGET_DIR}/src/" 2>/dev/null || true
cp -rf "${PKG_DIR}/docs/." "${TARGET_DIR}/docs/" 2>/dev/null || true
cp -f "${SCRIPT_DIR}/start.sh" "${TARGET_DIR}/linux/start.sh"
chmod +x "${TARGET_DIR}/linux/start.sh"

# ---------------------------------------------------------------- 3. 自启动项
echo "==> 写入自启动项 ${DESKTOP_FILE}"
mkdir -p "${AUTOSTART_DIR}"

cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=VelaGuard 巡检桌面
Comment=多机器人分区巡检调度台（全屏看板）
Exec=${TARGET_DIR}/linux/start.sh
Path=${TARGET_DIR}
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "    内容："
sed 's/^/      /' "${DESKTOP_FILE}"

# ---------------------------------------------------------------- 3b. 隐藏鼠标光标
# 触控屏不需要指针。hide-cursor 必须在图形会话内运行才有有效 X 授权
# （Xorg 用 -auth /var/run/lightdm/root/:0，属 root，SSH 里拿不到）。
# 所以单独放一个自启动项，登录即生效，不依赖看板是否在跑。
# 注意不加 --watch：它设完即退，设置由 X 服务端保持。
CURSOR_BIN="${TARGET_DIR}/linux/hide-cursor"
CURSOR_DESKTOP="${AUTOSTART_DIR}/velaguard-hide-cursor.desktop"

if [[ -x "${CURSOR_BIN}" ]]; then
  echo "==> 写入光标隐藏自启动项 ${CURSOR_DESKTOP}"
  cat > "${CURSOR_DESKTOP}" <<EOF
[Desktop Entry]
Type=Application
Name=VelaGuard 隐藏鼠标光标
Comment=触控屏无需鼠标指针
Exec=${CURSOR_BIN}
Path=${TARGET_DIR}
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
  echo "    内容："
  sed 's/^/      /' "${CURSOR_DESKTOP}"
else
  echo "==> 跳过光标隐藏自启动：${CURSOR_BIN} 不存在"
  echo "    请先在开发机执行：node tools/vnc/deploy-cursor.js"
  echo "    （该工具会上传源码并用 M1 自带 gcc 编译出 hide-cursor）"
fi

# ---------------------------------------------------------------- 4. 可选加固
echo
echo "==> 可选加固（需要时手动执行一次）"
echo "    禁用息屏 / 屏保："
echo "      xset s off; xset -dpms; xset s noblank"
echo "    去掉桌面鼠标指针："
echo "      sudo apt install -y unclutter    # start.sh 会自动使用"
echo
echo "==> 完成"
echo "    立即测试：  ${TARGET_DIR}/linux/start.sh"
echo "    窗口调试：  ${TARGET_DIR}/linux/start.sh --windowed"
echo "    取消自启：  ${SCRIPT_DIR}/install.sh --uninstall"
echo
echo "    提示：如果登录后没有自动进入桌面会话，自启动不会触发。"
echo "          可在系统设置里打开「自动登录」，或改用 systemd 服务方式。"
