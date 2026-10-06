@echo off
setlocal
cd /d "%~dp0"
python --version
if errorlevel 1 goto failed
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install --upgrade pip --retries 1 --timeout 20 --disable-pip-version-check
if errorlevel 1 goto direct_install
".venv\Scripts\python.exe" -m pip install . --retries 1 --timeout 20 --disable-pip-version-check
if errorlevel 1 goto direct_install
goto installed

:direct_install
echo Retrying installation with a direct connection for this process only...
set "NO_PROXY=*"
".venv\Scripts\python.exe" -m pip install --upgrade pip --retries 1 --timeout 20 --disable-pip-version-check
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install . --retries 1 --timeout 20 --disable-pip-version-check
if errorlevel 1 goto failed

:installed
echo Installation completed. Run start.cmd to download a replay.
if /I not "%~1"=="--no-pause" pause
exit /b 0

:failed
echo Installation failed. Python 3.10 or newer and an Internet connection are required.
if /I not "%~1"=="--no-pause" pause
exit /b 1
