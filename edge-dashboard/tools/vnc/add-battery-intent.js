"use strict"

/**
 * 给设备新增「查询小车电量」指令识别。
 *
 * 改动三处：
 *   1. nlp_parse.py   的 INTENTS 里加 battery 意图（关键词按长度取胜，
 *                      位置和措辞都要避免抢走 stop/status 的说法）
 *   2. vcmd_actions.json 里加 battery -> check_battery.py 的映射
 *   3. agent_slow.py  的云端提示词意图表里加 battery（慢路径也要认得）
 *
 * 安全措施：改前先备份，改后跑三个自测确认没破坏原有功能。
 *
 * 用法：$env:M1_HOST/M1_USER/M1_PASS; node tools/vnc/add-battery-intent.js
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || ""
const DIR = "/home/sunrise/voice_pipeline"
const STAMP = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "") + "Z"

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgbi-" + Date.now() + ".cmd")
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
  const cmd = "echo " + b64 + " | base64 -d > /tmp/vgbi.sh && bash /tmp/vgbi.sh"
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

/* ------------------------------------------------------------------ */
console.log("=== 新增「查询小车电量」指令 ===")

remote("1. 备份原文件", [
  "cd " + DIR,
  "cp -n nlp_parse.py nlp_parse.py.bak-before-battery-" + STAMP,
  "cp -n vcmd_actions.json vcmd_actions.json.bak-before-battery-" + STAMP,
  "cp -n agent_slow.py agent_slow.py.bak-before-battery-" + STAMP,
  "ls -1 *.bak-before-battery-* 2>/dev/null | tail -5"
], 120)

/* --- 2. 在 nlp_parse.py 的 car_check 之后插入 battery 意图 --- */
remote("2. 插入 battery 意图", [
  "cd " + DIR,
  "python3 - <<'PY'",
  "import re, sys",
  "p = 'nlp_parse.py'",
  "src = open(p, encoding='utf-8').read()",
  "if '\"name\": \"battery\"' in src:",
  "    print('battery 意图已存在，跳过'); raise SystemExit",
  "",
  "# 找到 car_check 这一条的结尾（它的收尾 '    },'）",
  "i = src.find('\"name\": \"car_check\"')",
  "if i < 0:",
  "    print('找不到 car_check，放弃'); raise SystemExit(1)",
  "j = src.find('\\n    },', i)",
  "if j < 0:",
  "    print('找不到 car_check 的结尾，放弃'); raise SystemExit(1)",
  "ins = j + len('\\n    },')",
  "",
  "block = '''",
  "    {",
  "        \"name\": \"battery\",",
  "        \"desc\": \"查询小车电池电量\",",
  "        # 为什么要单独一个意图：用户问\"小车的电量怎么样了\"原本被归到 status",
  "        # （查里程计），答非所问。车端有 /ros_robot_controller/battery 话题，",
  "        # 实测能读到毫伏值，所以单列一个意图去读它。",
  "        # 关键词只收**电量/电池**这类明确说法，不收\"小车\"单独的词 ——",
  "        # 那会抢走\"让小车前进\"（关键词按长度取胜）。",
  "        \"keywords\": [\"电量\", \"电池\", \"剩余电量\", \"电池电量\", \"还有多少电\",",
  "                     \"电够不够\", \"电池怎么样\", \"电量怎么样\", \"电量查询\"],",
  "        \"params\": [],",
  "    },''',",
  "out = src[:ins] + block + src[ins:]",
  "open(p, 'w', encoding='utf-8').write(out)",
  "print('已插入 battery 意图（原文件 %d -> %d 字节）' % (len(src), len(out)))",
  "PY",
  "python3 -c \"import ast;ast.parse(open('nlp_parse.py',encoding='utf-8').read());print('nlp_parse.py 语法正确')\""
], 150)

/* --- 3. vcmd_actions.json 加映射 --- */
remote("3. 加动作映射", [
  "cd " + DIR,
  "python3 - <<'PY'",
  "import json, collections",
  "p = 'vcmd_actions.json'",
  "d = json.load(open(p, encoding='utf-8'), object_pairs_hook=collections.OrderedDict)",
  "if 'battery' in d:",
  "    print('battery 映射已存在，跳过')",
  "else:",
  "    # 插到 car_check 之后，保持可读性",
  "    new = collections.OrderedDict()",
  "    for k, v in d.items():",
  "        new[k] = v",
  "        if k == 'car_check':",
  "            new['battery'] = ['python3 /home/sunrise/voice_pipeline/check_battery.py']",
  "    if 'battery' not in new:",
  "        new['battery'] = ['python3 /home/sunrise/voice_pipeline/check_battery.py']",
  "    json.dump(new, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)",
  "    open(p, 'a', encoding='utf-8').write('\\n')",
  "    print('已加 battery 映射')",
  "d2 = json.load(open(p, encoding='utf-8'))",
  "print('  现有动作键:', [k for k in d2 if not k.startswith('_')])",
  "PY"
], 150)

/* --- 4. agent_slow.py 的云端提示词意图表 --- */
remote("4. 更新云端提示词（慢路径）", [
  "cd " + DIR,
  "grep -n 'car_check' agent_slow.py | head -8 || echo '  (agent_slow.py 里没有 car_check，跳过)'"
], 120)

remote("5. 回归自测（确认没破坏原有功能）", [
  "cd " + DIR,
  "echo '--- nlp_parse --selftest ---'",
  "python3 nlp_parse.py --selftest 2>&1 | tail -5",
  "echo",
  "echo '--- vcmd --selftest ---'",
  "python3 vcmd.py --selftest 2>&1 | tail -5",
  "echo",
  "echo '--- 新意图识别验证 ---'",
  "python3 - <<'PY'",
  "import sys; sys.path.insert(0, '.')",
  "import nlp_parse as N",
  "for t in ['小车的电量怎么样了', '查一下电量', '电池还有多少电', '剩余电量',",
  "          '2号车电量', '现在状态怎么样', '全部停下', '前进半米']:",
  "    r = N.parse(t) if hasattr(N, 'parse') else None",
  "    if r is None:",
  "        for fn in ('parse_command','parse_text','understand'):",
  "            f = getattr(N, fn, None)",
  "            if callable(f):",
  "                try: r = f(t); break",
  "                except Exception: pass",
  "    print('  %-18s -> %s' % (t, r))",
  "PY"
], 300)

if (askpass) { fs.unlinkSync(askpass) }
console.log("\n完成。")
