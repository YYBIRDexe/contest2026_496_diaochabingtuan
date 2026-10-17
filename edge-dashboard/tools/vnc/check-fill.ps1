# Deterministic "is the screen filled?" check on a captured framebuffer image.
#
# Method: a letterboxed UI leaves near-uniform BLACK bands along the edges.
# We scan the outermost rows/columns and report the contiguous black band size
# on each side. If all four bands are ~0, the UI fills the framebuffer.
#
# This is objective, unlike eyeballing a photo of the panel.
#
# ASCII-only on purpose (PowerShell 5.1 reads .ps1 as ANSI).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\vnc\check-fill.ps1 -Src preview\m1\shot.png

param(
  [Parameter(Mandatory=$true)][string]$Src,
  [int]$BlackMax = 26
)

Add-Type -AssemblyName System.Drawing

if ([System.IO.Path]::IsPathRooted($Src)) {
  $srcAbs = $Src
} else {
  $srcAbs = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine((Get-Location).Path, $Src))
}
if (-not (Test-Path -LiteralPath $srcAbs)) {
  Write-Output "ERROR: not found: $srcAbs"
  exit 1
}

$img = [System.Drawing.Bitmap]::FromFile($srcAbs)
$W = $img.Width
$H = $img.Height
Write-Output ("image: {0}x{1}" -f $W, $H)

# A row/column is "black" if almost every sampled pixel is very dark.
function RowIsBlack($y) {
  $dark = 0; $n = 0
  for ($x = 0; $x -lt $W; $x += 4) {
    $c = $img.GetPixel($x, $y)
    $n++
    if ($c.R -le $BlackMax -and $c.G -le $BlackMax -and $c.B -le $BlackMax) { $dark++ }
  }
  return ($dark / [double]$n) -gt 0.97
}
function ColIsBlack($x) {
  $dark = 0; $n = 0
  for ($y = 0; $y -lt $H; $y += 4) {
    $c = $img.GetPixel($x, $y)
    $n++
    if ($c.R -le $BlackMax -and $c.G -le $BlackMax -and $c.B -le $BlackMax) { $dark++ }
  }
  return ($dark / [double]$n) -gt 0.97
}

$top = 0; while ($top -lt $H -and (RowIsBlack $top)) { $top++ }
$bottom = 0; while ($bottom -lt $H -and (RowIsBlack ($H - 1 - $bottom))) { $bottom++ }
$left = 0; while ($left -lt $W -and (ColIsBlack $left)) { $left++ }
$right = 0; while ($right -lt $W -and (ColIsBlack ($W - 1 - $right))) { $right++ }

$contentW = $W - $left - $right
$contentH = $H - $top - $bottom
$ratio = if ($contentH -gt 0) { $contentW / [double]$contentH } else { 0 }

Write-Output ""
Write-Output "=== black bands (letterbox / pillarbox) ==="
Write-Output ("  top    : {0} px" -f $top)
Write-Output ("  bottom : {0} px" -f $bottom)
Write-Output ("  left   : {0} px" -f $left)
Write-Output ("  right  : {0} px" -f $right)
Write-Output ""
Write-Output ("=== content area ===")
Write-Output ("  size   : {0}x{1}" -f $contentW, $contentH)
Write-Output ("  aspect : {0:N4}" -f $ratio)
Write-Output ""
$bandTotal = $top + $bottom + $left + $right
if ($bandTotal -le 4) {
  Write-Output "VERDICT: FILLED -- no letterboxing; the UI covers the whole screen."
} else {
  $pctW = ($left + $right) / [double]$W
  $pctH = ($top + $bottom) / [double]$H
  Write-Output ("VERDICT: NOT FILLED -- black bands present (width {0:P1}, height {1:P1} of screen)." -f $pctW, $pctH)
}

$img.Dispose()
