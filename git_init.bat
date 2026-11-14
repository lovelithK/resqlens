@echo off
REM Prepare the Git repository: init, stage, SECRET CHECKS, then ask before the first commit.
REM Writes logs\git_report.txt. Nothing is pushed anywhere.
setlocal EnableExtensions
cd /d "%~dp0"
if not exist logs mkdir logs
set "REPORT=logs\git_report.txt"
where git >nul 2>nul || (echo [ERROR] Git not found on PATH. & pause & exit /b 1)
if not exist ".git" (git init -b main >nul && echo [OK] Initialised a new Git repository ^(branch main^)) else (echo [OK] Existing Git repository found)
git add -A
echo ResQLens Git report > "%REPORT%"
echo. >> "%REPORT%"
echo == Secret / exclusion checks == >> "%REPORT%"
set BAD=0
for %%f in (.env backend\venv frontend\node_modules logs backend\resqlens.db) do (
  if exist "%%f" (
    git check-ignore -q "%%f" && (echo [OK] %%f is ignored>> "%REPORT%") || (echo [STOP] %%f is NOT ignored>> "%REPORT%" & set BAD=1)
  )
)
git diff --cached --name-only | findstr /i /r "\.env$ \.db$ venv\\ node_modules" >nul && (echo [STOP] a secret/local file is staged>> "%REPORT%" & set BAD=1)
git grep --cached -n -I -E "DB_PASSWORD=[A-Za-z0-9@!%%^*()_+.,:;~-]{6,}|SECRET_KEY=[A-Za-z0-9_-]{20,}" >nul 2>nul && (echo [STOP] a staged file contains a real password or secret key>> "%REPORT%" & set BAD=1)
if "%BAD%"=="0" echo [OK] no secrets staged>> "%REPORT%"
echo. >> "%REPORT%"
echo == Files staged for commit == >> "%REPORT%"
git diff --cached --name-only >> "%REPORT%"
for /f %%n in ('git diff --cached --name-only ^| find /c /v ""') do echo Total: %%n file^(s^)>> "%REPORT%"
type "%REPORT%"
echo.
if "%BAD%"=="1" (
  echo [STOP] Secret check failed - NOTHING committed. Send logs\git_report.txt to Claude.
  git reset -q
  pause
  exit /b 1
)
choice /c YN /m "Create the initial commit with these files"
if errorlevel 2 (echo No commit made.& echo. >> "%REPORT%"& echo == Commit skipped by user == >> "%REPORT%"& pause & exit /b 0)
git commit -q -F "%~dp0tools\initial_commit_message.txt"
if errorlevel 1 (echo [ERROR] Commit failed - is git user.name/user.email set?& pause & exit /b 1)
echo. >> "%REPORT%"
echo == Commit created == >> "%REPORT%"
git log --stat --oneline -1 | findstr /v /c:" | " >> "%REPORT%"
git status --short >> "%REPORT%"
echo [OK] Initial commit created:
git log --oneline -1
echo.
echo Nothing was pushed. To publish on GitHub later, create an EMPTY private repo and tell Claude its URL.
pause
