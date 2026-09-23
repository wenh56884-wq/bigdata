@echo off
setlocal
chcp 65001 >nul
title 九天梧桐 AI 工作台

cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo [九天梧桐] 正在启动服务，就绪后会自动打开浏览器...
echo [九天梧桐] 访问地址：http://127.0.0.1:5000
echo [九天梧桐] 停止服务：关闭本窗口或按 Ctrl+C
echo.

"%PYTHON_EXE%" web.py

echo.
echo [九天梧桐] 服务已停止或启动失败，请查看上方信息。
pause
