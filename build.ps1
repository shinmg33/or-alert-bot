$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    python -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    python -m PyInstaller --noconfirm --clean --windowed --onedir --name "Alert Bot" --collect-submodules winrt run.py
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    Copy-Item -LiteralPath README.md -Destination 'dist\Alert Bot\README.md'
    Copy-Item -LiteralPath create-shortcut.ps1 -Destination 'dist\Alert Bot\create-shortcut.ps1'
    Compress-Archive -Path 'dist\Alert Bot' -DestinationPath dist\AlertBot-windows-x64.zip -Force
} finally {
    Pop-Location
}
