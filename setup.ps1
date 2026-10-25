$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.\chrome-win64\chrome.exe')) {
        throw 'Missing chrome-win64\chrome.exe'
    }
    New-Item -ItemType Directory -Force '.tmp' | Out-Null
    $oldTemp = $env:TEMP
    $oldTmp = $env:TMP
    $env:TEMP = Join-Path $PSScriptRoot '.tmp'
    $env:TMP = $env:TEMP
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'venv creation failed' }
    }
    & '.\.venv\Scripts\python.exe' -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw 'pip setup failed' }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'dependency installation failed' }
    Write-Host 'Ready. Run: .\.venv\Scripts\python.exe dybrowser.py serve'
} finally {
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
    Pop-Location
}
