$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    python -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    python -m PyInstaller --noconfirm --clean --windowed --onedir --name "Alert Bot" --collect-submodules winrt run.py
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    $report = Join-Path $PWD 'dist/selfcheck.json'
    $process = Start-Process -FilePath 'dist/Alert Bot/Alert Bot.exe' -ArgumentList @('--selfcheck', $report) -PassThru
    if (-not $process.WaitForExit(30000)) { $process.Kill(); throw 'EXE selfcheck timed out' }
    if (-not (Test-Path $report)) { throw 'EXE did not create selfcheck report' }
    $check = Get-Content $report -Raw | ConvertFrom-Json
    if ($check.error_type -or -not $check.tk -or -not $check.dpapi -or -not $check.input_structure -or -not $check.app_import) { throw "EXE selfcheck failed: $(Get-Content $report -Raw)" }
    Copy-Item -LiteralPath README.md -Destination 'dist\Alert Bot\README.md'
    Copy-Item -LiteralPath create-shortcut.ps1 -Destination 'dist\Alert Bot\create-shortcut.ps1'
    Compress-Archive -Path 'dist\Alert Bot' -DestinationPath dist\AlertBot-windows-x64.zip -Force
} finally {
    Pop-Location
}

