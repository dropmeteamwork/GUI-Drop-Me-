@echo off
set MACHINE_NAME=maadi_club
set DROPME_MODELS_DIR=C:\DropMe\models
set DROPME_DATA_DIR=C:\DropMe\runtime\data
set DROPME_STATE_DIR=C:\DropMe\runtime\state
set DROPME_DEV=0
set DROPME_CHECK_BASKETS=1
cd /d C:\DropMe\gui\dropme-gui-final
C:\DropMe\gui\dropme-gui-final\.venv\Scripts\python.exe -m gui.main > C:\DropMe\run_gui.log 2>&1
type C:\DropMe\run_gui.log
pause
