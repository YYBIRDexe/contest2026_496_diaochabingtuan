# vg.ps1 -- VelaGuard device helper.  ASCII ONLY (PowerShell 5.1 reads .ps1 as GBK
# without a BOM, so non-ASCII text here would break parsing -- keep it English).
#
# Why this exists: this PC has NO ~/.ssh/config, and the DEFAULT identity under
# C:\Users\Demo.01\.ssh\ is NOT authorized on the device.  Only the runtime key works:
#     F:\xiaomiaiot\runtime\credentials\id_ed25519
# so a plain `ssh sunrise@192.168.1.104` fails with "Permission denied (publickey,password)".
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File <this file> status
#   powershell -ExecutionPolicy Bypass -File <this file> reset     # back to clean start screen
#   powershell -ExecutionPolicy Bypass -File <this file> start
#   powershell -ExecutionPolicy Bypass -File <this file> stop
#   powershell -ExecutionPolicy Bypass -File <this file> legacy    # restore the 8123 live board
#   powershell -ExecutionPolicy Bypass -File <this file> shot      # grab E5 screen to _tmp
#   powershell -ExecutionPolicy Bypass -File <this file> ssh "any command"
#
# NOTE on quoting: remote commands below are single-quoted PowerShell strings with
# NO inner double quotes -- Windows PowerShell strips inner double quotes when it
# hands arguments to native ssh.exe, which corrupts remote commands.

param(
    [Parameter(Position = 0)][string]$Action = 'status',
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest
)

$ErrorActionPreference = 'Continue'
$Key    = 'F:\xiaomiaiot\runtime\credentials\id_ed25519'
$KHF    = 'F:\xiaomiaiot\runtime\credentials\known_hosts'
$Dev    = 'sunrise@192.168.1.104'
$OutDir = 'F:\xiaomiaiot\_tmp\e5-check'

$sshBase = @('-i', $Key, '-o', "UserKnownHostsFile=$KHF", '-o', 'StrictHostKeyChecking=no',
             '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', $Dev)

function Invoke-Dev([string]$RemoteCommand) {
    & ssh @sshBase $RemoteCommand
}

$StatusCmd = @'
echo --- device ---
hostname
date
echo --- demo page 8126 ---
curl -sI http://127.0.0.1:8126/demo-e5.html
echo --- listening 812x ---
ss -ltn
echo --- firefox procs ---
pgrep -c firefox
echo --- touch device ---
DISPLAY=:0 xinput list
'@ -replace "`r", ''

switch ($Action) {
    'status' {
        $ok = (Test-NetConnection -ComputerName '192.168.1.104' -Port 22 -WarningAction SilentlyContinue).TcpTestSucceeded
        if (-not $ok) {
            Write-Host 'Device 192.168.1.104:22 unreachable -- check cable / U2P power' -ForegroundColor Red
            exit 1
        }
        Invoke-Dev $StatusCmd
    }
    'reset'  {
        # Two layers, on purpose:
        #   1) the car-side executor (so cars stop and state goes back to idle)
        #   2) the demo page (reloads the kiosk)
        # Doing only the page reload leaves the executor holding the last round.
        Invoke-Dev 'curl -s -X POST --max-time 20 http://127.0.0.1:8127/patrol/reset; echo; bash ~/velaguard/demo/reset.sh'
    }
    'patrol' { Invoke-Dev 'bash ~/velaguard/demo/start-patrol.sh' }
    'patrol-status' {
        Invoke-Dev 'curl -s --max-time 5 http://127.0.0.1:8127/patrol/status | python3 -m json.tool | head -40'
    }
    'patrol-stop' { Invoke-Dev 'curl -s -X POST --max-time 20 http://127.0.0.1:8127/patrol/stop' }
    'clearance' { Invoke-Dev 'python3 /tmp/check_clearance.py 2>/dev/null || echo "(check_clearance.py not on device)"' }
    'start'  { Invoke-Dev 'bash ~/velaguard/demo/run-demo.sh' }
    'stop'   { Invoke-Dev 'bash ~/velaguard/demo/run-demo.sh --stop' }
    'legacy' { Invoke-Dev 'bash ~/velaguard/demo/run-demo.sh --stop; bash ~/velaguard/linux/start.sh --serve' }
    'shot' {
        New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
        # No ImageMagick on the device: xwd always, then convert locally with the
        # pure-python converter that ships next to this script.
        Invoke-Dev 'DISPLAY=:0 xwd -root -silent -out /tmp/vg-shot.xwd'
        & scp -i $Key -o "UserKnownHostsFile=$KHF" -o StrictHostKeyChecking=no "${Dev}:/tmp/vg-shot.xwd" "$OutDir\e5-now.xwd" 2>$null
        $conv = Join-Path $PSScriptRoot 'xwd2png.py'
        if ((Test-Path "$OutDir\e5-now.xwd") -and (Test-Path $conv)) {
            & python $conv "$OutDir\e5-now.xwd" "$OutDir\e5-now.png"
        } else {
            Write-Host 'capture failed (xwd2png.py missing?)' -ForegroundColor Yellow
        }
    }
    'ssh'   { Invoke-Dev ($Rest -join ' ') }
    default {
        Write-Host "Unknown action: $Action"
        Write-Host 'Available: status | reset | start | stop | shot'
        Write-Host '           patrol | patrol-status | patrol-stop | clearance'
        Write-Host '           legacy | ssh <cmd>'
    }
}
