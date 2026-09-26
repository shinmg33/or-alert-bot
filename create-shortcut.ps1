$ErrorActionPreference = 'Stop'
$exePath = Join-Path $PSScriptRoot 'Alert Bot.exe'
if (-not (Test-Path -LiteralPath $exePath)) { throw 'Alert Bot.exe must be beside this script.' }
$desktopPath = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktopPath 'Alert Bot.lnk'
$wsh = New-Object -ComObject WScript.Shell
$link = $wsh.CreateShortcut($linkPath)
$link.TargetPath = $exePath
$link.WorkingDirectory = $PSScriptRoot
$link.Description = 'Alert Bot'
$link.Save()
