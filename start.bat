@echo off
title Clip Factory Pro
cd /d "%~dp0"
set PYTHONPATH=.
echo Clip Factory Pro: http://127.0.0.1:8501
.venv\python.exe -m src.api_server
pause
