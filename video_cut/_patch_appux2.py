# -*- coding: utf-8 -*-
"""editor_app: 片段缩略图数据源 + 拼接后视图必伸展 + 总时长醒目（行列表法）"""
import io

p = r"D:\my_AI_practice\video_cut\editor\editor_app.py"
src = io.open(p, encoding="utf-8").read()

def rep(old, new, anchor):
    assert old in src, f"missing: {anchor}"
    return src.replace(old, new, 1)

L = []

# 1) 数据源接入
rep(
    "        self.timeline.get_wave = lambda path: self.wave_peaks.get(path)",
    "        self.timeline.get_wave = lambda path: self.wave_peaks.get(path)\n"
    "        self.timeline.get_thumb = self._timeline_thumb",
    "get_thumb wire")
print("step1 ok")

# 2) 缩略图提供方法
old = "    # ============ 复制 / 粘贴 ============"
assert old in src, "missing anchor2"
lines = src.split("\n")
idx = next(i for i, l in enumerate(lines) if "复制 / 粘贴" in l)
method = [
    "    def _timeline_thumb(self, path: str):",
    '        """时间轴片段迷你缩略图（同步取缓存，防 GC）。"""',
    "        try:",
    "            key = path",
    "            ph = self.thumb_photos.get(key)",
    "            if ph is not None:",
    "                return ph",
    "            kind = self._thumb_kind.get(path, 'video')",
    "            from PIL import ImageTk",
    "            im = self.thumbs.generate(path, kind)",
    "            if im is None:",
    "                return None",
    "            im.thumbnail((64, 34))",
    "            ph = ImageTk.PhotoImage(im)",
    "            self.thumb_photos[key] = ph",
    "            return ph",
    "        except Exception:",
    "            return None",
    "",
]
lines[idx:idx] = method
src = "\n".join(lines)
print("step2 ok")

# 3) 拼接后视图必伸展
rep(
    "        self.timeline.set_playhead(clip.ts, drive_timeline=False)\n"
    "        self.timeline.see_playhead()\n"
    "        if self.timeline.content_width() > self.timeline.winfo_width() * 1.6:\n"
    "            self.timeline.fit()\n"
    "            self.timeline.see_playhead()",
    "        self.timeline.set_playhead(clip.ts, drive_timeline=False)\n"
    "        # 确保新片段和总长都在可视范围内（剪映式：拼完必能看到变长）\n"
    "        if (self.timeline.content_width() >\n"
    "                self.timeline.winfo_width() * 1.25):\n"
    "            self.timeline.fit()\n"
    "        self.timeline.see_playhead()",
    "auto fit")
print("step3 ok")

# 4) 状态栏总时长
rep(
    "        self.status_var.set(f'✅ 已加入主轨（第 {len(track.clips)} 个视频）：'\n"
    "                            f'{os.path.basename(path)}')",
    "        total = self.project.total_duration()\n"
    "        self.status_var.set(\n"
    "            f'✅ 已加入主轨（第 {len(track.clips)} 个视频）：'\n"
    "            f'{os.path.basename(path)}｜总时长 {self._fmt(total)}'\n"
    "            '（继续双击/拖拽素材即可往后拼）')",
    "status total")
print("step4 ok")

io.open(p, "w", encoding="utf-8", newline="\n").write(src)
check = io.open(p, encoding="utf-8").read()
for t in ("_timeline_thumb", "总时长"):
    assert t in check, t
print("APP TIMELINE UX OK")
