param([string]$SourceData = "")
$ErrorActionPreference = "Stop"
$sourceRoot = $PSScriptRoot
$installRoot = Join-Path $env:LOCALAPPDATA "SatyaShop"
$appRoot = Join-Path $installRoot "app"
$envRoot = Join-Path $installRoot ".venv"
$python = Join-Path $envRoot "Scripts\python.exe"
$pythonw = Join-Path $envRoot "Scripts\pythonw.exe"
$stage = Join-Path $installRoot ("app-next-" + [guid]::NewGuid().ToString("N"))
$previous = $null

try {
    if (!(Test-Path (Join-Path $sourceRoot "requirements.txt"))) {
        throw "Extract the complete project ZIP before running this installer."
    }
    Write-Host "Installing Satya Shop for your Windows account. No administrator access is needed."
    Write-Host "Finish pending bills and close your old shop windows before continuing."
    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null

    if (!(Test-Path $python)) {
        $oldPython = Join-Path $sourceRoot ".venv\Scripts\python.exe"
        if (Test-Path $oldPython) {
            & $oldPython -m venv $envRoot
        } else {
            $null = Get-Command py -ErrorAction Stop
            $version = $null
            foreach ($candidate in @("-3.13", "-3.12", "-3.11")) {
                try {
                    & py $candidate -c "import sys" 2>$null
                    if ($LASTEXITCODE -eq 0) { $version = $candidate; break }
                } catch { continue }
            }
            if (!$version) { throw "Install Python 3.11, 3.12 or 3.13 with the py launcher and Tcl/Tk, then run this installer again." }
            & py $version -m venv $envRoot
        }
        if ($LASTEXITCODE -ne 0) { throw "Could not create the shop's Python environment." }
    }
    & $python -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Satya Shop requires Python 3.11 to 3.13. Keep your records and install a supported Python version." }
    if (!(Test-Path $pythonw)) { throw "pythonw.exe is missing. Repair your Python installation and try again." }

    if (Test-Path (Join-Path $appRoot "retailpulse\desktop.py")) {
        Push-Location $appRoot
        try {
            & $python -m retailpulse.desktop --stop --quiet --home $installRoot
            if ($LASTEXITCODE -ne 0) { throw "The installed shop is still busy. Finish forecast training and retry the installer." }
        } finally { Pop-Location }
    }

    $requirements = Join-Path $sourceRoot "requirements.txt"
    $digest = (Get-FileHash $requirements -Algorithm SHA256).Hash
    $ready = Join-Path $envRoot "satya-requirements.txt"
    $savedDigest = if (Test-Path $ready) { (Get-Content $ready -Raw).Trim() } else { "" }
    if ($savedDigest -ne $digest) {
        Write-Host "Preparing the app packages. This setup step needs internet."
        & $python -m pip install -r $requirements
        if ($LASTEXITCODE -ne 0) { throw "Package installation failed. Check your internet connection and run the installer again." }
        Set-Content -Path $ready -Value $digest -Encoding ASCII
    }
    & $python -c "import numpy, pandas, sklearn, reportlab, openpyxl, tkinter; from zoneinfo import ZoneInfo; ZoneInfo('Asia/Kolkata')"
    if ($LASTEXITCODE -ne 0) { throw "A required package or Tcl/Tk is missing. Repair Python or delete only the satya-requirements.txt marker and run setup again." }

    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-Item (Join-Path $sourceRoot "retailpulse") -Destination $stage -Recurse
    Copy-Item $requirements -Destination $stage
    foreach ($guide in @("DESKTOP_APP.md", "SATYA_SHOP.md", "START_HERE.md")) {
        if (Test-Path (Join-Path $sourceRoot $guide)) { Copy-Item (Join-Path $sourceRoot $guide) -Destination $stage }
    }
    & $python -m compileall -q (Join-Path $stage "retailpulse")
    if ($LASTEXITCODE -ne 0) { throw "The new app files could not be prepared." }

    if (Test-Path $appRoot) {
        $previous = Join-Path $installRoot ("app-previous-" + [guid]::NewGuid().ToString("N"))
        Move-Item $appRoot $previous
    }
    Move-Item $stage $appRoot

    if (!$SourceData) { $SourceData = Join-Path $sourceRoot "shop-data" }
    $SourceData = [IO.Path]::GetFullPath($SourceData)
    Push-Location $appRoot
    try {
        & $python -m retailpulse.desktop --choose-data --source-data $SourceData --home $installRoot
        if ($LASTEXITCODE -ne 0) { throw "Shop data setup was not completed. Your original records were kept. Run the installer again." }
    } finally { Pop-Location }

    $shell = New-Object -ComObject WScript.Shell
    $desktop = $shell.SpecialFolders.Item("Desktop")
    $menu = Join-Path ([Environment]::GetFolderPath("Programs")) "Satya Shop"
    New-Item -ItemType Directory -Path $menu -Force | Out-Null
    $icon = (Join-Path $appRoot "retailpulse\static\satya-shop.ico") + ",0"
    foreach ($shortcutPath in @((Join-Path $desktop "Satya Shop.lnk"), (Join-Path $menu "Satya Shop.lnk"))) {
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $pythonw
        $shortcut.Arguments = '-m retailpulse.desktop --home "' + $installRoot + '"'
        $shortcut.WorkingDirectory = $appRoot
        $shortcut.IconLocation = $icon
        $shortcut.Description = "Open Satya Shop without VS Code"
        $shortcut.Save()
    }
    $quit = $shell.CreateShortcut((Join-Path $menu "Quit Satya Shop.lnk"))
    $quit.TargetPath = $pythonw
    $quit.Arguments = '-m retailpulse.desktop --stop --home "' + $installRoot + '"'
    $quit.WorkingDirectory = $appRoot
    $quit.IconLocation = $icon
    $quit.Save()
    $records = $shell.CreateShortcut((Join-Path $menu "Shop records and backups.lnk"))
    $records.TargetPath = Join-Path $env:WINDIR "explorer.exe"
    $records.Arguments = '"' + (Join-Path $installRoot "data") + '"'
    $records.Save()
    @{ installed = $true; installedAt = (Get-Date).ToString("o"); dataFolder = (Join-Path $installRoot "data") } | ConvertTo-Json | Set-Content -Path (Join-Path $installRoot "installed.json") -Encoding UTF8

    Write-Host "Installed. From now on, click the Satya Shop desktop icon. VS Code is not needed."
    Write-Host "Your records are kept at: $installRoot\data"
    Start-Process -FilePath $pythonw -ArgumentList '-m retailpulse.desktop' -WorkingDirectory $appRoot
    exit 0
} catch {
    Write-Host ("Setup could not finish: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "Your existing shop-data folder and installed records were kept."
    if ($previous -and !(Test-Path $appRoot) -and (Test-Path $previous)) { Move-Item $previous $appRoot }
    exit 1
} finally {
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
}
