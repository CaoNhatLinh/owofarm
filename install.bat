@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
title Owofarm - Install
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(not ((3,12) <= sys.version_info[:2] < (3,16)))" >nul 2>&1
    if not errorlevel 1 goto ready
    echo Existing .venv is unavailable. Rename .venv and run this installer again.
    goto failed
)
for %%V in (3.15 3.14 3.13 3.12) do (
    py -%%V -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        py -%%V -m venv .venv
        goto created
    )
)
python -c "import sys; raise SystemExit(not ((3,12) <= sys.version_info[:2] < (3,16)))" >nul 2>&1
if errorlevel 1 (
    echo Install Python 3.15, 64-bit, from https://www.python.org/downloads/windows/
    echo Open a new CMD window, check py --version, then run this installer again.
    goto failed
)
python -m venv .venv
:created
if errorlevel 1 goto failed
:ready
git --version >nul 2>&1
if errorlevel 1 (
    echo Install Git for Windows from https://git-scm.com/download/win
    echo Reopen CMD after installation, then run install.bat again.
    goto failed
)
".venv\Scripts\python.exe" bootstrap.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements-windows.txt
if errorlevel 1 goto failed
echo.
echo Installed. Read HUONG_DAN_WINDOWS.md, run start.bat, then enter your token and channel in the local dashboard.
echo No accounts are started by this installer.
pause
exit /b 0
:failed
echo Installation stopped. Read the error above and HUONG_DAN_WINDOWS.md.
pause
exit /b 1
