@echo off
setlocal
cd /d "%~dp0.."

python -m pytest %*
if errorlevel 1 exit /b %errorlevel%

echo.
echo Node settings-store test (optional): node tests\test_settings_store.js
endlocal
