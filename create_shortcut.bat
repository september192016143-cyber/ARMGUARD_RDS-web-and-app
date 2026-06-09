@echo off
:: ARMGUARD RDS — Desktop Shortcut Creator
:: Run this once after installation to place a shortcut (with icon) on the Desktop.
:: Double-click to run — no administrator rights required.

setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "PYTHONW=%APP_DIR%\venv\Scripts\pythonw.exe"
set "SCRIPT=%APP_DIR%\desktop_app.py"
set "ICON=%APP_DIR%\project\armguard\static\images\favicon.ico"
set "SHORTCUT=%USERPROFILE%\Desktop\ARMGUARD RDS.lnk"

:: Verify the virtual environment exists
if not exist "%PYTHONW%" (
    echo.
    echo  ERROR: Virtual environment not found.
    echo  Run the following commands first:
    echo    python -m venv venv
    echo    venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: Create the shortcut using PowerShell's WScript.Shell COM object
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s  = $ws.CreateShortcut('%SHORTCUT%'); " ^
  "$s.TargetPath      = '%PYTHONW%'; " ^
  "$s.Arguments       = '\""%SCRIPT%\"\"'; " ^
  "$s.WorkingDirectory = '%APP_DIR%'; " ^
  "$s.IconLocation    = '%ICON%,0'; " ^
  "$s.Description     = 'ARMGUARD RDS - Records and Dispensing System'; " ^
  "$s.Save()"

if exist "%SHORTCUT%" (
    echo.
    echo  Shortcut created successfully:
    echo  %SHORTCUT%
    echo.
    echo  You can now launch ARMGUARD from your Desktop.
) else (
    echo.
    echo  ERROR: Shortcut could not be created.
    echo  Check that PowerShell is available and try again.
)

pause
