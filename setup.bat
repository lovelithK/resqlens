@echo off
REM ============================================================================
REM  ResQLens - first-time setup (safe to re-run; never deletes your data)
REM    1. checks Python and Node.js
REM    2. creates backend\venv and installs Python packages
REM    3. creates .env from .env.example with a random SECRET_KEY (if missing)
REM    4. installs frontend packages and builds the production bundle
REM ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo  ResQLens setup
echo  --------------

where python >nul 2>nul || (echo [ERROR] Python not found on PATH. Install Python 3.10+ from https://www.python.org/ and tick "Add python.exe to PATH". & goto :fail)
where node >nul 2>nul || (echo [ERROR] Node.js not found on PATH. Install the LTS version from https://nodejs.org/ & goto :fail)
for /f "delims=" %%v in ('python --version 2^>^&1') do echo  [OK] %%v
for /f "delims=" %%v in ('node --version') do echo  [OK] Node.js %%v

echo.
echo  [1/4] Python virtual environment (backend\venv)
if not exist "backend\venv\Scripts\python.exe" (
  python -m venv backend\venv || (echo [ERROR] Could not create the virtual environment. & goto :fail)
)
call "backend\venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
echo  [2/4] Installing backend packages (requirements.txt)
pip install -r backend\requirements.txt || (echo [ERROR] pip install failed - see the messages above. & goto :fail)

echo  [3/4] Configuration file
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  for /f %%k in ('python -c "import secrets; print(secrets.token_urlsafe(48))"') do (
    powershell -NoProfile -Command "(Get-Content '.env') -replace '^SECRET_KEY=$','SECRET_KEY=%%k' | Set-Content -Encoding UTF8 '.env'"
  )
  echo  [OK] Created .env with a random SECRET_KEY.
  echo       ACTION: open .env and set DB_PASSWORD (see database\create_database.sql^)
) else (
  echo  [OK] .env already exists - left unchanged.
)

echo.
if exist "vscode-config\settings.json" (
  if not exist ".vscode\settings.json" (
    choice /c YN /m "  Install the VS Code workspace settings from vscode-config into .vscode"
    if not errorlevel 2 (
      xcopy /y /i /q "vscode-config\*.json" ".vscode\" >nul && echo  [OK] VS Code settings, tasks and debug configurations installed in .vscode
    ) else (
      echo  [SKIP] Left .vscode unchanged. See vscode-config\README.md
    )
  ) else (
    echo  [OK] .vscode\settings.json already exists - left unchanged. See vscode-config\README.md
  )
)

echo  [4/4] Frontend packages and production build
pushd frontend
call npm install || (popd & echo [ERROR] npm install failed. & goto :fail)
call npm run build || (popd & echo [ERROR] Frontend build failed. & goto :fail)
popd

echo.
echo  Setup complete.
echo  Next: 1) run database\create_database.sql in MySQL Workbench (once)
echo        2) put the app user's password in .env (DB_PASSWORD=...)
echo        3) start everything with start_resqlens.bat
echo.
exit /b 0

:fail
echo.
echo  Setup did not finish. Fix the error above and run setup.bat again.
exit /b 1
