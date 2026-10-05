# -*- coding: utf-8 -*-
"""
editor/timeline_widget.py —— 时间轴控件（tkinter Canvas 自绘）

能力：
  - 多轨显示（主轨 + 各 overlay 轨），片段矩形，可区分 视频/图片
  - 时间标尺 + 播放头（点击/拖动标尺或轨道可 seek）
  - 缩放：px_per_sec（zoom_in / zoom_out / fit）
  - 交互：
      单击选中片段（on_select 回调）
      双击片段（on_open 回调，用于打开预览）
      拖动片段移动时间位置（on_clips_changed 回调）
      拖动左/右边缘裁剪（on_clips_changed 回调）
  扩展点：转场标记、轨道锁定、吸附网格等后续加。
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional

from .model import AudioClip, Clip, ImageClip, Project, TextClip

HEADER_H = 26          # 标尺高度
TRACK_H = 46           # 每轨高度
MIN_PPS = 0.01         # 最小像素/秒（长视频可缩到一屏）
MAX_PPS = 400.0

# 标尺"好看"的间隔候选（秒）：1s/2s/5s/10s/15s/30s/1分/2分/5分/10分/15分/30分/1时…
_TICK_STEPS = [0.5, 1, 2, 5, 10, 15, 20, 30, 60, 120, 180, 300, 600, 900,
               1200, 1800, 3600, 7200, 10800, 21600, 43200, 86400]


def nice_step(sec: float) -> float:
    """从候选里挑一个 >= sec 的"好看"刻度间隔。"""
    sec = max(sec, 1e-6)
    for s in _TICK_STEPS:
        if s >= sec:
            return float(s)
    return float(_TICK_STEPS[-1])

TRACK_COLORS = {
    "main":    "#4a7a55",
    "overlay": "#a8702c",
    "audio":   "#3a6a9c",
    "subtitle": "#7a5a9c",
}
CLIP_IMG_COLOR = "#48698c"
CLIP_AUDIO_COLOR = "#2e8b57"
CLIP_TEXT_COLOR = "#9c6ab0"
PLAYHEAD_COLOR = "#e53935"
SEL_OUTLINE = "#ffd54f"


def fmt_time(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class TimelineWidget(tk.Canvas):
    def __init__(self, master, project: Project, **kw):
        super().__init__(master, background="#1e1e1e", highlightthickness=1,
                         highlightbackground="#3a3a3a", **kw)
        self.project = project
        self.pps = 12.0                # 像素/秒
        self.playhead = 0.0            # 播放头位置（秒）
        self.selected_id: Optional[str] = None
        self._multi: set = set()   # 多选片段 id 集合
        self.snap_enabled = True       # 磁吸开关（应用可切换）
        self.snap_px = 8.0             # 磁吸容差（像素）
        self.on_select = None          # cb(clip | None)
        self.on_open = None            # cb(clip)
        self.on_seek = None            # cb(sec)
        self.on_clips_changed = None   # cb()
        self.on_drag_start = None      # cb() 拖动开始时（供撤销快照）
        self.get_wave = None           # cb(path)->peaks|None（音频波形数据源）
        self.get_thumb = None          # cb(path)->PhotoImage|None（片段缩略图）
        self._thumb_cache = {}
        self._drag = None              # {"mode":"move"|"trim_l"|"trim_r"|"seek","clip_id","start_x","start_ts","start_in","start_out","start_dur"}

        self.bind("<Button-1>", self._on_press)
        self.bind("<MouseWheel>", self._on_wheel)
        self.on_rightclick = None   # cb(clip | None, x_root, y_root)
        self.on_release = None      # cb() 松手（供 app 冲刷节流 seek）
        self.on_move_track = None   # cb(clip, row_kind) 跨轨拖拽落到某轨道
        self._dragging = False      # 拖动中（轻量绘制用）
        self._edit_dirty = False    # 拖动是否真正改过片段（松手提交）
        self.on_edit_commit = None  # cb() 松手提交（autosave/控件刷新）
        self._press_row = None      # 按下时所在轨道行 kind
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Double-Button-1>", self._on_double)
        self.bind("<Button-3>", self._on_right)

    # ------------------------------------------------------------ 布局
    def track_rows(self):
        """返回 [(track, y_top, y_bottom)]，顺序：主轨 + overlay 轨 + audio 轨。"""
        rows = []
        y = HEADER_H
        mt = self.project.track("main", create=False)
        if mt is not None:
            rows.append((mt, y, y + TRACK_H))
            y += TRACK_H
        for t in self.project.overlay_tracks():
            rows.append((t, y, y + TRACK_H))
            y += TRACK_H
        for t in self.project.audio_tracks():
            rows.append((t, y, y + TRACK_H))
            y += TRACK_H
        for t in self.project.text_tracks():
            rows.append((t, y, y + TRACK_H))
            y += TRACK_H
        return rows

    def height_needed(self) -> int:
        return HEADER_H + TRACK_H * max(len(self.track_rows()), 1) + 6

    def content_width(self) -> float:
        """内容宽 = 项目总长 + 尾部留白（随时可往后面继续拼/拖）。"""
        return max(self.project.total_duration(), 60) * self.pps + 640

    # ------------------------------------------------------------ 刷新
    def refresh(self):
        self.configure(scrollregion=(0, 0, self.content_width(), self.height_needed() + 40))
        self.delete("all")
        total = self.project.total_duration()

        # 背景刻度线（等比例自适应：按每秒像素数选"好看"的间隔）
        major = nice_step(90.0 / max(self.pps, 1e-6))   # 主刻度至少间隔 90px
        minor = major / 5.0 if major >= 5 else major
        t = 0.0
        # 防止极端数量（安全上限）
        guard = 0
        while t <= total + minor and guard < 20000:
            guard += 1
            x = t * self.pps
            is_major = (abs(t / major - round(t / major)) < 1e-6)
            self.create_line(x, HEADER_H - (12 if is_major else 7),
                             x, HEADER_H,
                             fill="#7a7a7a" if is_major else "#4a4a4a")
            self.create_line(x, HEADER_H, x, self.height_needed(),
                             fill="#2e2e2e")
            if is_major:
                self.create_text(x + 3, 4, text=fmt_time(t), anchor="nw",
                                 fill="#9e9e9e", font=("Consolas", 9))
            t = t + minor
        # 总时长标记（在内容末尾）
        self.create_text(self.content_width() - 8, 4, anchor="ne",
                         text=f"▍总长 {fmt_time(total)}",
                         fill="#ffd54f", font=("Consolas", 9, "bold"))

        # 轨道（中文标签）
        TRACK_LABELS = {"main": "主轨", "overlay": "画中画", "audio": "音频轨",
                        "subtitle": "字幕"}
        ov_count = 0
        for row, (track, y0, y1) in enumerate(self.track_rows()):
            color = TRACK_COLORS.get(track.kind, "#666")
            self.create_rectangle(0, y0, self.content_width(), y1,
                                  fill="#262626", outline="#3c3c3c")
            label = TRACK_LABELS.get(track.kind, track.kind)
            if track.kind == "overlay":
                ov_count += 1
                label = f"画中画{ov_count}"
            self.create_text(6, y0 + 4, anchor="nw", text=label,
                             fill=color, font=("Microsoft YaHei UI", 9, "bold"))
            for clip in sorted(track.clips, key=lambda c: c.ts):
                self._draw_clip(clip, y0, y1, light=self._dragging)

        self._draw_playhead()

    def _draw_clip(self, clip: Clip, y0, y1, light: bool = False):
        x0 = clip.ts * self.pps
        x1 = (clip.ts + clip.timeline_duration()) * self.pps
        if isinstance(clip, ImageClip):
            color = CLIP_IMG_COLOR
        elif isinstance(clip, AudioClip):
            color = CLIP_AUDIO_COLOR
        elif isinstance(clip, TextClip):
            color = CLIP_TEXT_COLOR
        else:
            color = TRACK_COLORS.get(self._track_of(clip).kind, "#999")
        tag = f"clip_{clip.id}"
        sel = 2 if (clip.id in self._multi or clip.id == self.selected_id) else 0
        self.create_rectangle(x0 + 2, y0 + 14, x1 - 2, y1 - 4,
                              fill=color, outline=SEL_OUTLINE if sel else "#000",
                              width=sel, tags=(tag, "clip"))
        if isinstance(clip, TextClip):
            # 字幕片段：显示文字内容本身
            name = clip.text.replace("\n", " ")
            if len(name) > 20:
                name = name[:18] + "…"
            self.create_text(x0 + 8, y0 + (TRACK_H - 14) / 2 + 14, anchor="w",
                             text=f"✎ {name}", fill="#f2e6ff",
                             font=("Microsoft YaHei UI", 9), tags=(tag,))
        else:
            name = clip.name
            if len(name) > 18:
                name = name[:16] + "…"
            self.create_text(x0 + 8, y0 + (TRACK_H - 14) / 2 + 14, anchor="w",
                             text=name, fill="#e8e8e8",
                             font=("Microsoft YaHei UI", 9), tags=(tag,))
        # 迷你缩略图（视频片段；缩略图为缓存图，拖动中也保留）
        if (not isinstance(clip, (AudioClip, TextClip)) and
                x1 - x0 > 72 and self.get_thumb is not None):
            try:
                ph = self.get_thumb(clip.src)
                if ph is not None:
                    self.create_image(x0 + 6, y0 + 17, anchor="nw",
                                      image=ph, tags=(tag,))
            except Exception:
                pass
        extra = ""
        if isinstance(clip, AudioClip) and (clip.fade_in or clip.fade_out):
            extra = f" 淡入{clip.fade_in:.1f}s/淡出{clip.fade_out:.1f}s"
        tail = f"x{clip.speed:.1f}{extra}" if (clip.speed != 1.0 or extra) else ""
        self.create_text(x1 - 6, y0 + (TRACK_H - 14) / 2 + 14, anchor="e",
                         text=tail, fill="#ffe082", font=("Consolas", 8),
                         tags=(tag,))
        # 转场标记：本片段到下一片段有转场
        tr = getattr(clip, "transition", None)
        if tr:
            tname = str(tr.get("name", "fade"))[:8]
            tmark = f"◤{tname} {float(tr.get('dur', 0)):.1f}s"
            self.create_text(x1 - 4, y0 + 16, anchor="ne", text=tmark,
                             fill="#7ee787", font=("Microsoft YaHei UI", 8),
                             tags=(tag,))
        # 音频波形（拖动中跳过以保流畅）
        if not light and isinstance(clip, AudioClip) and self.get_wave is not None:
            self._draw_wave(clip, x0, x1, y0, y1, tag)

    def _draw_wave(self, clip: AudioClip, x0, x1, y0, y1, tag):
        peaks = None
        try:
            peaks = self.get_wave(clip.src)
        except Exception:
            return
        w = max(x1 - x0, 4)
        top = y0 + 20
        bottom = y1 - 5
        mid = (top + bottom) / 2
        amp = (bottom - top) / 2
        if not peaks:
            # 等待波形数据：画淡虚线占位
            self.create_line(x0 + 2, mid, x1 - 2, mid, fill="#3f7a55",
                             dash=(2, 3), tags=(tag,))
            return
        n_px = max(int(w), 1)
        step = max(len(peaks) / n_px, 1.0)
        for px in range(n_px):
            i0 = int(px * step)
            i1 = min(int((px + 1) * step), len(peaks))
            if i0 >= len(peaks):
                break
            seg = peaks[i0:i1]
            v = max(seg) if seg else 0.0
            y_hi = mid - amp * min(v, 1.0)
            y_lo = mid + amp * min(v, 1.0)
            x = x0 + 2 + px * (w - 4) / n_px
            self.create_line(x, y_hi, x, y_lo, fill="#7cc59b", tags=(tag,))

    def _track_of(self, clip: Clip):
        for track, *_row in [(r[0], r[1], r[2]) for r in self.track_rows()]:
            if track.id == clip.track_id:
                return track
        return None

    def _draw_playhead(self):
        x = self.playhead * self.pps
        self.create_line(x, 0, x, self.height_needed(), fill=PLAYHEAD_COLOR,
                         width=2, tags="playhead")

    # ------------------------------------------------------------ 交互
    def set_playhead(self, sec: float, drive_timeline: bool = True):
        self.playhead = max(0.0, min(sec, self.project.total_duration()))
        self.delete("playhead")
        self._draw_playhead()
        self.see_playhead()
        if drive_timeline and self.on_seek:
            self.on_seek(self.playhead)

    def see_playhead(self):
        x = self.playhead * self.pps
        self.xview_moveto(max(0.0, min(1.0, (x - self.winfo_width() * 0.3) /
                                       max(self.content_width() - self.winfo_width(), 1))))

    def zoom(self, factor: float):
        self.pps = max(MIN_PPS, min(MAX_PPS, self.pps * factor))
        self.refresh()

    def fit(self):
        total = max(self.project.total_duration(), 10)
        avail = max(self.winfo_width() - 40, 200)
        self.pps = max(MIN_PPS, avail / total)
        self.refresh()

    # ---- 磁吸 ----
    def _snap(self, value: float, except_clip_id: str | None = None) -> float:
        """把时间位置吸附到：各轨片段边缘 / 播放头 / 0。返回吸附后的值。"""
        if not self.snap_enabled:
            return value
        tol = self.snap_px / max(self.pps, 0.01)
        best = value
        best_d = tol
        for track, _y0, _y1 in self.track_rows():
            for c in track.clips:
                if c.id == except_clip_id:
                    continue
                for edge in (c.ts, c.ts + c.timeline_duration()):
                    d = abs(value - edge)
                    if d <= best_d:
                        best_d, best = d, edge
        for cand in (self.playhead, 0.0):
            d = abs(value - cand)
            if d <= best_d:
                best_d, best = d, cand
        return best

    # ---- 命中 ----
    def _hit_clip(self, x, y):
        for track, y0, y1 in self.track_rows():
            if y0 <= y < y1:
                for clip in sorted(track.clips, key=lambda c: c.ts, reverse=True):
                    x0 = clip.ts * self.pps
                    x1 = (clip.ts + clip.timeline_duration()) * self.pps
                    if x0 <= x <= x1:
                        return clip, x0, x1
                return None
        return None

    def _on_press(self, evt):
        cx, cy = int(self.canvasx(evt.x)), int(self.canvasy(evt.y))
        self._press = {"x": cx, "y": cy, "clip": None, "moving": False,
                       "mode": None, "x0": 0.0, "x1": 0.0}
        if cy < HEADER_H:
            self.set_playhead(cx / self.pps)
            self._press["mode"] = "seek"
            return
        hit = self._hit_clip(cx, cy)
        if hit is None:
            self.set_playhead(cx / self.pps)
            self._press["mode"] = "seek"
            self.select(None)
            return
        self._press_row = None
        for t, y0, y1 in self.track_rows():
            if y0 <= cy < y1:
                self._press_row = t.kind
                break
        clip, x0, x1 = hit
        if evt.state & 0x4:          # Ctrl：追加/切换多选
            if clip.id in self._multi:
                self._multi.discard(clip.id)
            else:
                self._multi.add(clip.id)
            self.selected_id = clip.id if clip.id in self._multi else (
                next(iter(self._multi), None))
            self.refresh()
            if self.on_select:
                self.on_select(self.find_clip(self.selected_id or ""))
        else:
            self._multi = {clip.id}
            self.select(clip.id)
        self._press["clip"] = clip
        self._press["x0"], self._press["x1"] = x0, x1

    def _on_drag(self, evt):
        p = getattr(self, "_press", None)
        if p is None:
            return
        cx, cy = int(self.canvasx(evt.x)), int(self.canvasy(evt.y))
        if p["mode"] == "seek":
            self.set_playhead(cx / self.pps)
            return
        if p["clip"] is None:
            return
        # 阈值判定：小于 8px 视为单击（跳转），超过才进入拖动
        if not p["moving"]:
            if abs(cx - p["x"]) < 8 and abs(cy - p["y"]) < 8:
                return
            p["moving"] = True
            clip = p["clip"]
            edge = 5.0
            if abs(cx - p["x0"]) <= edge:
                mode = "trim_l"
            elif abs(cx - p["x1"]) <= edge:
                mode = "trim_r"
            else:
                mode = "move"
            self._drag = {
                "mode": mode, "clip_id": clip.id,
                "start_x": p["x"],
                "start_ts": clip.ts,
                "start_in": getattr(clip, "in_point", 0),
                "start_out": getattr(clip, "out_point",
                                      clip.timeline_duration()),
                "start_dur": clip.timeline_duration(),
            }
            if self.on_drag_start:
                self.on_drag_start()
        d = self._drag
        if d is None:
            return
        clip = self.project.find_clip(d["clip_id"])
        if clip is None:
            return
        # 跨轨拖拽：纵向超过半条轨高 → 换轨（一次即可，防抖动）
        for t, y0, y1 in self.track_rows():
            if y0 <= cy < y1 and t.kind != self._press_row and \
                    abs(cy - p["y"]) > 20:
                if self.on_move_track:
                    self.on_move_track(clip, t.kind)
                self._press_row = t.kind
                self._drag = None
                self._dragging = False
                return
        self._dragging = True
        dx = (cx - d["start_x"]) / self.pps

        if d["mode"] == "move":
            new_ts = max(0.0, round(d["start_ts"] + dx, 2))
            new_ts = self._snap(new_ts, except_clip_id=clip.id)
            clip.ts = new_ts

        elif d["mode"] == "trim_l":
            new_ts = max(0.0, round(d["start_ts"] + dx, 2))
            new_ts = self._snap(new_ts, except_clip_id=clip.id)
            shift = d["start_ts"] - new_ts
            clip.ts = new_ts
            if hasattr(clip, "in_point") and not isinstance(clip, ImageClip) \
                    and not isinstance(clip, AudioClip):
                spd = clip.speed if clip.speed > 0 else 1.0
                clip.in_point = max(0.0, d["start_in"] + shift * spd)

        elif d["mode"] == "trim_r":
            new_dur = max(0.2, round(d["start_dur"] + dx, 2))
            edge_t = self._snap(d["start_ts"] + new_dur,
                                except_clip_id=clip.id)
            clip.duration = max(0.2, round(edge_t - clip.ts, 2))
            if hasattr(clip, "out_point") and not isinstance(clip, ImageClip) \
                    and not isinstance(clip, AudioClip):
                spd = clip.speed if clip.speed > 0 else 1.0
                clip.out_point = d["start_in"] + clip.duration * spd

        self._edit_dirty = True
        self.refresh()
        if self.on_clips_changed:
            self.on_clips_changed()

    def _on_release(self, _evt):
        lightweight = self._dragging
        self._dragging = False
        p = getattr(self, "_press", None)
        self._press = None
        if lightweight:
            self.refresh()   # 拖动结束：恢复全量绘制
        if getattr(self, "_edit_dirty", False):
            self._edit_dirty = False
            if self.on_edit_commit:
                self.on_edit_commit()
        if p is not None and not p["moving"] and p["mode"] is None \
                and p["clip"] is not None:
            # 单击片段 = 跳转到该时间点（不再弹出任何面板）
            cx = int(self.canvasx(_evt.x))
            self.set_playhead(cx / self.pps)
        self._drag = None
        if self.on_release:
            self.on_release()

    def _on_wheel(self, evt):
        """滚轮=横向滚动；Ctrl+滚轮=缩放。"""
        if evt.state & 0x4:
            self.zoom(1.15 if evt.delta > 0 else 0.87)
            return
        dx = -evt.delta / 120 * 60.0
        cw = self.content_width()
        cur = self.xview()[0]
        self.xview_moveto(max(0.0, min(1.0, cur + dx / max(cw, 1))))

    def hit_clip_at(self, x, y):
        hit = self._hit_clip(x, y)
        return hit[0] if hit else None

    def _on_double(self, evt):
        ex, ey = int(self.canvasx(evt.x)), int(self.canvasy(evt.y))
        if ey < HEADER_H:
            return
        hit = self._hit_clip(ex, ey)
        if hit and self.on_open:
            self.on_open(hit[0])

    def time_at_x(self, x: float) -> float:
        """像素→时间：供拖拽落点换算。"""
        return max(x / self.pps, 0.0)

    def set_drop_hint(self, sec: float):
        """拖拽落点提示：竖线 + '放这里'。"""
        try:
            self.delete("drophint")
            x = max(sec, 0.0) * self.pps
            self.create_line(x, HEADER_H, x, self.height_needed(),
                             fill="#4a9eff", width=2, dash=(5, 3),
                             tags="drophint")
            self.create_text(x + 4, HEADER_H + 4, anchor="nw", text="放这里",
                             fill="#4a9eff", font=("Microsoft YaHei UI", 9),
                             tags="drophint")
        except Exception:
            pass

    def clear_drop_hint(self):
        try:
            self.delete("drophint")
        except Exception:
            pass

    def _on_right(self, evt):
        clip = self.hit_clip_at(self.canvasx(evt.x), self.canvasy(evt.y))
        if clip is not None:
            self.select(clip.id)
        if self.on_rightclick:
            self.on_rightclick(clip, evt.x_root, evt.y_root)

    def selected_ids(self) -> list:
        """当前选中（含多选）的片段 id 列表。"""
        ids = sorted(self._multi) if self._multi else []
        if self.selected_id and self.selected_id not in ids:
            ids.append(self.selected_id)
        return ids

    def select(self, clip_id: Optional[str], notify: bool = True):
        self.selected_id = clip_id
        self._multi = {clip_id} if clip_id else set()
        self.refresh()
        if notify and self.on_select:
            clip = self.project.find_clip(clip_id) if clip_id else None
            self.on_select(clip)