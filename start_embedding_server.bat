@echo off
cd /d "%~dp0"
title JevChat Embedding Server
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Virtual environment Python not found: %PYTHON%
    pause
    exit /b 1
)
"%PYTHON%" embedding_server.py
pause
