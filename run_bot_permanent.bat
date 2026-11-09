@echo off
title Lords Mobile GF Bot - Auto Restart
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

:loop
echo [%date% %time%] Checking for existing bot instance...
powershell -NoProfile -Command "exit @(gwmi Win32_Process -Filter \"Name='python.exe'\" | ? { $_.CommandLine -like '*bot.py*' }).Count" 2>nul
if %errorlevel% gtr 0 (
    echo [%date% %time%] Bot already running, skipping start.
    timeout /t 30 /nobreak
    goto loop
)
echo [%date% %time%] Starting Lords Mobile GF Bot...
start "" /b python.exe bot.py >> "%~dp0bot.log" 2>&1
timeout /t 10 /nobreak
goto loop
