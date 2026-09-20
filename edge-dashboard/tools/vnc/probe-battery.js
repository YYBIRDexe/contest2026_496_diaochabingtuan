"use strict"

/**
 * 探测小车是否有电量数据可读（为新增「查询电量」指令做准备）。
 *
 * 背景：四台小车已上线（.201~.204 的 9090 都通），但设备上 ros_car.py
 * 完全没有电量相关代码，所以要先确认车端 ROS 图里到底有没有电池话题。
 *
 * 做法：在设备上用 rosbridge 的 /rosapi/topics 列出全部话题，筛电量相关的，
 * 再尝试订阅一次看能否读到真实数值。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/probe-battery.js
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || ""

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgbt-" + Date.now() + ".cmd")
      fs.writeFileSync(askpass, "@echo off\r\necho %VG_SSH_PASS%\r\n", "utf8")
    }
    e.VG_SSH_PASS = PASS
    e.SSH_ASKPASS = askpass
    e.SSH_ASKPASS_REQUIRE = "force"
    e.DISPLAY = "localhost:0"
  }
  return e
}

const OPTS = [
  "-o", "StrictHostKeyChecking=no",
  "-o", "UserKnownHostsFile=/dev/null",
  "-o", "ConnectTimeout=10",
  "-o", "LogLevel=ERROR",
  "-o", "PreferredAuthentications=password,keyboard-interactive",
  "-o", "PubkeyAuthentication=no",
  "-o", "NumberOfPasswordPrompts=1"
]

function remote(title, lines, timeoutSec) {
  if (title) { console.log("\n### " + title) }
  const b64 = Buffer.from(lines.join("\n"), "utf8").toString("base64")
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgbt.sh && bash /tmp/vgbt.sh"
  const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST, cmd]), {
    encoding: "utf8",
    timeout: (timeoutSec || 240) * 1000,
    env: env(),
    maxBuffer: 32 * 1024 * 1024
  })
  const out = (String(r.stdout || "") + (r.stderr ? "\n[stderr] " + String(r.stderr) : "")).trim()
  if (title) { console.log(out || "(no output)") }
  return out
}

/* 在设备上写一个探测脚本再执行 —— 避免 shell 引号问题 */
const PROBE = [
  "cat > /tmp/vg_battery_probe.py <<'PY'",
  "# -*- coding: utf-8 -*-",
  '"""探测小车电量话题。"""',
  "import asyncio, json, sys",
  "import websockets",
  "",
  "CAR = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.201'",
  "URL = 'ws://%s:9090' % CAR",
  "",
  "# 常见电量话题名（先按话题列表筛，再补几个候选）",
  "KEYS = ['battery', 'Battery', 'power', 'voltage', 'fuel', 'charge', '电量']",
  "",
  "async def main():",
  "    async with websockets.connect(URL, open_timeout=8, max_size=2**22) as ws:",
  "        # 1) 取话题列表",
  "        await ws.send(json.dumps({'op':'call_service',",
  "                                  'service':'/rosapi/topics',",
  "                                  'args':{}, 'id':'t1'}))",
  "        topics = []",
  "        for _ in range(40):",
  "            try:",
  "                raw = await asyncio.wait_for(ws.recv(), timeout=3)",
  "            except asyncio.TimeoutError:",
  "                break",
  "            m = json.loads(raw)",
  "            if m.get('id') == 't1' and 'values' in m:",
  "                topics = m['values'].get('topics', [])",
  "                break",
  "        print('话题总数:', len(topics))",
  "        hit = [t for t in topics if any(k.lower() in t.lower() for k in KEYS)]",
  "        print('电量相关话题:', hit if hit else '(无)')",
  "        print()",
  "        if not hit:",
  "            print('--- 全部话题（前 60 个）---')",
  "            for t in topics[:60]:",
  "                print('   ', t)",
  "            return",
  "        # 2) 订阅第一个电量话题，看能否读到数值",
  "        topic = hit[0]",
  "        print('--- 订阅 %s 试读 ---' % topic)",
  "        await ws.send(json.dumps({'op':'subscribe','topic':topic,'id':'s1'}))",
  "        got = 0",
  "        for _ in range(60):",
  "            try:",
  "                raw = await asyncio.wait_for(ws.recv(), timeout=5)",
  "            except asyncio.TimeoutError:",
  "                break",
  "            m = json.loads(raw)",
  "            if m.get('op') == 'publish' and m.get('topic') == topic:",
  "                print('  收到:', json.dumps(m.get('msg'), ensure_ascii=False)[:400])",
  "                got += 1",
  "                if got >= 3:",
  "                    break",
  "        if got == 0:",
  "            print('  (5 秒内没收到数据 —— 话题存在但没有发布者，或数据是请求式的)')",
  "",
  "asyncio.run(main())",
  "PY",
  "python3 /tmp/vg_battery_probe.py 192.168.1.201 2>&1 | head -80"
]

console.log("=== 探测小车电量数据 ===")

remote("1. 小车在线状态", [
  "for ip in 192.168.1.201 192.168.1.202 192.168.1.203 192.168.1.204; do",
  "  timeout 3 bash -c \"echo > /dev/tcp/$ip/9090\" 2>/dev/null && echo \"  $ip 在线\" || echo \"  $ip 离线\"",
  "done"
], 120)

remote("2. 列出话题并找电量", PROBE, 300)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
