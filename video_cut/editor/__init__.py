# -*- coding: utf-8 -*-
"""
editor —— 剪辑应用包
入口：editor.editor_app.main()
"""
import os
import sys

__version__ = "0.2.0"


def bundled_dir() -> str:
    """资源/数据目录：打包后一律用 exe 所在目录（ffmpeg、日志、配置都在 exe 旁）；
    源码运行用脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def resolve_ffmpeg(user_input: str = "") -> str:
    """按优先级找 ffmpeg：界面输入 > 同目录/脚本目录 > PATH。"""
    if user_input.strip():
        return user_input.strip()
    candidates = [
        os.path.join(bundled_dir(), "ffmpeg.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools",
                     "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ffmpeg.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    from shutil import which
    return which("ffmpeg") or ""


def resolve_ffprobe() -> str:
    """ffprobe 同样按 同目录/PATH 找。"""
    for c in [os.path.join(bundled_dir(), "ffprobe.exe"),
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "tools", "ffmpeg", "bin", "ffprobe.exe")]:
        if os.path.isfile(c):
            return c
    from shutil import which
    return which("ffprobe") or ""