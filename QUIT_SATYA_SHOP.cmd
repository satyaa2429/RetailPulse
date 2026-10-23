@echo off
setlocal
set "SATYA_INSTALL=%LOCALAPPDATA%\SatyaShop"
if not exist "%SATYA_INSTALL%\.venv\Scripts\pythonw.exe" (
    echo Satya Shop has not been installed yet.
    pause
    exit /b 1
)
start "" /d "%SATYA_INSTALL%\app" "%SATYA_INSTALL%\.venv\Scripts\pythonw.exe" -m retailpulse.desktop --stop
exit /b 0
