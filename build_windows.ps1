$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.build-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  python -m venv '.build-venv'
  if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}

& $python -m pip install -e '.[desktop,build]'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }

$originalPath = $env:PATH
$system32 = Join-Path $env:WINDIR 'System32'
$env:PATH = (($originalPath -split ';' | Where-Object {
  $_ -and ((-not (Test-Path -LiteralPath (Join-Path $_ 'icuuc.dll'))) -or ($_ -ieq $system32))
}) -join ';')
try {
  & $python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name ScorePartsAssistant `
    --collect-data verovio --collect-binaries verovio `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtWebEngineQuick `
    desktop_entry.py
} finally {
  $env:PATH = $originalPath
}
if ($LASTEXITCODE -ne 0) { throw 'Windows package build failed.' }

$runtimePath = $env:PATH
$env:PATH = "$system32;$env:WINDIR"
$env:QT_QPA_PLATFORM = 'offscreen'
try {
  $selfTest = Start-Process -FilePath (Join-Path $PSScriptRoot 'dist\ScorePartsAssistant\ScorePartsAssistant.exe') `
    -ArgumentList '--self-test' -WorkingDirectory $env:TEMP -WindowStyle Hidden -Wait -PassThru
} finally {
  $env:PATH = $runtimePath
  Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
}
if ($selfTest.ExitCode -ne 0) { throw "Packaged app self-test failed with exit code $($selfTest.ExitCode)." }

& $python '.\tools\collect_licenses.py' '.\dist\ScorePartsAssistant\THIRD_PARTY_LICENSES'
if ($LASTEXITCODE -ne 0) { throw 'Third-party license collection failed.' }

$package = Join-Path $PSScriptRoot 'dist\ScorePartsAssistant-Windows.zip'
Compress-Archive -Path '.\dist\ScorePartsAssistant' -DestinationPath $package -Force
Write-Output "Built: $package"
