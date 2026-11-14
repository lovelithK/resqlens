@echo off
REM One-time MySQL setup: creates resqlens_db, resqlens_test and user resqlens_app,
REM then saves the app password in .env (hidden input; nothing is printed or stored elsewhere).
cd /d "%~dp0..\backend"
if not exist "venv\Scripts\python.exe" (echo [ERROR] Run setup.bat first. & pause & exit /b 1)
call venv\Scripts\activate.bat
python -m scripts.setup_mysql
echo.
pause
