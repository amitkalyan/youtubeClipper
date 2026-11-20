$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$marker = [regex]::Escape($root)
$procs = Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and $_.CommandLine -match $marker -and (
    $_.CommandLine -match "uvicorn" -or $_.CommandLine -match "vite"
  )
}
if (-not $procs) {
  Write-Host "No Clipper dev processes found."
  exit 0
}
foreach ($proc in $procs) {
  Write-Host "Stopping PID $($proc.ProcessId)"
  Stop-Process -Id $proc.ProcessId -Force
}
