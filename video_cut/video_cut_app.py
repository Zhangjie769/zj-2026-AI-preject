# -*- coding: utf-8 -*-
"""
视频剪辑器 —— 程序入口（PyInstaller 打包入口，勿改文件名）
运行 GUI：python video_cut_app.py
"""
import sys
import os

# 允许从源码目录直接运行（PyInstaller 打包时此路径无意义）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from editor.editor_app import main

if __name__ == "__main__":
    main()