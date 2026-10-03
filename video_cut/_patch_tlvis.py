# -*- coding: utf-8 -*-
"""timeline: 隐藏轨道不出现在行里"""
import io

p = r"D:\my_AI_practice\video_cut\editor\timeline_widget.py"
src = io.open(p, encoding="utf-8").read()

old = '''        rows = []
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
        return rows'''
new = '''        rows = []
        y = HEADER_H
        mt = self.project.track("main", create=False)
        if mt is not None and mt.visible:
            rows.append((mt, y, y + TRACK_H))
            y += TRACK_H
        for t in self.project.overlay_tracks():
            if t.visible:
                rows.append((t, y, y + TRACK_H))
                y += TRACK_H
        for t in self.project.audio_tracks():
            if t.visible:
                rows.append((t, y, y + TRACK_H))
                y += TRACK_H
        for t in self.project.text_tracks():
            if t.visible:
                rows.append((t, y, y + TRACK_H))
                y += TRACK_H
        return rows'''
assert old in src, "rows anchor"
src = src.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\n").write(src)
print("TIMELINE VISIBLE OK")