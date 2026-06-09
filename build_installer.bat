@echo off
:: =============================================================================
:: ARMGUARD RDS — Build Windows Installer
:: =============================================================================
:: Run this script once to produce:
::   installer\Output\ARMGUARD_RDS_Setup.exe
::
:: Requirements (one-time setup):
::   1. Python 3.12 + venv already created  (run: python -m venv venv)
::   2. pip install -r requirements.txt
::   3. pip install pyinstaller
::   4. Inno Setup 6 installed  →  https://jrsoftware.org/isinfo.php
:: =============================================================================

setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
set "VENV=%ROOT%venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set "PYINSTALLER=%VENV%\Scripts\pyinstaller.exe"
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

echo.
echo  ============================================
echo   ARMGUARD RDS — Build Installer
echo  ============================================
echo.

:: ── Verify venv ───────────────────────────────────────────────────────────────
if not exist "%PYTHON%" (
    echo  [ERROR] Virtual environment not found at: %VENV%
    echo  Run first:  python -m venv venv  ^&^&  venv\Scripts\pip install -r requirements.txt
    pause & exit /b 1
)
:: ── Check for .env (needed to bundle config into the installer) ─────────────
echo  [0/3] Checking for .env...
if not exist "%ROOT%.env" (
    echo  [WARN]  No .env found at: %ROOT%.env
    echo          The installer will be built WITHOUT a bundled configuration.
    echo          To bundle the config, download .env from the server Settings page
    echo          and place it in the repo root, then re-run this script.
    echo.
) else (
    echo        Found .env — will be embedded in the installer.
)
:: ── Install / upgrade PyInstaller ─────────────────────────────────────────────
echo  [1/3] Installing PyInstaller...
"%PIP%" install --quiet --upgrade pyinstaller pyinstaller-hooks-contrib
if errorlevel 1 ( echo  [ERROR] pip failed. & pause & exit /b 1 )
echo        Done.

:: ── Build PyInstaller bundle ──────────────────────────────────────────────────
echo  [2/3] Building PyInstaller bundle (this takes a few minutes)...
cd /d "%ROOT%"
"%PYINSTALLER%" desktop_app.spec --noconfirm --clean
if errorlevel 1 ( echo  [ERROR] PyInstaller build failed. & pause & exit /b 1 )
echo        Bundle created: dist\ARMGUARD_RDS\

:: ── Compile Inno Setup installer ─────────────────────────────────────────────
echo  [3/3] Compiling Inno Setup installer...
if not exist "%ISCC%" (
    echo  [WARN]  Inno Setup not found at: %ISCC%
    echo          Install from https://jrsoftware.org/isinfo.php
    echo          Then re-run this script or manually open installer\armguard_setup.iss
    echo.
    echo  PyInstaller bundle is ready at:  dist\ARMGUARD_RDS\
    pause & exit /b 0
)

"%ISCC%" "%ROOT%installer\armguard_setup.iss"
if errorlevel 1 ( echo  [ERROR] Inno Setup compilation failed. & pause & exit /b 1 )

echo.
echo  ============================================
echo   SUCCESS
echo  ============================================
echo   Installer: installer\Output\ARMGUARD_RDS_Setup.exe
echo   Upload this file to the server via Settings ^> Desktop App Setup.
echo   Users download and run it \u2014 no ZIP, no manual config.
echo  ============================================
echo.
pause
