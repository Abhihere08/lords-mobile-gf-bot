@echo off
cls
title Lords Mobile GF Bot - One-Click Setup
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo ============================================================
echo   Lords Mobile GF Bot - One-Click Bootstrap
echo   MSI Cubi NUC 24/7 Setup
echo ============================================================
echo.

:: --- Step 1: Check / install Python 3.12 ---
echo [1/5] Checking for Python...
where python >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
    echo [OK] Found %PYVER%
    goto :install_deps
)

echo [MISSING] Python not found. Downloading Python 3.12...
powershell -NoProfile -Command "& { (New-Object System.Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe', '%TEMP%\python-installer.exe') }"

if not exist "%TEMP%\python-installer.exe" (
    echo [ERROR] Failed to download Python. Please install manually:
    echo   https://www.python.org/downloads/release/python-3128/
    echo   Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo Installing Python 3.12 (this may take a minute)...
"%TEMP%\python-installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
del "%TEMP%\python-installer.exe"

:: Wait for Python to register in PATH
timeout /t 5 /nobreak >nul
where python >nul 2>&1
if %errorlevel% neq 0 (
    set "PATH=C:\Program Files\Python312;%PATH%"
    set "PATH=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312;%PATH%"
)

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python installation failed. Please install manually.
    pause
    exit /b 1
)
echo [OK] Python 3.12 installed successfully.
echo.

:install_deps
:: --- Step 2: Install pip dependencies ---
echo [2/5] Installing Python dependencies...
python -m pip install --upgrade pip 2>nul
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.
echo.

:: --- Step 3: Configure bot secrets ---
echo [3/5] Configuring Discord bot secrets...
echo.
echo You need to provide:
echo   1. Google Sheet URL (from your GF spreadsheet)
echo   2. Discord Bot Token (from Discord Developer Portal)
echo   3. Discord Channel ID (right-click channel with "Copy ID")
echo   4. Discord Webhook URL (optional, for webhook mode)
echo.
echo Get your bot token at: https://discord.com/developers/applications
echo Get your channel ID with Developer Mode enabled in Discord settings
echo.
set /p SHEET_URL="Paste your Google Sheet URL here: "
set /p BOT_TOKEN="Paste your Discord Bot Token here: "
set /p CHANNEL_ID="Paste your Discord Channel ID here: "
set /p WEBHOOK_URL="Paste your Discord Webhook URL (optional, press Enter to skip): "

:: Write config.json
python -c "import json; json.dump({'sheet_url': '%SHEET_URL%', 'timezone': 'Asia/Kolkata', 'slot_0_start_time': '10:30', 'total_slots': 15, 'pre_slot_reminder_minutes': 15, 'auto_detect_date_from_sheet': True, 'fallback_start_date': '2026-09-06', 'discord_bot_token': '%BOT_TOKEN%', 'discord_channel_id': '%CHANNEL_ID%', 'discord_webhook_url': '%WEBHOOK_URL%'}, open('config.json', 'w'), indent=2)"

:: Create runtime files that the bot needs
echo {} > member_mappings.json
echo {} > sent_alerts.json
echo {} > user_timezones.json
echo [] > locked_mappings.json
type nul > bot.log
type nul > bot_err.log

echo [OK] config.json saved. You can edit it later with setup.bat
echo [OK] Runtime files created: member_mappings.json, sent_alerts.json, user_timezones.json, locked_mappings.json, bot.log, bot_err.log
echo.

:: --- Step 4: Create scheduled task for auto-start ---
echo [4/5] Setting up Windows auto-start task...
echo (Requires Administrator - right-click to run as admin)
schtasks /end /tn "BloodMafiaGFBot" 2>nul
schtasks /delete /tn "BloodMafiaGFBot" /f 2>nul

:: Generate task XML with this folder's actual path
powershell -NoProfile -Command "(Get-Content '%~dp0bot_task.xml') -replace '__BOT_DIR__', '%~dp0' -replace '%USERNAME%', '$env:USERNAME' | Set-Content '%TEMP%\BloodMafiaGFBot.xml' -Encoding Unicode"
schtasks /create /tn "BloodMafiaGFBot" /xml "%TEMP%\BloodMafiaGFBot.xml" /f >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Scheduled task "BloodMafiaGFBot" created ^(starts at Windows login^)
    echo [OK] Starting bot now via scheduled task ^(detached from this terminal^)
    schtasks /run /tn "BloodMafiaGFBot"
) else (
    echo [WARN] Could not create scheduled task. Run as Administrator to enable auto-start.
    echo        Starting bot directly for now...
    start "" /min python.exe bot.py > bot.log 2>&1
)
del "%TEMP%\BloodMafiaGFBot.xml" 2>nul
echo.

:: --- Step 5: Confirm bot is running ---
echo [5/5] Bot started. Check Discord for online status.
echo.
echo Bot will keep running even after this window is closed.
echo ──────────────────────────────────────────────────────────
echo  To STOP the bot:   schtasks /end /tn "BloodMafiaGFBot"
echo  To RESTART later:  schtasks /run /tn "BloodMafiaGFBot"
echo  Configuration:     setup.bat   ^(re-edit token/channel^)
echo  View logs:         type bot.log
echo ──────────────────────────────────────────────────────────
echo.
timeout /t 3 /nobreak >nul
