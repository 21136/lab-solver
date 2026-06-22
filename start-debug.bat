@echo off
setlocal EnableExtensions
echo ========================================
echo  解题能手 - 调试启动（DevTools + 日志）
echo ========================================
cd /d "%~dp0"

set "PYTHON_CMD="
python --version >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD py -3 --version >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD py --version >nul 2>&1 && set "PYTHON_CMD=py"
if not defined PYTHON_CMD (
    echo [错误] 未找到 Python
    pause
    exit /b 1
)

set "PYTHON="
for /f "delims=" %%i in ('%PYTHON_CMD% -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%i"

if not exist "node_modules\electron\package.json" (
    call npm install
)

set "LAB_SOLVER_DISABLE_GPU=1"
set "ELECTRON_ENABLE_LOGGING=1"

echo 以开发模式启动（自动打开 DevTools）...
call npm run dev >> "%~dp0startup.log" 2>&1
if errorlevel 1 (
    echo 启动失败，详见 startup.log 与 %%APPDATA%%\lab-solver\crash.log
    type "%~dp0startup.log" 2>nul
    pause
    exit /b 1
)

endlocal
