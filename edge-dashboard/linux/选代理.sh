#!/bin/bash
# 选代理.sh — 挑一个**真能连上**的代理出口并导出环境变量。
#
# 用法（**必须 source**，否则环境变量传不出去）：
#     . /home/sunrise/voice_pipeline/选代理.sh
#
# 背景
# ----
# 这台板子只有 eth0，**没有公网出口**（实测：网关 192.168.1.1 通，但
# 公共 DNS、443、域名解析全不通），所有云端访问（ASR / TTS / 云端意图模型）
# 都必须走代理。
#
# 而 `/etc/x3m-proxy.env` 里写死的是 `192.168.1.100:7890` —— 那台机器上的
# 代理软件一停，设备就彻底断网，语音助手只能回一句「网络不通」。
# 那个文件是 root 所有、写不了，所以在这里做**运行时兜底**：
#
#   候选 1：配置里原有的代理（正常情况下就是它）
#   候选 2：本机隧道 127.0.0.1:{7890,7891,7892}
#
# 谁先探通就用谁。这样 `192.168.1.100` 修好之后**自动切回去**，
# 不需要再改动任何文件。
#
# ⚠️ 为什么隧道要探三个端口
# --------------------------
# 隧道断了之后，本机的 sshd 有时会把监听套接字留着而**没有对应会话进程**
# （`ss -ltnp` 看不到属主，也杀不掉）。这时 7890 一直被占，反向隧道就建不起来。
# 所以笔记本侧的 autostart.ps1 会在端口被占时自动改用下一个候选，
# 这里必须探测**同一组端口**才能跟上。两边的列表要一起改。

_pick_probe() {   # host port -> 0=通
    timeout 2 bash -c "echo > /dev/tcp/$1/$2" 2>/dev/null
}

_pick_apply() {   # host port
    export http_proxy="http://$1:$2"
    export https_proxy="http://$1:$2"
    export HTTP_PROXY="$http_proxy"
    export HTTPS_PROXY="$https_proxy"
    export no_proxy="localhost,127.0.0.1,::1,192.168.1.0/24,10.0.0.0/8"
    export NO_PROXY="$no_proxy"
    export X3M_PROXY_CHOSEN="$1:$2"
}

_pick_from() {    # url -> host port（拆不出就返回 1）
    local url="$1"
    [ -n "$url" ] || return 1
    local hp="${url#*://}"
    hp="${hp%%/*}"
    local h="${hp%%:*}"
    local p="${hp##*:}"
    [ "$h" = "$hp" ] && p=80          # 没写端口
    [ -n "$h" ] || return 1
    _PICK_H="$h"; _PICK_P="$p"
    return 0
}

# 本机隧道候选端口（必须与笔记本 autostart.ps1 的 -Ports 保持一致）
TUNNEL_PORTS="7890 7891 7892"

# ---- 候选 1：配置里原有的代理 ----
for _u in "${https_proxy:-}" "${HTTPS_PROXY:-}" "${http_proxy:-}" "${HTTP_PROXY:-}"; do
    if _pick_from "$_u"; then
        if _pick_probe "$_PICK_H" "$_PICK_P"; then
            _pick_apply "$_PICK_H" "$_PICK_P"
            echo "[代理] 使用配置里的 $_PICK_H:$_PICK_P"
            return 0 2>/dev/null || exit 0
        fi
    fi
done

# ---- 候选 2：本机隧道（逐个端口试）----
for _p in $TUNNEL_PORTS; do
    if _pick_probe 127.0.0.1 "$_p"; then
        _pick_apply 127.0.0.1 "$_p"
        echo "[代理] ⚠ 配置里的代理不可用，改用**本机隧道** 127.0.0.1:$_p"
        echo "        （由笔记本通过 SSH 反向隧道借网；笔记本或隧道一断，这里就不通了）"
        return 0 2>/dev/null || exit 0
    fi
done

# ---- 都不通 ----
echo "[代理] ⚠ 没有任何可用代理 —— 云端 ASR / TTS / 意图模型都会失败，"
echo "        语音助手只会回一句「网络不通」。"
echo "        排查：① 192.168.1.100 上的代理软件是否在运行；"
echo "              ② 笔记本上的 local_proxy.py 与 SSH 反向隧道是否还在"
echo "                 （笔记本执行 tunnel\\run-hidden.vbs，或看 tunnel\\autostart.log）。"
return 1 2>/dev/null || exit 1
