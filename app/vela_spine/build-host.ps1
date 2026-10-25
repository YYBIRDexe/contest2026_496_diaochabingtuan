$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$out = Join-Path $root 'build'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installation) { throw 'MSVC C compiler not installed' }
$vcvars = Join-Path $installation 'VC/Auxiliary/Build/vcvars64.bat'
$batch = Join-Path $out 'compile.cmd'
@"
@echo off
call "$vcvars" >nul
if errorlevel 1 exit /b 1
cl /nologo /W4 /WX /TC /LD /O2 ../native/spine.c /Fospine.obj /link /OUT:spine.dll
"@ | Set-Content -LiteralPath $batch -Encoding ascii
Push-Location $out
try { & cmd /d /c $batch; if ($LASTEXITCODE -ne 0) { throw 'C build failed' } }
finally { Pop-Location }
