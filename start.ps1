param([switch]$Rebuild)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    throw "Ejecuta primero .\setup.ps1"
}
if ($Rebuild -or -not (Test-Path -LiteralPath "frontend\dist\index.html")) {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "No se pudo compilar la interfaz." }
}
if (Test-Path -LiteralPath "data\server-process.json") {
    & "$PSScriptRoot\stop.ps1"
}
$scoutPython = (Resolve-Path -LiteralPath ".venv\Scripts\python.exe").Path
$scoutProcess = Start-Process -FilePath $scoutPython -ArgumentList "-m","uvicorn","backend.main:app","--host","127.0.0.1","--port","8001" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "$PSScriptRoot\server.log" -RedirectStandardError "$PSScriptRoot\server-error.log" -PassThru
if ($scoutProcess.WaitForExit(1500)) {
    $scoutMessage = Get-Content -LiteralPath "$PSScriptRoot\server-error.log" -Raw
    throw "No se pudo iniciar el servidor. $scoutMessage"
}
New-Item -ItemType Directory -Path "$PSScriptRoot\data" -Force | Out-Null
$scoutRecord = @{
    Pid = $scoutProcess.Id
    StartedTicks = $scoutProcess.StartTime.ToUniversalTime().Ticks.ToString()
    Path = $scoutPython
}
$scoutRecord | ConvertTo-Json | Set-Content -LiteralPath "$PSScriptRoot\data\server-process.json" -Encoding UTF8
Write-Host "Kerna Client Research: http://127.0.0.1:8001" -ForegroundColor Green
Write-Host "Para detener: .\stop.ps1. Para reiniciar: .\start.ps1"
