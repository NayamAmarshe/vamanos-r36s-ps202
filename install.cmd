@echo off
rem vamanOS for R36S PS202 - Windows launcher.
rem Requires Python 3 and adb. See README.md.
setlocal
set "SCRIPT_DIR=%~dp0"

rem Prefer the launcher on Microsoft Store/`py`, then `python`.
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 "%SCRIPT_DIR%vamanos_installer.py" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  python "%SCRIPT_DIR%vamanos_installer.py" %*
  exit /b %ERRORLEVEL%
)

echo Python 3 is required but was not found on PATH.
exit /b 2
