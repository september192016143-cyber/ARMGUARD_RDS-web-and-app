@echo off
:: ARMGUARD RDS — Desktop Application Launcher
:: Double-click this file (or pin it to the taskbar) to start ARMGUARD.
:: Requires: Python 3.12 venv at .\venv\  (created by setup or deploy script)

title ARMGUARD RDS

:: Resolve the directory containing this batch file.
cd /d "%~dp0"

:: Verify the virtual environment exists.
if not exist "venv\Scripts\python.exe" (
    echo.
    echo  ERROR: Virtual environment not found.
    echo  Expected: %~dp0venv\Scripts\python.exe
    echo.
    echo  Run the following commands to create it:
    echo    python -m venv venv
    echo    venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: Launch the desktop app (hidden console via pythonw for a cleaner experience).
:: Change "pythonw.exe" to "python.exe" to see console output for debugging.
echo Starting ARMGUARD RDS...
start "" "venv\Scripts\pythonw.exe" desktop_app.py
