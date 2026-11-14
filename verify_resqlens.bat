@echo off
REM Automated verification -> logs\verification_report.txt
REM (database check, backend tests on SQLite + MySQL test DB, frontend build + type-check, live API smoke test)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\verify_resqlens.ps1"
echo.
pause
