@echo off
chcp 65001 >nul
echo ========================================
echo    Customer-Agent 启动脚本
echo ========================================
echo.

REM 检查配置文件是否存在
if not exist "config.json" (
    echo [错误] config.json 配置文件不存在！
    echo.
    echo 请按以下步骤操作：
    echo 1. 复制 config.json.template 为 config.json
    echo 2. 编辑 config.json，填入你的 API Key 和 Base URL
    echo.
    echo 配置示例：
    echo {
    echo   "llm": {
    echo     "model_name": "你的模型名称",
    echo     "api_key": "你的API密钥",
    echo     "api_base": "你的API地址"
    echo   }
    echo }
    echo.
    pause
    exit /b 1
)

echo [信息] 正在启动应用...
echo.

REM 激活虚拟环境并启动应用
call .venv\Scripts\activate.bat
python app.py

pause
