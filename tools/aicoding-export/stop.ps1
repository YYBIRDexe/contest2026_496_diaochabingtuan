Remove-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'VelaGuardProjectLogArchive' -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'VelaGuard-AICoding-Watchdog' -Confirm:$false -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "name = 'pythonw.exe'" | Where-Object { $_.CommandLine -like '*aicoding-export*project_archive.py*--watch*' } | ForEach-Object { Stop-Process -Id $_.ProcessId }
