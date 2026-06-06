@echo off
echo ========================================
echo  解题能手 - 启动中
echo ========================================
cd /d "%~dp0"

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请安装Python 3.8+
    pause
    exit /b 1
)

:: 安装Python依赖（首次运行，含 PDF 解析 pymupdf）
echo 检查Python依赖...
python -m pip install -r requirements.txt -q --user

:: 检查Node.js  
node --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Node.js，请安装Node.js 18+
    pause
    exit /b 1
)

:: 安装npm依赖（首次运行）
if not exist node_modules (
    echo 安装npm依赖，请稍候...
    npm install
)

echo 启动应用...
npm start
