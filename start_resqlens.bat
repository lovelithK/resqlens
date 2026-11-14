@echo off
REM ============================================================================
REM  Start the complete ResQLens development environment
REM    checks environment -> checks MySQL service -> backend (new window)
REM    -> waits for /api/health -> frontend (new window) -> opens browser
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
echo.
echo  Starting ResQLens
echo  -----------------
if not exist "backend\venv\Scripts\python.exe" (echo  [ERROR] Not set up yet - run setup.bat first. & pause & exit /b 1)
if not exist "frontend\node_modules" (echo  [ERROR] Frontend packages missing - run setup.bat first. & pause & exit /b 1)
if not exist ".env" (echo  [ERROR] .env missing - run setup.bat first. & pause & exit /b 1)

set "DB_ENGINE=sqlite"
for /f "usebackq tokens=1,* delims==" %%a in (".env") do if /i "%%a"=="DB_ENGINE" set "DB_ENGINE=%%b"
if /i "!DB_ENGINE!"=="mysql" (
  powershell -NoProfile -Command "if (Get-Service -Name 'MySQL*' -ErrorAction SilentlyContinue | Where-Object Status -eq 'Running') { exit 0 } else { exit 1 }"
  if errorlevel 1 (
    echo  [WARN] No running MySQL Windows service was found.
    echo         Start it: Win+R ^> services.msc ^> MySQL80 ^(or MySQL84^) ^> Start, then press a key.
    pause
  ) else (
    echo  [OK] MySQL service is running
  )
) else (
  echo  [OK] Using SQLite ^(DB_ENGINE=!DB_ENGINE!^)
)

start "ResQLens backend :8000" cmd /k call "%~dp0start_backend.bat"
echo  Waiting for the backend to answer on http://localhost:8000/api/health ...
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 60;$i++){ try { Invoke-RestMethod http://127.0.0.1:8000/api/health -TimeoutSec 2 | Out-Null; $ok=$true; break } catch { Start-Sleep -Seconds 1 } }; if($ok){exit 0}else{exit 1}"
if errorlevel 1 (
  echo  [ERROR] Backend did not start within 60 s - read the "ResQLens backend" window.
  pause
  exit /b 1
)
echo  [OK] Backend is up
start "ResQLens frontend :5173" cmd /k call "%~dp0start_frontend.bat"
timeout /t 3 /nobreak >nul
start "" http://localhost:5173
echo.
echo  ResQLens is running
echo    Frontend (dev, live reload) : http://localhost:5173
echo    Backend / production build   : http://localhost:8000
echo    API documentation            : http://localhost:8000/docs
echo    Health check                 : http://localhost:8000/api/health
echo    Demo login                   : demo@resqlens.dev / Demo@2026
echo.
echo  Close the two server windows ^(or press Ctrl+C in them^) to stop.
exit /b 0
