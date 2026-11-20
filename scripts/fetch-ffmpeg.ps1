$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root "tools\ffmpeg"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$ffmpeg = Join-Path $dest "ffmpeg.exe"
$ffprobe = Join-Path $dest "ffprobe.exe"
if ((Test-Path $ffmpeg) -and (Test-Path $ffprobe)) {
  & $ffmpeg -version | Select-Object -First 1
  exit 0
}

$zip = Join-Path $root "tools\ffmpeg-essentials.zip"
Write-Host "Downloading FFmpeg essentials..."
& curl.exe -L --fail --retry 3 --retry-delay 2 -A "Mozilla/5.0" -o $zip "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
if ($LASTEXITCODE -ne 0) { throw "FFmpeg download failed: $LASTEXITCODE" }

$copy = Join-Path $root "tools\ffmpeg-essentials-copy.zip"
Copy-Item $zip $copy -Force
$extract = Join-Path $root "tools\ffmpeg-extract"
if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($copy, $extract)
$exe = Get-ChildItem -Path $extract -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $exe) { throw "ffmpeg.exe was not in the archive." }
Copy-Item (Join-Path $exe.DirectoryName "ffmpeg.exe") $dest -Force
Copy-Item (Join-Path $exe.DirectoryName "ffprobe.exe") $dest -Force
Remove-Item -Recurse -Force $extract
Remove-Item -Force $copy
Remove-Item -Force $zip -ErrorAction SilentlyContinue
& $ffmpeg -version | Select-Object -First 1
