# Download the FFmpeg bundled into the Windows installer: Gyan.dev's
# "essentials" build (x264, ddagrab, NVENC/QSV/AMF included) from
# https://github.com/GyanD/codexffmpeg, pinned and checked against its SHA256.
# It is GPL-licensed; the zip's LICENSE comes along.
#
#   powershell -ExecutionPolicy Bypass -File packaging\fetch_ffmpeg.ps1 <out dir>
#     -> <out dir>\bin\ffmpeg.exe, <out dir>\LICENSE (where build.ps1 looks for it)

param(
    [Parameter(Mandatory = $true)][string]$OutDir
)

$ErrorActionPreference = "Stop"

$FfmpegVersion = "9.0.2"
$FfmpegName = "ffmpeg-$FfmpegVersion-essentials_build"
$FfmpegUrl = "https://github.com/GyanD/codexffmpeg/releases/download/$FfmpegVersion/$FfmpegName.zip"
$FfmpegSha256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory $tmp | Out-Null
try {
    $zip = Join-Path $tmp "ffmpeg.zip"
    # Invoke-WebRequest's progress bar makes large downloads many times slower.
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri $FfmpegUrl -OutFile $zip
    $hash = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    if ($hash -ne $FfmpegSha256) { throw "SHA256 mismatch for $FfmpegUrl`: got $hash" }

    Expand-Archive -Path $zip -DestinationPath $tmp
    if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
    Move-Item (Join-Path $tmp $FfmpegName) $OutDir
} finally {
    Remove-Item -Recurse -Force $tmp
}

& (Join-Path $OutDir "bin\ffmpeg.exe") -hide_banner -version | Select-Object -First 1
