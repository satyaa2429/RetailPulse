@echo off
setlocal
cd /d "%~dp0"
set "SATYA_INSTALL=%LOCALAPPDATA%\SatyaShop"
if not exist "%SATYA_INSTALL%\installed.json" (
    call "%~dp0INSTALL_SATYA_SHOP.cmd" "%~1"
    exit /b
)
if not exist "%SATYA_INSTALL%\.venv\Scripts\pythonw.exe" (
    echo The installed app needs repair. Run INSTALL_SATYA_SHOP.cmd again.
    pause
    exit /b 1
)
start "" /d "%SATYA_INSTALL%\app" "%SATYA_INSTALL%\.venv\Scripts\pythonw.exe" -m retailpulse.desktop
exit /b 0
