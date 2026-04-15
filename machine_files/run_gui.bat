@echo off
setlocal

set MACHINE_NAME=maadi_club
set DROPME_MODELS_DIR=C:\DropMe\models
set DROPME_DATA_DIR=C:\DropMe\runtime\data
set DROPME_STATE_DIR=C:\DropMe\runtime\state
set DROPME_DEV=0
set DROPME_CHECK_BASKETS=1

if not defined DROPME_APP_DIR set "DROPME_APP_DIR=%~dp0.."
set "LOG_FILE=%DROPME_APP_DIR%\machine_files\run_gui.log"

where uv >nul 2>&1
if errorlevel 1 (
    echo uv is not installed or not on PATH. Install uv first.
    pause
    exit /b 1
)

cd /d "%DROPME_APP_DIR%" || (
    echo Failed to change directory to %DROPME_APP_DIR%
    pause
    exit /b 1
)

uv sync --frozen > "%LOG_FILE%" 2>&1
if errorlevel 1 (
    type "%LOG_FILE%"
    pause
    exit /b 1
)

uv run gui >> "%LOG_FILE%" 2>&1
type "%LOG_FILE%"
pause
