@echo off
REM Read-only environment inspection -> logs\environment_report.txt (installs/changes nothing)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\inspect_environment.ps1"
echo.
pause
