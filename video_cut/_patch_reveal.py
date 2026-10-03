# -*- coding: utf-8 -*-
"""editor_app: 属性窗改为手动开；拼接后 reveal（短片整条可见，长片滚到新段）"""
import io

p = r"D:\my_AI_practice\video_cut\editor\editor_app.py"
src = io.open(p, encoding="utf-8").read()

def rep(old, new, anchor):
    global src
    assert old in src, f"missing: {anchor}"
    src = src.replace(old, new, 1)

# 1) 选中片段不再自动弹属性窗（改为：只填充，弹窗归 ▦属性 按钮管）
rep(
    '''        # 极简：选中自动弹属性窗，无选中自动收起
        if clip is not None and not self._prop_visible:
            self.prop_frame_recover()
        elif clip is None and self._prop_visible:
            self.prop_frame_recover()''',
    '''        # 不再自动弹出属性窗（有需要点工具栏「▦ 属性」，避免打扰）''',
    "no auto prop")

# 2) 删除"每次编辑都适配"：改由 _reveal_clip 决定视图
rep(
    "        self._refresh_controls()\n        self._maybe_fit()\n        # 预取音频波形",
    "        self._refresh_controls()\n        # 预取音频波形",
    "remove maybe_fit")

# 3) _maybe_fit 替换为 reveal 逻辑（短片整条可见=能看见变长；长片工作缩放+滚到新段）
rep(
    '''    def _maybe_fit(self):
        """内容超出可视区域 → 自动适配，保证整条时间轴同屏可见。"""
        try:
            w = self.timeline.winfo_width()
            if w > 50 and self.timeline.content_width() > w * 1.02:
                self.timeline.fit()
        except Exception:
            pass''',
    '''    def _reveal_clip(self, clip):
        """拼完新片段后的视图策略：
        - 总片长较短（能整条放进视野）：自动适配 → 你能亲眼看到时间轴变长
        - 总片长较长：保持工作缩放，滚到新片段处（避免时间轴被压成蚂蚁线）
        """
        try:
            w = self.timeline.winfo_width()
            if w <= 50:
                return
            total = self.project.total_duration()
            if total * 4 <= w:          # 粗刻度下能整条放下
                self.timeline.fit()
                return
            # 长片：确保新片段在视野内，宽度不小于 60px
            clip_w = clip.timeline_duration() * self.timeline.pps
            if clip_w > 6 and clip_w < 60:
                self.timeline.pps = max(60 / clip.timeline_duration(),
                                        self.timeline.pps)
                self.timeline.refresh()
            self.timeline.set_playhead(clip.ts, drive_timeline=False)
            self.timeline.see_playhead()
        except Exception:
            pass''',
    "reveal")

# 4) 拼接后调用 reveal（替换旧的 set_playhead/see_playhead/fit 块）
rep(
    '''        self.timeline.set_playhead(clip.ts, drive_timeline=False)
        # 确保新片段和总长都在可视范围内（剪映式：拼完必能看到变长）
        if (self.timeline.content_width() >
                self.timeline.winfo_width() * 1.25):
            self.timeline.fit()
        self.timeline.see_playhead()''',
    '''        self._reveal_clip(clip)''',
    "add reveal call")

# 5) 时间轴松手 → 冲刷节流 seek
rep(
    "        self.timeline.on_rightclick = self._timeline_context_menu",
    "        self.timeline.on_rightclick = self._timeline_context_menu\n"
    "        self.timeline.on_release = self._flush_seek",
    "on_release wire")

io.open(p, "w", encoding="utf-8", newline="\n").write(src)
check = io.open(p, encoding="utf-8").read()
for t in ("_reveal_clip", "on_release = self._flush_seek"):
    assert t in check, t
print("APP REVEAL/NO-PROP OK")