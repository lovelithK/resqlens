@echo off
REM Commit all current changes (after secret checks) and push them to GitHub.
REM Uses tools\docs_commit_message.txt as the commit message. Writes logs\update_github_report.txt.
setlocal EnableExtensions
cd /d "%~dp0"
if not exist logs mkdir logs
set "REPORT=logs\update_github_report.txt"
echo ResQLens GitHub update report > "%REPORT%"
git add -A
set BAD=0
git diff --cached --name-only | findstr /i /r "\.env$ \.db$ venv/ node_modules/" >nul && (echo [STOP] a secret/local file is staged>> "%REPORT%" & set BAD=1)
git grep --cached -n -I -E "DB_PASSWORD=[A-Za-z0-9@!%%^*()_+.,:;~-]{6,}|SECRET_KEY=[A-Za-z0-9_-]{20,}" >nul 2>nul && (echo [STOP] a staged file contains a real password or secret key>> "%REPORT%" & set BAD=1)
if "%BAD%"=="1" (git reset -q & type "%REPORT%" & echo NOTHING committed or pushed. & pause & exit /b 1)
echo [OK] no secrets staged>> "%REPORT%"
echo == Files in this commit == >> "%REPORT%"
git diff --cached --name-only >> "%REPORT%"
git diff --cached --quiet || git commit -q -F "%~dp0tools\docs_commit_message.txt" >> "%REPORT%" 2>&1
git push -u origin HEAD:main >> "%REPORT%" 2>&1
if errorlevel 1 (echo [ERROR] Push failed>> "%REPORT%" & type "%REPORT%" & pause & exit /b 1)
echo [OK] Pushed:>> "%REPORT%"
git log --oneline -3 >> "%REPORT%"
type "%REPORT%"
echo.
echo  Done: https://github.com/lovelithK/resqlens  (Render redeploys automatically)
pause
