# Builds dist\ScreenRec\ScreenRec.exe (PyInstaller) and, if Inno Setup is
# installed, dist\ScreenRec-Setup-<version>.exe.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-FfmpegPath C:\path\ffmpeg.exe] [-RequireInstaller]
#
# -RequireInstaller fails the build when Inno Setup is missing instead of
# skipping the installer (the release workflow uses it).

param(
    [string]$FfmpegPath = "",
    [switch]$RequireInstaller
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $FfmpegPath) {
    $FfmpegPath = (Get-Command ffmpeg -ErrorAction Stop).Source
}
$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
Write-Host "ScreenRec $version, bundling ffmpeg from $FfmpegPath"

uv sync --group build
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

uv run --no-sync python packaging\make_icon.py
uv run --no-sync pyinstaller --noconfirm --clean --distpath dist --workpath build packaging\screenrec.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$ffmpegDir = "dist\ScreenRec\ffmpeg"
New-Item -ItemType Directory -Force $ffmpegDir | Out-Null
Copy-Item $FfmpegPath "$ffmpegDir\ffmpeg.exe" -Force
# The FFmpeg build is GPL-licensed; ship its license alongside it.
$license = Join-Path (Split-Path -Parent (Split-Path -Parent $FfmpegPath)) "LICENSE"
if (Test-Path $license) { Copy-Item $license "$ffmpegDir\LICENSE.txt" -Force }

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($iscc) {
    & $iscc "/DAppVersion=$version" packaging\installer.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} elseif ($RequireInstaller) {
    throw "Inno Setup 6 not found - can't build the installer"
} else {
    Write-Host "Inno Setup not found - skipped the installer; dist\ScreenRec is still usable as-is"
}
