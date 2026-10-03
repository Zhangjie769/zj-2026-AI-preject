# -*- coding: utf-8 -*-
"""
editor/project_store.py —— 项目文件（.vcp JSON）读写 + 自动保存

- 手动保存/打开：任意路径 .vcp
- 自动保存：每次变更后调用 request_autosave()，300ms 去抖后写入 autosave.vcp，
  防止中途中断丢失工作。
"""
from __future__ import annotations

import os
import threading

from .model import Project

AUTOSAVE_NAME = "autosave.vcp"


class ProjectStore:
    def __init__(self):
        self._timer = None
        self._lock = threading.Lock()
        self.last_path: str = ""

    # ---------------- 手动存取 ----------------
    def save(self, project: Project, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(project.to_json())
        self.last_path = path

    def load(self, path: str) -> Project:
        with open(path, "r", encoding="utf-8") as f:
            p = Project.from_json(f.read())
        self.last_path = path
        return p

    # ---------------- 自动保存 ----------------
    def autosave_path(self, base_dir: str) -> str:
        return os.path.join(base_dir, AUTOSAVE_NAME)

    def request_autosave(self, project: Project, base_dir: str) -> None:
        """带去抖的自动保存：多次快速变更只落盘一次。"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(
                0.3, self._do_autosave, args=(project, base_dir)
            )
            self._timer.daemon = True
            self._timer.start()

    def _do_autosave(self, project: Project, base_dir: str) -> None:
        try:
            path = self.autosave_path(base_dir)
            with open(path, "w", encoding="utf-8") as f:
                f.write(project.to_json())
        except Exception:
            pass  # 自动保存失败不打扰用户

    def try_recover(self, base_dir: str) -> Project | None:
        """启动时尝试从 autosave.vcp 恢复上次未完成的项目。"""
        path = self.autosave_path(base_dir)
        if os.path.isfile(path):
            try:
                return self.load(path)
            except Exception:
                return None
        return None