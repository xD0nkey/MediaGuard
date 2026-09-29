@echo off
setlocal
title MediaGuard
cd /d "%~dp0"
if errorlevel 1 (
    echo Unable to open the MediaGuard folder.
    pause
    exit /b 1
)

echo ========================================
echo  MediaGuard
echo ========================================

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    set "PYTHON_ARGS="
) else (
    where py >nul 2>&1
    if errorlevel 1 (
        echo Python 3 was not found. Install Python 3.11 or newer, or create .venv.
        pause
        exit /b 1
    )
    set "PYTHON=py"
    set "PYTHON_ARGS=-3"
)

if not exist "config.json" (
    echo Missing config.json. Copy config.example.json to config.json and enable Discord.
    pause
    exit /b 1
)

if not exist "web\dist\index.html" (
    echo Missing dashboard build. Run npm ci and npm run build in the web folder once.
    pause
    exit /b 1
)

"%PYTHON%" %PYTHON_ARGS% -c "import mediaguard, fastapi, uvicorn, discord, aiohttp; import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 (
    echo Python 3.11+ or MediaGuard dependencies are missing from the selected Python environment.
    echo Install the project into that environment once with: python -m pip install -e .
    pause
    exit /b 1
)

"%PYTHON%" %PYTHON_ARGS% -c "from mediaguard.config import load; import sys; sys.exit(0 if load().discord_enabled else 1)" >nul 2>&1
if errorlevel 1 (
    echo Discord is not enabled in config.json, or the configuration is invalid.
    echo Set discord.enabled to true in config.json.
    pause
    exit /b 1
)

"%PYTHON%" %PYTHON_ARGS% -c "from mediaguard.secrets import discord_token; import sys; sys.exit(0 if discord_token() else 1)" >nul 2>&1
if errorlevel 1 (
    echo Missing Discord bot token. Set DISCORD_BOT_TOKEN or add it to ignored secrets.env.
    pause
    exit /b 1
)

echo Starting... Default dashboard: http://127.0.0.1:8765
"%PYTHON%" %PYTHON_ARGS% -m mediaguard.main
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo MediaGuard exited with code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
