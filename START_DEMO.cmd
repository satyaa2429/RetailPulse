@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\retailpulse-v4-ready" (
    call SETUP_RETAILPULSE.cmd
    if errorlevel 1 exit /b 1
)
if not exist "stream-demo\retailpulse.sqlite3" (
    .venv\Scripts\python.exe -m retailpulse --data-dir stream-demo demo
    if errorlevel 1 goto fail
)
echo Opening the DEMO database. These records are examples.
echo Keep this window open while using RetailPulse.
.venv\Scripts\python.exe -m retailpulse --data-dir stream-demo serve --open --find-port
if errorlevel 1 goto fail
exit /b 0
:fail
echo The demo could not start. Review the error above.
pause
exit /b 1
