#!/bin/bash
# 诊断：为什么经代理拿不到 Date 头
V=/home/sunrise/velaguard

echo "===== 1. 选代理.sh 会导出什么 ====="
( . /etc/x3m-proxy.env 2>/dev/null; . /home/sunrise/voice_pipeline/选代理.sh 2>/dev/null
  echo "  http_proxy=$http_proxy"; echo "  https_proxy=$https_proxy"
  echo "  X3M_PROXY_CHOSEN=$X3M_PROXY_CHOSEN" )

echo
echo "===== 2. 直接 curl（带 -k、带代理）看完整输出 ====="
( . /etc/x3m-proxy.env 2>/dev/null; . /home/sunrise/voice_pipeline/选代理.sh 2>/dev/null
  echo "--- HEAD 请求 ---"
  curl -k -sI --max-time 10 -o /dev/null -D - https://dashscope.aliyuncs.com 2>&1 | head -8
  echo "--- GET 请求（-w 看 http_code）---"
  curl -k -s -o /dev/null -D /tmp/hdr.txt -w "  code=%{http_code}\n" --max-time 10 https://dashscope.aliyuncs.com 2>&1
  echo "--- GET 的响应头 ---"
  head -6 /tmp/hdr.txt 2>/dev/null | sed 's/^/  /'
  echo "--- 不加代理对照 ---"
  curl -k -sI --max-time 6 -o /dev/null -D - https://dashscope.aliyuncs.com 2>&1 | head -3
)

echo
echo "===== 3. 用 assistant 进程的环境做对照（那个环境是有代理的）====="
P=$(pgrep -f voice_button.py | head -1)
if [ -n "$P" ]; then
  tr '\0' '\n' < /proc/$P/environ | grep -iE "^(http_proxy|https_proxy|X3M_PROXY_CHOSEN)=" | sed 's/^/  /'
  echo "--- 用它跑一次 curl ---"
  ( export $(tr '\0' '\n' < /proc/$P/environ | grep -iE "^(http_proxy|https_proxy)=" | xargs)
    curl -k -sI --max-time 10 -o /dev/null -D - https://dashscope.aliyuncs.com 2>&1 | head -5 )
fi

echo
echo "===== 4. date -s 到底行不行（用固定字符串试）====="
echo sunrise | sudo -S -p "" date -s "Sat, 19 Sep 2026 05:20:15 GMT" && date '+  设置成功：%F %T'
