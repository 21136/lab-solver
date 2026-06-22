@echo off
setlocal EnableExtensions
echo ========================================
echo  从 GitHub 恢复缺失文件
echo ========================================
cd /d "%~dp0"

set "REPO_URL=https://github.com/21136/lab-solver.git"

:: 检查 git
git --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 git，请先安装 Git: https://git-scm.com/download/win
    pause
    exit /b 1
)

:: 若当前目录不是 git 仓库，提示克隆
if not exist ".git" (
    echo [提示] 当前目录不是 git 仓库。
    echo 建议在上级目录执行:
    echo   git clone %REPO_URL%
    echo 然后进入 lab-solver 文件夹运行 start.bat
    pause
    exit /b 1
)

echo 拉取 GitHub 最新代码...
git fetch origin master
if errorlevel 1 (
    echo [错误] git fetch 失败，请检查网络或执行:
    echo   git remote add origin %REPO_URL%
    pause
    exit /b 1
)

echo 恢复关键文件（package.json / start.bat / main.js / preload.js）...
git checkout origin/master -- package.json start.bat main.js preload.js
if errorlevel 1 (
    echo [错误] 恢复文件失败
    pause
    exit /b 1
)

if not exist package.json (
    echo [错误] package.json 仍不存在
    pause
    exit /b 1
)

echo.
echo [成功] package.json 已恢复
echo 接下来安装依赖并启动...
echo.

if not exist node_modules\electron\package.json (
    call npm install
)

call start.bat
endlocal
