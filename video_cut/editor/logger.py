# -*- coding: utf-8 -*-
"""
editor/logger.py —— 统一日志系统

原则（用户要求：每一处出错都要打印日志，重要日志也要打印）：
  - 所有模块统一 get_logger(__name__) 取 logger
  - 同时输出到：logs/app.log（RotatingFileHandler，1MB×3）+ stderr
  - 所有 except 分支必须 log.exception / log.error，禁止静默吞异常
  - 重要生命周期事件（启动/打开项目/渲染开始结束/自动保存）用 log.info
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys

_ROOT_LOGGER: logging.Logger | None = None
_LOGS_DIR = ""

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(app_dir: str) -> logging.Logger:
    """初始化根日志。app_dir 下创建 logs/ 目录。可重复调用（幂等）。"""
    global _ROOT_LOGGER, _LOGS_DIR
    if _ROOT_LOGGER is not None:
        return _ROOT_LOGGER

    _LOGS_DIR = os.path.join(app_dir, "logs")
    os.makedirs(_LOGS_DIR, exist_ok=True)

    root = logging.getLogger("vc")
    root.setLevel(logging.INFO)

    # 文件：滚动 1MB × 3
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(_LOGS_DIR, "app.log"), maxBytes=1_000_000,
        backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter(LOG_FORMAT))

    # 控制台：非冻结（源码运行）时输出
    handlers = [fh]
    if not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter(LOG_FORMAT))
        handlers.append(sh)

    root.handlers = handlers
    _ROOT_LOGGER = root
    root.info("日志系统初始化完成 -> %s", os.path.join(_LOGS_DIR, "app.log"))
    return root


def get_logger(name: str) -> logging.Logger:
    """各模块拿 logger：get_logger(__name__)"""
    return logging.getLogger(f"vc.{name}")


def log_path() -> str:
    """当前日志文件路径（供"打开日志"按钮用）。"""
    return os.path.join(_LOGS_DIR, "app.log") if _LOGS_DIR else ""


def tail_lines(n: int = 200) -> list:
    """读取日志文件最后 n 行（供应用内日志查看器）。"""
    path = log_path()
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [l.rstrip("\n") for l in lines[-n:]]