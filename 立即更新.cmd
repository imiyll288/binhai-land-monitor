@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish_update.ps1"
echo.
echo 更新并发布完成。按任意键打开汇总页面。
pause >nul
start "" "%~dp0滨海新区土地信息.html"
