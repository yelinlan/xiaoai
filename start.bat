@echo off
chcp 65001 >nul
set PYTHONUTF8=1
title XiaoAI Gateway
cd /d %~dp0
rem Check for admin rights; self-elevate so the gateway can close elevated processes
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
python app.py
pause
