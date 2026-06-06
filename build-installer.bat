@echo off
setlocal
echo ========================================
echo  Lab-Solver - Build Windows Installer
echo ========================================
cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Cannot change to script directory.
    pause
    exit /b 1
)

echo [1/3] npm install...
call npm install
if errorlevel 1 (
    echo [ERROR] npm install failed.
    pause
    exit /b 1
)

echo [2/3] Verify Python backend imports...
python tests\verify_imports.py
if errorlevel 1 (
    echo [ERROR] verify_imports failed.
    pause
    exit /b 1
)

echo [3/3] electron-builder (fresh TEMP dir, no file lock)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-win.ps1"
if errorlevel 1 (
    echo [ERROR] build failed.
    pause
    exit /b 1
)

echo.
echo Done. See installer\ folder in repo.
dir /b "%~dp0installer\*.exe" 2>nul
pause
endlocal
