$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "Instala Node.js 22 o posterior desde https://nodejs.org y abre una nueva terminal."
}
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv .venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    } else {
        throw "Instala Python 3.11 o posterior desde https://python.org."
    }
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno de Python." }
}
& ".\.venv\Scripts\python.exe" -m pip install -r backend/requirements.txt
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias de Python." }
& npm.cmd ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias de la interfaz." }
if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
}
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw "No se pudo compilar la interfaz." }
Write-Host ""
Write-Host "Instalacion completa. Configura TAVILY_API_KEY en .env y ejecuta .\start.ps1" -ForegroundColor Green
