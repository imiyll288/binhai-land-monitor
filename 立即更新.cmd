@echo off
chcp 65001 >nul
cd /d "%~dp0"
"C:\Users\andon\AppData\Local\Programs\Python\Python314\python.exe" collector.py
echo.
echo 更新完成。按任意键打开汇总页面。
pause >nul
start "" "%~dp0滨海新区土地信息.html"
