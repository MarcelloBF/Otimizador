# Gera dist\Otimizador.exe (arquivo único, pede administrador ao abrir)
Set-Location $PSScriptRoot
if (-not (Test-Path .venv\Scripts\python.exe)) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin `
    --name Otimizador --collect-data customtkinter main.py
Write-Host "Pronto: $PSScriptRoot\dist\Otimizador.exe"
