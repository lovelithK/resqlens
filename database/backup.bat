@echo off
REM Timestamped MySQL backup of resqlens_db (prompts for the root password).
setlocal
cd /d "%~dp0"
if not exist backups mkdir backups
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set TS=%%t
where mysqldump >nul 2>nul
if errorlevel 1 (
  set "MYSQLDUMP=C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe"
  if exist "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe" set "MYSQLDUMP=C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe"
) else (
  set "MYSQLDUMP=mysqldump"
)
"%MYSQLDUMP%" -u root -p --single-transaction --routines resqlens_db > "backups\resqlens_db_%TS%.sql"
if errorlevel 1 ( echo Backup FAILED & exit /b 1 )
echo Backup written to database\backups\resqlens_db_%TS%.sql
