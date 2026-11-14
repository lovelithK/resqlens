@echo off
REM ResQLens backend (Starlette/uvicorn) on http://localhost:8000  - API docs at /docs
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "backend\venv\Scripts\python.exe" (echo [ERROR] backend\venv missing - run setup.bat first. & pause & exit /b 1)
if not exist ".env" (echo [ERROR] .env missing - run setup.bat first. & pause & exit /b 1)
call "backend\venv\Scripts\activate.bat"
cd backend
echo Checking database connection...
python -m scripts.check_db
if errorlevel 1 (
  echo.
  echo [ERROR] Database check failed. Is MySQL Server running and is DB_PASSWORD in .env correct?
  echo         See docs\TROUBLESHOOTING.md
  pause
  exit /b 1
)
echo.
echo Backend:  http://localhost:8000      API docs: http://localhost:8000/docs
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
if errorlevel 1 (echo [ERROR] Backend stopped with an error ^(port 8000 in use? see docs\TROUBLESHOOTING.md^). & pause)
