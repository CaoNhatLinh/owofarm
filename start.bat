@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
title Owofarm
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" bootstrap.py
if errorlevel 1 goto failed
echo Stop with Ctrl+C. Keep this window open while using the dashboard.
".venv\Scripts\python.exe" -X utf8 -u -B uwu.py
if errorlevel 1 goto failed
exit /b 0
:missing
echo Run install.bat first.
:failed
echo Startup failed. Read the message above and HUONG_DAN_WINDOWS.md.
pause
exit /b 1
