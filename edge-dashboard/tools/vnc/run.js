"use strict"

/**
 * 通用远程执行器：把本地一段 bash 脚本送到 M1 上跑，取回输出。
 *
 * 为什么要有它：本项目每查一次设备状态都要写一遍 SSH + askpass 样板，
 * 已经散落二十多个文件。这里收口成一个工具，诊断时只关心「跑什么」。
 *
 * 用法：
 *   $env:M1_PASS='sunrise'
 *   node tools/vnc/run.js --file tools/vnc/scripts/xxx.sh      # 跑脚本文件
 *   node tools/vnc/run.js "pgrep -af voice_button"             # 直接跑一行
 *   echo "df -h" | node tools/vnc/run.js -                     # 从 stdin 读
 *   node tools/vnc/run.js --get /tmp/x.png preview/m1/x.png    # 从设备取文件
 *   node tools/vnc/run.js --put local.png /tmp/x.png           # 传到设备
 *
 * 实现约定（沿用本项目已验证的做法）：
 *   - 远端脚本 base64 传输，避免任何引号/中文编码拼装问题
 *   - 密码走 SSH_ASKPASS，不依赖 sshpass（Windows 上没有）
 */

const fs = require("fs")
const path = require("path")
const os = require("os")
const { spawnSync } = require("child_process")

const HOST = process.env.M1_HOST || "192.168.1.104"
const USER = process.env.M1_USER || "sunrise"
const PASS = process.env.M1_PASS || "sunrise"

let askpass = null
function env() {
  const e = Object.assign({}, process.env)
  if (PASS) {
    if (!askpass) {
      askpass = path.join(os.tmpdir(), "vgrun-" + Date.now() + ".cmd")
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

function run(script, timeoutSec) {
  const b64 = Buffer.from(script, "utf8").toString("base64")
  /*
   * ⚠️ 远端脚本路径必须**每次都不一样**。
   * 以前写死 /tmp/vgrun.sh：两条命令并发时会互相覆盖对方的脚本，
   * 表现是其中一条报出莫名其妙的语法错误（实测踩过：后台跑着解码实验，
   * 前台又发了一条查询，前者的 stderr 里出现了后者那行 grep）。
   */
  const tmp = "/tmp/vgrun-" + process.pid + "-" + Date.now() + ".sh"
  const cmd = "echo " + b64 + " | base64 -d > " + tmp + " && bash " + tmp + "; rc=$?; rm -f " + tmp + "; exit $rc"
  const r = spawnSync("ssh", OPTS.concat([USER + "@" + HOST, cmd]), {
    encoding: "utf8",
    timeout: (timeoutSec || 120) * 1000,
    env: env(),
    maxBuffer: 32 * 1024 * 1024
  })
  const out = String(r.stdout || "")
  const err = String(r.stderr || "")
  return { out: out, err: err, status: r.status }
}

function main() {
  const args = process.argv.slice(2)
  let script = ""
  let timeout = 120
  let get = null
  let put = null

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--file") {
      script = fs.readFileSync(args[++i], "utf8")
    } else if (args[i] === "--timeout") {
      timeout = parseInt(args[++i], 10)
    } else if (args[i] === "--get") {
      get = [args[++i], args[++i]]
    } else if (args[i] === "--put") {
      put = [args[++i], args[++i]]
    } else if (args[i] === "-") {
      script = fs.readFileSync(0, "utf8")
    } else {
      script = args[i]
    }
  }

  // 文件传输：scp 同样要走 askpass（否则会卡在密码提示直到超时）
  if (get || put) {
    const pair = get || put
    const from = get ? USER + "@" + HOST + ":" + pair[0] : pair[0]
    const to = get ? pair[1] : USER + "@" + HOST + ":" + pair[1]
    const r = spawnSync("scp", OPTS.concat([from, to]), {
      encoding: "utf8", timeout: timeout * 1000, env: env()
    })
    if (r.status !== 0) {
      console.error("[scp 失败] " + String(r.stderr || r.error || ""))
    } else {
      console.log("[scp ok] " + pair[0] + " <-> " + pair[1])
    }
    if (askpass) { try { fs.unlinkSync(askpass) } catch (e) {} }
    process.exit(r.status === 0 ? 0 : 1)
  }

  if (!script.trim()) {
    console.error("用法：node tools/vnc/run.js \"<bash 命令>\" | --file <脚本> | -  (stdin)")
    process.exit(2)
  }

  const r = run(script, timeout)
  process.stdout.write(r.out)
  if (r.err) {
    process.stdout.write("\n[stderr] " + r.err)
  }
  if (askpass) { try { fs.unlinkSync(askpass) } catch (e) {} }
  process.exit(r.status === null ? 1 : r.status)
}

main()
