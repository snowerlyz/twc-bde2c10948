@echo off
cd /d "%~dp0"
title TW Compass - desktop shortcut
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\make_shortcut.ps1"
echo.
pause
