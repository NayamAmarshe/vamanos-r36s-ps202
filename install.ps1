# vamanOS for R36S PS202 - PowerShell launcher.
# Requires Python 3 and adb. See README.md.
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$pythonCommand = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $pythonCommand) {
    throw "Python 3 is required but was not found on PATH."
}

& $pythonCommand.Source (Join-Path $scriptDir "vamanos_installer.py") @args
exit $LASTEXITCODE
