$archivePython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\pythonw.exe'
$archiveScript = Join-Path $PSScriptRoot 'project_archive.py'
$archiveCommand = '"' + $archivePython + '" "' + $archiveScript + '" --watch'
Set-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'VelaGuardProjectLogArchive' -Value $archiveCommand
Start-Process -FilePath $archivePython -ArgumentList @(('"' + $archiveScript + '"'), '--watch') -WindowStyle Hidden
if (-not (Get-ScheduledTask -TaskName 'VelaGuard-AICoding-Watchdog' -ErrorAction SilentlyContinue)) {
    & (Join-Path $PSScriptRoot 'install-watchdog.ps1')
}
