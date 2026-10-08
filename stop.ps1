$ErrorActionPreference = "Stop"
$scoutRecordFile = Join-Path $PSScriptRoot "data\server-process.json"
if (-not (Test-Path -LiteralPath $scoutRecordFile)) {
    Write-Host "No hay un servidor iniciado por start.ps1."
    return
}
$scoutRecord = Get-Content -LiteralPath $scoutRecordFile -Raw | ConvertFrom-Json
$scoutOwnedProcess = Get-Process -Id ([int]$scoutRecord.Pid) -ErrorAction SilentlyContinue
if ($scoutOwnedProcess) {
    $scoutExpectedPath = (Resolve-Path -LiteralPath "$PSScriptRoot\.venv\Scripts\python.exe").Path
    if ($scoutOwnedProcess.Path -ne $scoutExpectedPath -or $scoutOwnedProcess.StartTime.ToUniversalTime().Ticks.ToString() -ne $scoutRecord.StartedTicks) {
        throw "El PID guardado no corresponde al servidor de este proyecto. No se ha detenido ningun proceso."
    }
    & taskkill.exe /PID $scoutOwnedProcess.Id /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo detener el servidor de este proyecto." }
}
Remove-Item -LiteralPath $scoutRecordFile
Write-Host "Servidor de Kerna Client Research detenido."
