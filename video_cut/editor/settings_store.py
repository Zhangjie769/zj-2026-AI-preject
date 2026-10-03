# -*- coding: utf-8 -*-
"""
editor/settings_store.py —— 界面状态记忆（"返回操作回到上次的界面"）

记忆内容（JSON，settings.json，保存在应用目录）：
  - window 几何位置
  - last_dir（素材文件夹）
  - last_project（最近打开的项目 .vcp）
  - timeline 状态：播放头秒、缩放 像素/秒、选中片段 id
  - recent_projects（最近项目列表，供菜单快速打开）

启动时 restore()，关键变化时 save()（关闭窗口、切换目录等）。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from . import logger as _logmod

log = _logmod.get_logger("settings_store")


class SettingsStore:
    def __init__(self, app_dir: str):
        self.app_dir = app_dir
        self.path = os.path.join(app_dir, "settings.json")
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.warning("读取 settings.json 失败，使用默认: %s", e)
        return {}

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error("保存 settings.json 失败: %s", e)

    # ---------------- 便捷读写 ----------------
    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value

    def add_recent_project(self, path: str, maxn: int = 8) -> None:
        recents = self.get("recent_projects", [])
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        self.set("recent_projects", recents[:maxn])
        self.save()

    def recent_projects(self) -> list:
        return self.get("recent_projects", [])