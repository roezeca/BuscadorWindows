$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno. Instala Python 3.12 de 64 bits." }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las herramientas." }
& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Las pruebas fallaron; se detuvo la compilación." }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onefile --name BuscadorWindows --collect-all pypdfium2 --collect-all pypdfium2_raw launcher.py
if ($LASTEXITCODE -ne 0) { throw "No se pudo generar la aplicación." }
$reportPath = Join-Path (Get-Location) "dist\verificacion-windows.json"
if (Test-Path $reportPath) { Remove-Item $reportPath }
$process = Start-Process -FilePath ".\dist\BuscadorWindows.exe" -ArgumentList @("--self-test", ('"' + $reportPath + '"')) -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path $reportPath)) { throw "Falló la comprobación del ejecutable." }
$report = Get-Content $reportPath -Raw | ConvertFrom-Json
if ($report.status -ne "passed" -or -not $report.frozen) { throw "El ejecutable no pasó la verificación." }
Write-Host "Aplicación generada y verificada: dist\BuscadorWindows.exe"
Write-Host "Puedes copiar este único archivo; no requiere Python instalado."
