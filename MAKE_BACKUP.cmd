@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\retailpulse-v4-ready" (
    call SETUP_RETAILPULSE.cmd
    if errorlevel 1 exit /b 1
)
set "RP_DATA_DIR=shop-data"
if not "%~1"=="" set "RP_DATA_DIR=%~1"
if not exist "%RP_DATA_DIR%\retailpulse.sqlite3" (
    echo No shop database was found. Start your shop first.
    pause
    exit /b 1
)
.venv\Scripts\python.exe -m retailpulse --data-dir "%RP_DATA_DIR%" backup
pause
