@echo off
REM Convenience wrapper: first-time setup if needed, then start everything.
cd /d "%~dp0"
if not exist "backend\venv\Scripts\python.exe" call setup.bat || exit /b 1
call start_resqlens.bat
