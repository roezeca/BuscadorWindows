$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno. Instala Python 3.12 de 64 bits." }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias." }
& .\.venv\Scripts\python.exe -m buscador
if ($LASTEXITCODE -ne 0) { throw "La aplicación terminó con un error." }
