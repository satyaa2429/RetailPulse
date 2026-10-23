@echo off
setlocal
cd /d "%~dp0"
if not exist "requirements.txt" (
    echo Extract the complete ZIP first. requirements.txt must be beside this script.
    goto fail
)
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto fail
)
echo Installing RetailPulse packages. Internet is needed for this setup step.
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
type nul > ".venv\retailpulse-v4-ready"
echo Setup complete.
exit /b 0
:fail
echo Setup failed. Review the error above. Python 3.11 to 3.13 and the py launcher are required.
pause
exit /b 1
