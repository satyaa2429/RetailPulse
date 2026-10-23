@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\retailpulse-v4-ready" (
    call SETUP_RETAILPULSE.cmd
    if errorlevel 1 exit /b 1
)
echo Run START_DEMO.cmd first. This stream uses simulated demo sales only.
.venv\Scripts\python.exe -m retailpulse --data-dir stream-demo simulate --interval 2
if errorlevel 1 pause
