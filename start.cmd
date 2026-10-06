@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto install
".venv\Scripts\python.exe" -c "import bilibili_replay_downloader" >nul 2>&1
if not errorlevel 1 goto run

:install
call setup.cmd --no-pause
if errorlevel 1 (
    pause
    exit /b 1
)

:run
".venv\Scripts\python.exe" -m bilibili_replay_downloader %*
set "run_exit=%errorlevel%"
pause
exit /b %run_exit%
