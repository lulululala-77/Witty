@echo off
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Virtual environment Python not found: %PYTHON%
    pause
    exit /b 1
)
start "JevChat Embedding Server" /min cmd /k ""%PYTHON%" embedding_server.py"
echo Embedding server started in a minimized window.
