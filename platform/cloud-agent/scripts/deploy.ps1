#Requires -Version 5.1
<#
Deploy the cloud agent from this workspace to the platform over the existing
strict SSH key.  The script:
  1. runs the local unit tests (unless -SkipTests),
  2. packages platform/cloud-agent into a tar.gz without secrets or state,
  3. copies it to /tmp and runs scripts/remote-install.sh as the SSH user,
  4. installs and enables the user systemd unit velaguard-cloud-agent.service
     and queries /api/health,
  5. prints a no-secret summary.

It never copies the API key back to this workspace and never overwrites an
existing ~/.config/velaguard-cloud-agent/cloud-agent.env on the platform.  If
no key is configured there, the service is deployed in the unconfigured state
and POST /api/chat returns 503.

ASCII only on purpose: Windows PowerShell 5.1 reads UTF-8 without BOM as ANSI.
#>
[CmdletBinding()]
param(
    [string]$TargetHost = "192.168.137.134",
    [string]$UserName = "sunrise",
    [string]$KeyPath = "F:/xiaomiaiot/runtime/credentials/id_ed25519",
    [string]$KnownHostsPath = "F:/xiaomiaiot/runtime/credentials/known_hosts",
    [string]$HostKeyAlias = "192.168.137.134",
    [string]$BindAddress = "192.168.137.1",
    [string]$RemoteDir = "/home/sunrise/cloud-agent",
    [int]$Port = 8130,
    [string]$ListenHost = "0.0.0.0",
    [string]$LocalPython = "python",
    [switch]$DryRun,
    [switch]$SkipTests,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PlatformRoot = Split-Path -Parent $AppRoot
$SshExe = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$ScpExe = Join-Path $env:WINDIR "System32\OpenSSH\scp.exe"
$TarExe = Join-Path $env:WINDIR "System32\tar.exe"

function Assert-FileExists([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -le 0) {
        throw "$Label is empty: $Path"
    }
}

function Assert-SafeValue([string]$Value, [string]$Pattern, [string]$Label) {
    if ($Value -notmatch $Pattern) {
        throw "$Label contains unsupported characters: $Value"
    }
}

function Get-SshArgs {
    $result = @()
    if ($BindAddress) {
        $result += @("-b", $BindAddress)
    }
    $result += @(
        "-i", $KeyPath,
        "-o", "UserKnownHostsFile=$KnownHostsPath",
        "-o", "HostKeyAlias=$HostKeyAlias",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=8",
        "-o", "ServerAliveInterval=5",
        "-o", "ServerAliveCountMax=3"
    )
    return $result
}

function Get-ScpArgs {
    $result = @()
    if ($BindAddress) {
        $result += @("-o", "BindAddress=$BindAddress")
    }
    $result += @(
        "-i", $KeyPath,
        "-o", "UserKnownHostsFile=$KnownHostsPath",
        "-o", "HostKeyAlias=$HostKeyAlias",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=8"
    )
    return $result
}

function Invoke-Remote([string]$Command) {
    $sshArgs = Get-SshArgs
    $sshArgs += @("$UserName@$TargetHost", $Command)
    $output = @(& $SshExe @sshArgs)
    if ($LASTEXITCODE -ne 0) {
        throw "remote command failed with exit code $LASTEXITCODE"
    }
    return $output
}

Assert-SafeValue $TargetHost '^[A-Za-z0-9._:-]+$' "TargetHost"
Assert-SafeValue $UserName '^[A-Za-z0-9._-]+$' "UserName"
Assert-SafeValue $HostKeyAlias '^[A-Za-z0-9._:-]+$' "HostKeyAlias"
if ($BindAddress) {
    Assert-SafeValue $BindAddress '^[A-Za-z0-9.:]+$' "BindAddress"
}
Assert-SafeValue $RemoteDir '^/[A-Za-z0-9._/-]+$' "RemoteDir"
Assert-SafeValue $ListenHost '^[A-Za-z0-9.:-]+$' "ListenHost"
if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535"
}

if (-not (Test-Path -LiteralPath $SshExe)) { throw "ssh.exe not found: $SshExe" }
if (-not (Test-Path -LiteralPath $ScpExe)) { throw "scp.exe not found: $ScpExe" }
if (-not (Test-Path -LiteralPath $TarExe)) { throw "tar.exe not found: $TarExe" }
Assert-FileExists $KeyPath "SSH private key"
Assert-FileExists $KnownHostsPath "SSH known_hosts"

Write-Host "App root : $AppRoot"
Write-Host "Target   : $UserName@$TargetHost (HostKeyAlias=$HostKeyAlias)"
Write-Host "Remote   : $RemoteDir  port=$Port listen=$ListenHost"
Write-Host "Key      : $KeyPath (not read or printed)"

if ($DryRun) {
    Write-Host ""
    Write-Host "DRY RUN: no tests, packaging, upload, or remote command executed."
    Write-Host "Local test command: $LocalPython -m unittest discover -s tests -t . -v (cwd=$AppRoot)"
    Write-Host "Remote install command: bash /tmp/cloud-agent-stage/cloud-agent/scripts/remote-install.sh --staging /tmp/cloud-agent-stage/cloud-agent --app-dir '$RemoteDir' --host '$ListenHost' --port $Port"
    Write-Host "The existing environment file on the platform is never printed or overwritten."
    exit 0
}

if (-not $SkipTests) {
    Write-Host ""
    Write-Host "Running local tests..."
    Push-Location $AppRoot
    try {
        & $LocalPython -m unittest discover -s tests -t . -v
        if ($LASTEXITCODE -ne 0) {
            throw "local unit tests failed with exit code $LASTEXITCODE"
        }
        & $LocalPython -m compileall -q cloud_agent app.py
        if ($LASTEXITCODE -ne 0) {
            throw "compileall failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Warning "Skipping local tests at your request."
}

$deployDir = Join-Path $AppRoot ".deploy"
New-Item -ItemType Directory -Force -Path $deployDir | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")
$archive = Join-Path $deployDir ("cloud-agent-" + $stamp + ".tar.gz")
$remoteTar = "/tmp/cloud-agent-" + $stamp + ".tar.gz"

try {
    Write-Host ""
    Write-Host "Packaging source (excludes secrets, env files, state, caches)..."
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force
    }
    $tarArgs = @(
        "-czf", $archive,
        "--exclude", "cloud-agent/.deploy",
        "--exclude", "cloud-agent/.env",
        "--exclude", "*.env",
        "--exclude", "cloud-agent/config/*.env",
        "--exclude", "*.key",
        "--exclude", "cloud-agent/config/*.key",
        "--exclude", "cloud-agent/var",
        "--exclude", "*/state",
        "--exclude", "*/__pycache__",
        "--exclude", "*.pyc",
        "--exclude", ".pytest_cache",
        "-C", $PlatformRoot,
        "cloud-agent"
    )
    & $TarExe @tarArgs
    if ($LASTEXITCODE -ne 0) {
        throw "tar failed with exit code $LASTEXITCODE"
    }
    $entries = @(& $TarExe -tzf $archive)
    if ($LASTEXITCODE -ne 0) {
        throw "tar listing failed with exit code $LASTEXITCODE"
    }
    $forbidden = @($entries | Where-Object {
        $_ -match '\.env$' -or
        $_ -match '\.key$' -or
        $_ -match '(^|/)var/' -or
        $_ -match '(^|/)state/' -or
        $_ -match '__pycache__' -or
        $_ -match '\.pyc$' -or
        $_ -match '\.pytest_cache'
    })
    if ($forbidden.Count -gt 0) {
        throw ("archive contains forbidden paths: " + ($forbidden -join ", "))
    }
    Assert-FileExists $archive "deployment archive"
    Write-Host ("Archive  : {0} ({1} bytes)" -f $archive, (Get-Item -LiteralPath $archive).Length)

    Write-Host ""
    Write-Host "Checking platform Python..."
    $pythonVersion = Invoke-Remote "python3 --version"
    $pythonVersion | ForEach-Object { Write-Host ("  " + $_) }

    Write-Host "Uploading archive..."
    $scpArgs = Get-ScpArgs
    $scpArgs += @($archive, "$UserName@$TargetHost`:$remoteTar")
    & $ScpExe @scpArgs
    if ($LASTEXITCODE -ne 0) {
        throw "scp failed with exit code $LASTEXITCODE"
    }

    $installArgs = "--staging /tmp/cloud-agent-stage/cloud-agent --app-dir '$RemoteDir' --host '$ListenHost' --port $Port"
    if ($NoStart) {
        $installArgs += " --no-start"
    }
    $remoteCommand = "set -eu; rm -rf /tmp/cloud-agent-stage; mkdir -p /tmp/cloud-agent-stage; tar -xzf '$remoteTar' -C /tmp/cloud-agent-stage; bash /tmp/cloud-agent-stage/cloud-agent/scripts/remote-install.sh $installArgs"

    Write-Host "Installing on platform..."
    try {
        $installOutput = @(Invoke-Remote $remoteCommand)
    }
    finally {
        try {
            $cleanup = Invoke-Remote "rm -f '$remoteTar'"
        }
        catch {
            Write-Warning "Could not remove remote archive: $remoteTar"
        }
    }
    $installOutput | ForEach-Object { Write-Host $_ }

    if ($NoStart) {
        Write-Host ""
        Write-Host "DEPLOY_OK=1 (installed, not started)"
        exit 0
    }

    $healthLine = @($installOutput | Where-Object { $_ -like "HEALTH_JSON=*" }) | Select-Object -Last 1
    if (-not $healthLine) {
        throw "install finished but no HEALTH_JSON line was returned"
    }
    $healthJson = $healthLine.Substring("HEALTH_JSON=".Length)
    $health = $healthJson | ConvertFrom-Json

    Write-Host ""
    Write-Host "DEPLOY_OK=1"
    Write-Host ("URL=http://{0}:{1}/" -f $TargetHost, $Port)
    Write-Host ("SERVICE_VERSION={0}" -f $health.version)
    Write-Host ("LLM_CONFIGURED={0}" -f $health.configured)
    Write-Host ("SERVICE_STATUS={0}" -f $health.status)
    Write-Host "SERVICE=velaguard-cloud-agent.service (systemctl --user, enabled)"
    if (-not $health.configured) {
        Write-Host "NEXT=run the local hidden-input key window, or have the maintainer write /home/sunrise/.config/velaguard-cloud-agent/deepseek.key and restart velaguard-cloud-agent.service; chat stays unavailable until then."
    }
    Write-Host "RUN_SMOKE=python3 $RemoteDir/current/scripts/smoke_test.py --base-url http://127.0.0.1:$Port"
}
finally {
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force
    }
}
