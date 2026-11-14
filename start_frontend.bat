@echo off
REM ResQLens frontend dev server on http://localhost:5173 (live reload, /api proxied to :8000)
setlocal EnableExtensions
cd /d "%~dp0frontend"
if not exist "node_modules" (echo [ERROR] frontend\node_modules missing - run setup.bat first. & pause & exit /b 1)
call npm run dev -- --host 127.0.0.1 --port 5173
if errorlevel 1 (echo [ERROR] Frontend dev server stopped with an error ^(see above^). & pause)
