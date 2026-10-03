# -*- coding: utf-8 -*-
"""preview: reframe（暂停时也合成叠加层）+ app 每帧同步叠加层"""
import io

p = r"D:\my_AI_practice\video_cut\editor\preview.py"
src = io.open(p, encoding="utf-8").read()

old = '''    def stop_overlays(self):
        for k in list(self._overlays.keys()):
            self._stop_overlay(k)'''
new = '''    def stop_overlays(self):
        for k in list(self._overlays.keys()):
            self._stop_overlay(k)

    def has_overlays(self) -> bool:
        return bool(self._overlays)

    def reframe(self):
        """强制重绘当前帧（暂停时叠加层新帧到达后刷新画面）。"""
        if self._frame_img is not None:
            try:
                self._show(self._frame_img)
            except Exception as e:
                log.debug("reframe 失败: %s", e)'''
assert old in src, "reframe anchor"
src = src.replace(old, new)
io.open(p, "w", encoding="utf-8", newline="\n").write(src)
print("PREVIEW REFRAME OK")

# ---- app 侧同步 ----
p2 = r"D:\my_AI_practice\video_cut\editor\editor_app.py"
s2 = io.open(p2, encoding="utf-8").read()

old = """    def _preview_tick(self):
        self.player.tick()
        self.root.after(33, self._preview_tick)"""
new = """    def _preview_tick(self):
        self.player.tick()
        self._sync_overlays()
        self.root.after(33, self._preview_tick)

    def _sync_overlays(self):
        \"\"\"把当前时间轴上活跃的画中画片段同步到预览叠加层（变身实时预览）。\"\"\"
        try:
            t_abs = self._preview_ts + self.player._pos
            specs = []
            for t in self.project.overlay_tracks():
                for c in t.clips:
                    if c.ts <= t_abs < c.ts + c.timeline_duration():
                        spd = c.speed if c.speed > 0 else 1.0
                        local = (t_abs - c.ts) * spd
                        _len = c.timeline_duration()
                        specs.append({
                            "id": c.id,
                            "src": c.src,
                            "in_pt": c.in_point + local,
                            "len": max(_len - local / max(spd, 1e-6), 0.05),
                            "speed": spd,
                            "x_frac": float(getattr(c, "x", 0)) /
                                      max(self.project.canvas_w, 1),
                            "y_frac": float(getattr(c, "y", 0)) /
                                      max(self.project.canvas_h, 1),
                            "w_frac": float(getattr(c, "w", 160)) /
                                      max(self.project.canvas_w, 1),
                            "h_frac": float(getattr(c, "h", 90)) /
                                      max(self.project.canvas_h, 1),
                        })
            self.player.set_overlays(specs)
            if not self.player._playing and self.player.has_overlays():
                self.player.reframe()
        except Exception as e:
            log.debug("叠加层同步失败: %s", e)"""
assert old in s2, "tick anchor"
src2 = s2.replace(old, new, 1)
io.open(p2, "w", encoding="utf-8", newline="\n").write(src2)
print("APP SYNC OK")