@echo off
REM =====================================================================
REM  一键打包脚本（onedir 免安装版，内置 ffmpeg/ffprobe/ffplay）
REM  生成 dist\video_cut_app\ 文件夹，里面：
REM    video_cut_app.exe  +  ffmpeg.exe  +  ffprobe.exe  +  ffplay.exe
REM  整个文件夹复制到任何 Windows 机器即可用，无需装任何依赖。
REM =====================================================================
setlocal
cd /d %~dp0

REM --- ffmpeg 三件套源文件（本脚本默认从项目 tools\ffmpeg\bin 取）---
set "FFDIR=%~dp0tools\ffmpeg\bin"

echo 安装 PyInstaller（若已安装会自动跳过）...
python -m pip install --upgrade pyinstaller >nul 2>&1

echo 开始打包（onedir）...
python -m PyInstaller --onedir --windowed --clean --noconfirm ^
  --name video_cut_app ^
  --collect-all sounddevice ^
  --collect-all soundfile ^
  --distpath .\dist ^
  --workpath .\build ^
  --specpath .\build ^
  video_cut_app.py

if errorlevel 1 (
    echo.
    echo 打包失败，请查看上方错误信息。
    pause
    exit /b 1
)

echo.
echo 捆绑 ffmpeg.exe 到应用目录...
if exist "%FFDIR%\ffmpeg.exe" (
    copy /y "%FFDIR%\ffmpeg.exe" ".\dist\video_cut_app\ffmpeg.exe" >nul
) else (
    echo [警告] 未找到 %FFDIR%，请先下载 ffmpeg 放入 tools\ffmpeg\bin
)

echo.
echo =====================================================================
echo  打包完成！
echo  使用方式：把整个文件夹 .\dist\video_cut_app\ 拷走即可
echo  双击其中的 video_cut_app.exe 运行（无需装任何依赖）
echo =====================================================================
endlocal
pause