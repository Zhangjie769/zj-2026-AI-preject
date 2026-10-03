@echo off
rem 启动“逐鹿秋狩 · 涂色辅助”
cd /d "%~dp0"
where py >nul 2>nul && (py paint_gui.py) || (python paint_gui.py)
