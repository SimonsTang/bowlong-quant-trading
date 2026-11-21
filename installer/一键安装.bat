@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title 巧未来-波龙量化 一键安装
echo 正在启动安装程序...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0一键安装.ps1"
echo.
pause
