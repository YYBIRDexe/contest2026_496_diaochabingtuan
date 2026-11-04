$archivePython = Join-Path $env:LOCALAPPDATA 'Programs/Python/Python314/pythonw.exe'
$archiveScript = Join-Path $PSScriptRoot 'project_archive.py'
$archiveAction = New-ScheduledTaskAction -Execute $archivePython -Argument ('"' + $archiveScript + '" --watch')
$archiveTrigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 1)
$archivePrincipal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$archiveTaskSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'VelaGuard-AICoding-Watchdog' -Action $archiveAction -Trigger $archiveTrigger -Principal $archivePrincipal -Settings $archiveTaskSettings -Description 'Maintain project-scoped Codex log collection and validated uploads to the user fork.' -Force -ErrorAction Stop | Out-Null
