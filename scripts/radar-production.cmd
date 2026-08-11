@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Radar production launcher: virtualenv Python not found at "%PYTHON_EXE%"
  exit /b 1
)
if not exist "%PROJECT_ROOT%\runtime-logs" mkdir "%PROJECT_ROOT%\runtime-logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "RADAR_TIMESTAMP=%%I"
set "RADAR_LOG_FILE=%PROJECT_ROOT%\runtime-logs\radar-%RADAR_TIMESTAMP%.log"
pushd "%PROJECT_ROOT%"
"%PYTHON_EXE%" -m radar.runner --production %* > "%RADAR_LOG_FILE%" 2>&1
set "RADAR_EXIT=%ERRORLEVEL%"
popd
exit /b %RADAR_EXIT%
