@echo off
chcp 65001 >nul
cd /d %~dp0
py voice_studio.py
pause