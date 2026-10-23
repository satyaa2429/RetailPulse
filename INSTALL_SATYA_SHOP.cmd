@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_SATYA_SHOP.ps1"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_SATYA_SHOP.ps1" -SourceData "%~f1"
)
if errorlevel 1 (
    echo Setup did not finish. Read the message above and try again.
    pause
    exit /b 1
)
exit /b 0
