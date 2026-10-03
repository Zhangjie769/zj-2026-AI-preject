# -*- coding: utf-8 -*-
"""editor_app: ▶=整条时间轴（不再单段复活） + 标尺拖动节流 + 编辑后视图必适配"""
import io

p = r"D:\my_AI_practice\video_cut\editor\editor_app.py"
src = io.open(p, encoding="utf-8").read()

def rep(old, new, anchor):
    assert old in src, f"missing: {anchor}"
    return src.replace(old, new, 1)

# 1) ▶ 永远=整条时间轴（修复"只播一个视频长度"）
rep(
    '''    def _toggle_play(self):
        """▶播放：从播放头处按整条时间轴连续播放（时长=项目总时长）。"""
        if getattr(self.player, "_path", None):
            if self.player._playing:
                self.player.pause()
            else:
                if self._timeline_play:
                    self.player.play()   # 时间轴模式恢复
                else:
                    self._play_timeline()  # 没有在播 → 从头轴模式
            return
        self._play_timeline()''',
    '''    def _toggle_play(self):
        """▶播放：永远=整条时间轴连续播放（时长=项目总时长）。"""
        if self.player._playing and self._timeline_play:
            self.player.pause()
            return
        if not self._timeline_play and getattr(self.player, "_path", None):
            # 上次是单段预览：切换为整条时间轴（从当前播放头开始）
            self._play_timeline()
            return
        self._play_timeline()''',
    "toggle tl-always")

# 2) 标尺拖动节流：拖得再快也只 0.15s 一跳，松开必跳准
rep(
    '''    def _on_timeline_seek(self, sec):
        """时间轴播放头被点击/拖动 → 定位预览（连续播放模式下保持播放）。"""
        self.tl_time_var.set(self._fmt(sec))
        was_tl = self._timeline_play
        was_playing = self.player._playing''',
    '''    def _on_timeline_seek(self, sec):
        """时间轴播放头被点击/拖动 → 定位预览（节流：拖拖时 0.15s 一跳，松开跳准）。"""
        self.tl_time_var.set(self._fmt(sec))
        now = _time_now()
        last = getattr(self, "_last_seek", 0.0)
        if now - last < 0.15:
            self._pending_seek = sec
            return
        self._last_seek = now
        self._pending_seek = None
        self._do_seek(sec)

    def _flush_seek(self):
        p = getattr(self, "_pending_seek", None)
        if p is not None:
            self._pending_seek = None
            self._do_seek(p)

    def _do_seek(self, sec):
        was_tl = self._timeline_play
        was_playing = self.player._playing''',
    "seek throttle head")

# 3) _do_seek 主体改名（原函数尾不变）
rep(
    '''        if clip.id != self._preview_clip_id:
            self._timeline_play = False
            self._load_clip_preview(clip, autoplay=False)
        self.player.seek(local)
        self._timeline_play = was_tl
        if was_playing:
            self.player.play()''',
    '''        if clip.id != self._preview_clip_id:
            self._timeline_play = False
            self._load_clip_preview(clip, autoplay=False)
        self.player.seek(local)
        self._timeline_play = was_tl
        if was_playing:
            self.player.play()''',
    "do_seek tail")

# 4) 导入 time 模块别名
src = rep(
    "from .undo import UndoManager",
    "from .undo import UndoManager\nimport time as _time_now",
    "time import")

# 5) 编辑动作后视图必适配（拼接/删除/粘贴/分割/闭合/变换后整条可见）
rep(
    '''    def _after_model_change(self):
        self.store.request_autosave(self.project, self.base_dir)
        self.timeline.refresh()
        self.status_var.set(
            f"项目总时长 {self._fmt(self.project.total_duration())}，"
            f"片段 {len(self.project.all_clips())}，"
            f"画布 {self.project.canvas_w}×{self.project.canvas_h}"
            f"（工具栏「◧ 画布」可改）")
        self._refresh_controls()''',
    '''    def _after_model_change(self):
        self.store.request_autosave(self.project, self.base_dir)
        self.timeline.refresh()
        self._maybe_fit()
        self.status_var.set(
            f"项目总时长 {self._fmt(self.project.total_duration())}，"
            f"片段 {len(self.project.all_clips())}，"
            f"画布 {self.project.canvas_w}×{self.project.canvas_h}"
            f"（工具栏「◧ 画布」可改）")
        self._refresh_controls()

    def _maybe_fit(self):
        """内容超出可视区域 → 自动适配，保证整条时间轴同屏可见。"""
        try:
            w = self.timeline.winfo_width()
            if w > 50 and self.timeline.content_width() > w * 1.02:
                self.timeline.fit()
        except Exception:
            pass''',
    "after model fit")

io.open(p, "w", encoding="utf-8", newline="\n").write(src)
check = io.open(p, encoding="utf-8").read()
for t in ("_do_seek", "_flush_seek", "_maybe_fit"):
    assert t in check, t
print("APP SEEK/FIT/TLPLAY OK")