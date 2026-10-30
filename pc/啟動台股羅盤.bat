@echo off
cd /d "%~dp0"
title TW Compass
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\open_if_running.ps1" && exit /b 0
if not exist "runtime\python\python.exe" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1"
if not exist "runtime\python\python.exe" (
  echo.
  echo [!] Python runtime is missing. Please check the internet connection and run this file again.
  pause
  exit /b 1
)
if not exist "runtime\ml_setup_done.txt" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup_ml.ps1"
set TWC_OPEN=1
"runtime\python\python.exe" -X utf8 "app\main.py" serve
echo.
pause
