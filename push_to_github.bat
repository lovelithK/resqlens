@echo off
REM Push the local ResQLens commits to https://github.com/lovelithK/resqlens (private repo).
REM Writes logs\push_report.txt. Never pushes .env (re-checked below).
setlocal EnableExtensions
cd /d "%~dp0"
if not exist logs mkdir logs
set "REMOTE=https://github.com/lovelithK/resqlens.git"
set "REPORT=logs\push_report.txt"
echo ResQLens push report > "%REPORT%"
git ls-files | findstr /i /r "^\.env$ \.db$ venv/ node_modules/" >nul && (
  echo [STOP] A secret or local file is tracked by Git - NOT pushing.>> "%REPORT%"
  type "%REPORT%" & pause & exit /b 1
)
git status --porcelain | findstr /r "." >nul && echo [NOTE] There are uncommitted changes; only commits are pushed.>> "%REPORT%"
git remote get-url origin >nul 2>nul && (git remote set-url origin "%REMOTE%") || (git remote add origin "%REMOTE%")
echo Remote: %REMOTE%>> "%REPORT%"
REM Commit this script itself if it is new or changed (secret check already passed above)
git add push_to_github.bat
git diff --cached --quiet || git commit -q -m "Add GitHub push script" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_011HWv34PhvnHGbiigAWCNov"
REM GitHub created the repo with its own one-line README: join the histories, keeping the full local README
git fetch -q origin >> "%REPORT%" 2>&1
git rev-parse -q --verify origin/main >nul 2>nul && (
  git merge-base --is-ancestor origin/main HEAD || (
    git merge -q --allow-unrelated-histories -X ours --no-edit origin/main -m "Merge GitHub's initial commit (keep the full local README)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_011HWv34PhvnHGbiigAWCNov" >> "%REPORT%" 2>&1 || (
      git merge --abort >nul 2>nul
      echo [ERROR] Could not merge GitHub's initial commit - nothing pushed.>> "%REPORT%"
      type "%REPORT%" & pause & exit /b 1
    )
    echo [OK] Merged GitHub's initial README commit; local README kept.>> "%REPORT%"
  )
)
echo.
echo  Pushing to %REMOTE%
echo  If a GitHub sign-in window opens, sign in as lovelithK and approve.
echo.
git push -u origin HEAD:main >> "%REPORT%" 2>&1
if errorlevel 1 (
  echo [ERROR] Push failed - see below.>> "%REPORT%"
  type "%REPORT%"
  echo.
  echo  Does the empty repo exist at https://github.com/lovelithK/resqlens ? Send logs\push_report.txt to Claude.
  pause & exit /b 1
)
echo [OK] Pushed:>> "%REPORT%"
git log --oneline -5 >> "%REPORT%"
type "%REPORT%"
echo.
echo  Done: https://github.com/lovelithK/resqlens
pause
