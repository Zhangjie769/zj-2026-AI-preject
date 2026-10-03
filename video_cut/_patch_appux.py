# -*- coding: utf-8 -*-
"""editor_app: 片段缩略图数据源 + 拼接后视图必伸展 + 总时长醒目提示"""
import io

p = r"D:\my_AI_practice\video_cut\editor\editor_app.py"
src = io.open(p, encoding="utf-8").read()

def rep(old, new, anchor):
    assert old in src, f"missing: {anchor}"
    return src.replace(old, new, 1)

# 1) 数据源接入（放在 _restore_state 之前的某个 setup 点：构建时间轴后）
src = rep(
    "        self.timeline.get_wave = lambda path: self.wave_peaks.get(path)",
    "        self.timeline.get_wave = lambda path: self.wave_peaks.get(path)\n"
    "        self.timeline.get_thumb = self._timeline_thumb",
    "get_thumb wire")

# 2) 缩略图同步提供（复用 thumbs 缓存，防回收）
src = rep(
    "    # ============ 画中画/图层相关 ============",
    "    def _timeline_thumb(self, path: str):
        \"\"\"时间轴片段迷你缩略图（同步从缓存取，防 GC）。\"\"\"
        try:
            key = path
            ph = self.thumb_photos.get(key)
            if ph is not None:
                return ph
            kind = self._thumb_kind.get(path, \"video\")
            from PIL import ImageTk
            im = self.thumbs.generate(path, kind)
            if im is None:
                return None
            im.thumbnail((64, 34))
            ph = ImageTk.PhotoImage(im)
            self.thumb_photos[key] = ph
            return ph
        except Exception:
            return None

    # ============ 画中画/图层相关 ============",
    "thumb provider")

# 3) 拼接后：视图必伸展到能看到总长（改阈值）＋状态栏带总时长
src = rep(
    '''        self.timeline.set_playhead(clip.ts, drive_timeline=False)
        self.timeline.see_playhead()
        if self.timeline.content_width() > self.timeline.winfo_width() * 1.6:
            self.timeline.fit()
            self.timeline.see_playhead()''',
    '''        self.timeline.set_playhead(clip.ts, drive_timeline=False)
        # 确保新片段和总长都在可视范围内（剪映式：拼完必能看到变长）
        need = (self.timeline.content_width() >
                self.timeline.winfo_width() * 1.25)
        if need:
            self.timeline.fit()
        self.timeline.see_playhead()''',
    "auto fit")

src = rep(
    '''        self.status_var.set(f"✅ 已加入主轨（第 {len(track.clips)} 个视频）："
                            f"{os.path.basename(path)}")''',
    '''        total = self.project.total_duration()
        self.status_var.set(
            f"✅ 已加入主轨（第 {len(track.clips)} 个视频）："
            f"{os.path.basename(path)}｜总时长 {self._fmt(total)}"
            "（继续双击/拖拽素材即可往后拼）")''',
    "status total")

io.open(p, "w", encoding="utf-8", newline="\n").write(src)
check = io.open(p, encoding="utf-8").read()
for t in ("_timeline_thumb", "总时长"):
    assert t in check, t
print("APP TIMELINE UX OK")