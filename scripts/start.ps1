$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
$ffmpeg = Join-Path $root "tools\ffmpeg\ffmpeg.exe"
$frontend = Join-Path $root "frontend"

if (-not (Test-Path $python)) {
  Write-Error "Python virtualenv is missing. See README.md for the install steps."
}
if (-not (Test-Path $ffmpeg) -and -not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Write-Error "FFmpeg is missing. Run scripts\fetch-ffmpeg.ps1"
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
  Write-Error "Frontend dependencies are missing. Run npm install in the frontend folder."
}

$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npm) { Write-Error "npm was not found on PATH." }

Start-Process -FilePath $python -WorkingDirectory (Join-Path $root "backend") -ArgumentList @(
  "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1"
)
Start-Process -FilePath $npm -WorkingDirectory $frontend -ArgumentList @(
  "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"
)

Write-Host "Backend:  http://127.0.0.1:8000"
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "Stop both with scripts\stop.ps1 or by closing their windows."
