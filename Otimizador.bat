@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Preparando o ambiente pela primeira vez...
  python -m venv .venv || (echo Instale o Python 3.10+ em python.org & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
start "" ".venv\Scripts\pythonw.exe" main.py
