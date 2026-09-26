$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    python -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    python -m PyInstaller --noconfirm --clean --windowed --onedir --name ORAlertBot --collect-submodules winrt run.py
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    Copy-Item -LiteralPath README.md -Destination dist\ORAlertBot\README.md
    Compress-Archive -Path dist\ORAlertBot -DestinationPath dist\ORAlertBot-windows-x64.zip -Force
} finally {
    Pop-Location
}
