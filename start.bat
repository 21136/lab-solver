@echo off
setlocal EnableExtensions
echo ========================================
echo  解题能手 - 启动中
echo ========================================
cd /d "%~dp0"

:: 解析 Python（Windows 常见：python / py -3 / py）
set "PYTHON_CMD="
python --version >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    py -3 --version >nul 2>&1 && set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    py --version >nul 2>&1 && set "PYTHON_CMD=py"
)
if not defined PYTHON_CMD (
    echo [错误] 未找到 Python，请安装 Python 3.8+ 并勾选 "Add to PATH"
    echo        下载: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo 使用 Python: %PYTHON_CMD%
%PYTHON_CMD% --version

:: 安装 Python 依赖（每次启动检查，避免更新代码后缺包）
echo 检查 Python 依赖...
%PYTHON_CMD% -m pip install -r requirements.txt -q --user
if errorlevel 1 (
    echo [错误] pip install 失败。请手动运行:
    echo        %PYTHON_CMD% -m pip install -r requirements.txt
    pause
    exit /b 1
)

:: 导入冒烟测试（提前发现后端起不来）
echo 验证 Python 后端...
%PYTHON_CMD% tests\verify_imports.py
if errorlevel 1 (
    echo [错误] Python 后端依赖不完整，见上方报错
    pause
    exit /b 1
)

:: 解析 python.exe 绝对路径，供 Electron 主进程 spawn 使用
set "PYTHON="
for /f "delims=" %%i in ('%PYTHON_CMD% -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%i"
if not defined PYTHON (
    echo [警告] 无法解析 python.exe 路径，Electron 将尝试使用 PATH 中的 python
) else (
    echo Python 可执行文件: %PYTHON%
)

:: 检查 Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Node.js，请安装 Node.js 18+
    echo        下载: https://nodejs.org/
    pause
    exit /b 1
)
node --version

:: npm 依赖：node_modules 缺失或 electron 未安装时重装
if not exist "node_modules\electron\package.json" (
    echo 安装 npm 依赖，请稍候...
    call npm install
    if errorlevel 1 (
        echo [错误] npm install 失败
        pause
        exit /b 1
    )
) else (
    echo npm 依赖已就绪
)

:: 避免部分 Windows 显卡驱动导致 Electron 一打开就闪退
set "LAB_SOLVER_DISABLE_GPU=1"
set "ELECTRON_ENABLE_LOGGING=1"

echo 启动应用（日志写入 startup.log）...
call npm start >> "%~dp0startup.log" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [错误] 应用未能启动（退出码 %EXIT_CODE%）。常见原因:
    echo   1. 5199 端口被占用 — 关闭其他解题能手窗口或结束残留 python.exe
    echo   2. node_modules 损坏 — 删除 node_modules 文件夹后重新运行本脚本
    echo   3. 杀毒软件拦截 electron — 将项目目录加入白名单
    echo   4. 显卡驱动冲突 — 已默认关闭 GPU 加速；仍闪退请看 startup.log 与 crash.log
    echo.
    echo 详细日志: %~dp0startup.log
    echo 崩溃日志: %LOCALAPPDATA%\lab-solver\crash.log
    echo.
    echo --- startup.log 末尾 ---
    powershell -NoProfile -Command "if (Test-Path '%~dp0startup.log') { Get-Content '%~dp0startup.log' -Tail 40 }"
    pause
    exit /b %EXIT_CODE%
)

endlocal
