@echo off
REM 1) Adds four sample projects and runs two simulations (logs\sample_data_report.txt)
REM 2) Commits all changes locally via commit_redesign.bat (secret checks first). Nothing is pushed.
setlocal EnableExtensions
cd /d "%~dp0"
if not exist logs mkdir logs
powershell -NoProfile -Command "try { Invoke-RestMethod http://127.0.0.1:8000/api/health -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo  Backend is not running - starting ResQLens first...
  call "%~dp0start_resqlens.bat"
  if errorlevel 1 exit /b 1
)
echo.
echo  == Adding sample projects and running simulations ==
"backend\venv\Scripts\python.exe" tools\add_sample_projects.py
if errorlevel 1 (
  echo  [ERROR] Sample data step failed - see the message above. Nothing was committed.
  pause
  exit /b 1
)
echo.
echo  == Committing changes ==
call "%~dp0commit_redesign.bat"
