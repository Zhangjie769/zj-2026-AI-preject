# -*- coding: utf-8 -*-
"""
editor/undo.py —— 撤销/重做管理器（快照式）

原理：模型每次变更前 push 一份项目 JSON 快照（深拷贝）；
undo 把当前状态压入 redo，恢复上一份快照；redo 反向。
上限 50 步，防内存膨胀（只存纯数据 dict，不存对象引用）。
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .model import Project


class UndoManager:
    def __init__(self, limit: int = 50):
        self.limit = limit
        self._undo: List[Dict[str, Any]] = []
        self._redo: List[Dict[str, Any]] = []

    # ---------------- 记录 ----------------
    def push(self, project: Project) -> None:
        """在每次模型变更【之前】调用，记录当前状态。"""
        snap = copy.deepcopy(project.to_dict())
        self._undo.append(snap)
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    # ---------------- 操作 ----------------
    def snapshot(self, project: Project) -> Dict[str, Any]:
        """取出当前项目作为一份可回滚的快照（不改变历史）。"""
        return copy.deepcopy(project.to_dict())

    def undo(self, current: Project) -> Optional[Project]:
        """撤销：把当前压入 redo，恢复上一份快照。"""
        if not self._undo:
            return None
        self._redo.append(copy.deepcopy(current.to_dict()))
        snap = self._undo.pop()
        return Project.from_dict(snap)

    def redo(self, current: Project) -> Optional[Project]:
        """重做：把当前压入 undo，恢复被撤销的快照。"""
        if not self._redo:
            return None
        self._undo.append(copy.deepcopy(current.to_dict()))
        snap = self._redo.pop()
        return Project.from_dict(snap)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()