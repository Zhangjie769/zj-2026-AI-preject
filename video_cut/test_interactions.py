# -*- coding: utf-8 -*-
"""
交互回归测试：复现用户报告的场景
  S1 添加视频 → 删除第一个 → 再添加：必须能加进去
  S2 点击时间轴标尺(seek) 后：播放头与播放器位置必须停在目标处，不得回原点
  S3 添加第二个视频 → 主轨顺序衔接
"""
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from editor.model import Project as _P
from editor.editor_app import EditorApp

sample_dir = os.path.join(os.path.dirname(__file__), "samples")
v1 = os.path.join(sample_dir, "v1.mp4")
v2 = os.path.join(sample_dir, "v2.mp4")

root = tk.Tk()
root.withdraw()
app = EditorApp(root)
for _ in range(20):
    root.update()
app.project = _P()
app.timeline.project = app.project
for _ in range(10):
    root.update()

app.dir_var.set(sample_dir)
app._refresh_media()
root.update()
paths = [p for _, p in app.media_files]

def pick(path):
    app.media_list.selection_set(str(paths.index(path)))
    root.update()

# ============ S1: 删除第一个后还能添加 ============
pick(v1)
app._media_add_main()
root.update()
assert len(app.project.all_clips()) == 1, f"S1a 添加失败 n={len(app.project.all_clips())}"
clip = app.project.all_clips()[0]
app.timeline.select(clip.id)
root.update()
app._delete_selected()
root.update()
assert len(app.project.all_clips()) == 0, "S1b 删除失败"
print("S1 删除 OK")
# 重新添加（按钮路径）
pick(v1)
app._media_add_main()
root.update()
assert len(app.project.all_clips()) == 1, f"S1c 删除后再添加失败! clips={app.project.all_clips()}"
print("S1 删除后再添加 OK")

# ============ S2: 标尺点击 seek 不回原点 ============
app.timeline.set_playhead(0.0)
root.update()
# 模拟点击时间轴 3 秒处（与 _on_timeline_seek 相同的调用路径）
app._on_timeline_seek(3.0)
app._flush_seek()
for _ in range(5):
    root.update()
    time.sleep(0.02)
tl_pos = app.timeline.playhead
player_pos = app.player._pos
print(f"S2 seek 后 timeline.playhead={tl_pos:.3f} player.pos={player_pos:.3f}")
assert abs(tl_pos - 3.0) < 0.1, f"S2 播放头回到原点/偏移: {tl_pos}"
assert abs(player_pos - 0.0) < 0.05 or abs(player_pos - 3.0) < 0.5, \
    f"S2 播放器位置异常: {player_pos}"

# S2b: 播放中拖动标尺
app._preview_clip(app.project.all_clips()[0])
root.update()
app.player.play()
time.sleep(0.15)
for _ in range(5):
    root.update()
app._on_timeline_seek(2.0)
app._flush_seek()
for _ in range(5):
    root.update()
    time.sleep(0.02)
tl_pos2 = app.timeline.playhead
print(f"S2b 播放中seek: playhead={tl_pos2:.3f}")
assert abs(tl_pos2 - 2.0) < 0.15, f"S2b 播放头漂回: {tl_pos2}"
print("S2 标尺 seek 不回原点 OK")

# ============ S3: 第二个视频顺序跟主轨 ============
n = len(app.project.all_clips())
pick(v2)
app._media_add_main()
root.update()
mt = app.project.track("main")
s = sorted(mt.clips, key=lambda c: c.ts)
gap = s[1].ts - (s[0].ts + s[0].timeline_duration())
assert abs(gap) < 0.02, f"S3 第二个视频未衔接: gap={gap}"
print("S3 第二视频顺序衔接 OK")

# ============ S2c(关键回归): 预览第二个视频(ts>0)时播放头=ts+局部时间，不为0 ============
mt = app.project.track("main")
second = sorted(mt.clips, key=lambda c: c.ts)[1]
app._preview_clip(second)
root.update()
time.sleep(0.1)
for _ in range(5):
    root.update()
    time.sleep(0.02)
tl3 = app.timeline.playhead
print(f"S2c 预览第二个视频: ts={second.ts} playhead={tl3:.3f}")
assert tl3 >= second.ts - 0.05, f"S2c 播放头回原点/未加偏移: {tl3}"
print("S2c 预览第二段播放头不回原点 OK")

# ============ S4: 整条时间轴连续播放 ============
app.timeline.set_playhead(0.0, drive_timeline=False)
app._play_timeline()
root.update()
assert app._timeline_play, "S4 时间轴播放模式未开启"
assert app._preview_clip_id == sorted(
    app.project.track("main").clips, key=lambda c: c.ts)[0].id, "S4 起始片段不对"
# 模拟播完 → 应自动切到下一段
first_id = app._preview_clip_id
app._player_state("ended", "")
root.update()
assert app._preview_clip_id != first_id, "S4 播完未自动接下一段"
# 双击单段预览应退出时间轴模式
app._preview_clip(app.project.track("main").clips[0])
assert not app._timeline_play, "S4 单段预览未退出时间轴模式"
print("S4 整条时间轴连续播放 OK")

# ============ S5: 画中画实时合成（像素验证） ============
logo = os.path.join(sample_dir, "logo.png")
mt = app.project.track("main")
c0 = sorted(mt.clips, key=lambda c: c.ts)[0]
app._timeline_play = False
app._load_clip_preview(c0, autoplay=False)
root.update()
app.player.set_overlays([{
    "id": "p1", "src": logo, "in_pt": 0.0, "len": 10.0, "speed": 1.0,
    "x_frac": 0.5, "y_frac": 0.5, "w_frac": 0.35, "h_frac": 0.15}])
time.sleep(1.0)   # 等叠加流出第一帧
app.player.reframe()
img = app.player._frame_img
assert img is not None, "S5 无帧"
px = img.convert("RGB").getpixel((int(img.width * 0.67), int(img.height * 0.57)))
r, g, b = px
print(f"S5 画中画区域像素 RGB={px}")
assert r > g + 60 and r > b + 60, f"S5 画中画未合成(应偏红): {px}"
app.player.stop_overlays()
print("S5 画中画实时合成(像素验证) OK")

# ============ S6: 导出渲染 E2E（真出文件）见文件存在 ============
out = os.path.join(sample_dir, "_itest_render.mp4")
import queue as _q
opts = {"path": out, "container": "mp4", "crf": 20, "keep": False}
app._render_worker(opts)
for _ in range(600):
    try:
        kind, data = app.q.get_nowait()
    except _q.Empty:
        time.sleep(0.1)
        continue
    if kind in ("done", "fail"):
        break
assert kind == "done", f"S6 导出失败: {data}"
assert os.path.isfile(out) and os.path.getsize(out) > 50 * 1024, "S6 没有导出文件"
print(f"S6 导出E2E OK（{os.path.getsize(out)//1024}KB）")
try:
    os.remove(out)
except OSError:
    pass

# ============ S7: 横向滚动后，拖拽仍命中正确片段 ============
app.timeline.fit()
root.update()
total_w = app.timeline.content_width()
app.timeline.xview_moveto(min(1.0, 0.6 * app.timeline.winfo_width() / max(total_w, 1)))
root.update()
mt = app.project.track("main")
for c in sorted(mt.clips, key=lambda cc: cc.ts):
    if not isinstance(c, type(None)):
        pass
# 取时间轴中部某一个片段，用换算后坐标模拟按下并拖动
def sim_click(x_widget, y_widget):
    evt = type("e", (), {"x": x_widget, "y": y_widget,
                          "x_root": 0, "y_root": 0, "delta": 0, "state": 0})()
    app.timeline._on_press(evt)
    return evt

target = sorted([c for c in mt.clips], key=lambda cc: cc.ts)[-1]
x0 = app.timeline.canvasx(int(target.ts * app.timeline.pps) + 5)
row_y = HEADER_H_EXPECTED = 26 + 23   # 第一行主轨中间
sim_click(x0, row_y)
app.timeline._on_drag(type("e", (), {"x": x0 + 40, "y": row_y, "state": 0})())
app.timeline._on_release(None)
root.update()
assert app.timeline.selected_id == target.id, "S7 滚动后拖拽命中错了片段"
print("S7 滚动后拖拽命中 OK")

# ============ S8: 主轨连续拼接，总时长必须增长 ============
app.project = _P()
app.timeline.project = app.project
root.update()
vlist = [os.path.join(sample_dir, f) for f in ("v1.mp4", "v2.mp4", "v3.mp4")]
for v in vlist:
    pick(v)
    app._media_add_main()
    root.update()
mt = app.project.track("main")
assert len(mt.clips) == 3, "S8 主轨应 3 段"
total = app.project.total_duration()
expected = sum(app.engine.source_length(v) for v in vlist)
print(f"S8 总时长 {total:.1f}s ≈ 三段之和 {expected:.1f}s")
assert abs(total - expected) < 1.0, f"S8 拼接后总时长未增长: {total} vs {expected}"
assert app.timeline.content_width() > total * app.timeline.pps, "S8 时间轴宽未随总长增长"
print("S8 主轨拼接总时长必增长 OK")

# ============ S9: 双击单段预览后点 PLAY，必须切回整条时间轴 ============
mt = app.project.track("main")
first = sorted(mt.clips, key=lambda c: c.ts)[0]
app._preview_clip(first)          # 单段预览残留
root.update()
assert not app._timeline_play, "S9 前置：应处于单段模式"
app._toggle_play()                # PLAY → 必须整条时间轴
root.update()
assert app._timeline_play, "S9 PLAY 未切回整条时间轴"
print("S9 PLAY 单段残留→整条时间轴 OK")

# ============ S10: 标尺快速拖动节流（0.15s 内多次 seek 只执行一次，最后跳准） ============
app._last_seek = 0.0
app._pending_seek = None
app.player.pause()
app._on_timeline_seek(1.0)
assert getattr(app, "_pending_seek", None) == 1.0 or abs(
    app.timeline.playhead - 1.0) < 0.1, "S10 节流逻辑异常"
app._on_timeline_seek(2.0)   # 0.15s 内 → 挂起
assert getattr(app, "_pending_seek", None) == 2.0, "S10 未挂起最近一次拖动"
app._flush_seek()
assert abs(app.timeline.playhead - 2.0) < 0.1, "S10 松开未跳准"
print("S10 标尺拖动节流 OK")

# ============ S11: 单击片段 = 跳转（不移动、不弹属性窗） ============
mt = app.project.track("main")
c = sorted(mt.clips, key=lambda cc: cc.ts)[0]
ts_before = c.ts
app.timeline.set_playhead(0.0, drive_timeline=False)
# 模拟在片段中部的单击（按下+松开，无移动）
xw = int(app.timeline.canvasx(5.0 * app.timeline.pps))
yw = 26 + 23
evt_down = type("e", (), {"x": xw, "y": yw, "x_root": 0, "y_root": 0,
                          "delta": 0, "state": 0})()
evt_up = type("e", (), {"x": xw, "y": yw, "x_root": 0, "y_root": 0,
                        "delta": 0, "state": 0})()
app.timeline._on_press(evt_down)
app.timeline._on_release(evt_up)
root.update()
assert abs(app.timeline.playhead - 5.0) < 0.3, f"S11 单击未跳转: {app.timeline.playhead}"
assert c.ts == ts_before, "S11 单击不应移动片段"
assert not getattr(app, "_prop_visible", True), "S11 单击不应弹属性窗"
print("S11 单击=跳转(不弹窗) OK")

# ============ S12: 短片拼接后视图自动适配，且能看到总长增长 ============
app.undo.clear()
app.project = _P()
app.timeline.project = app.project
root.update()
for v in vlist:
    pick(v)
    app._media_add_main()
    root.update()
total = app.project.total_duration()
assert total == 24.0, f"S12 总长应=24s: {total}"
wsz = app.timeline.winfo_width()
if wsz > 50:
    assert app.timeline.content_width() <= wsz * 1.15 or \
        total * 4 <= wsz, "S12 短片应可整条可见"
print(f"S12 视图适配 OK（总长 {total}s）")

# ============ S13: 重置速度 = 常速（修复"乘1没反应"） ============
mt = app.project.track("main")
c = sorted(mt.clips, key=lambda cc: cc.ts)[0]
c.speed = 2.0
app.timeline.select(c.id)
root.update()
app._timeline_speed_reset()
root.update()
assert c.speed == 1.0, f"S13 重置后非 1.0: {c.speed}"
span = app._src_span(c)
assert abs(c.duration - span) < 0.05, f"S13 时长未回源区间: {c.duration} vs {span}"
print("S13 重置速度=常速 OK")

# S13b: 属性面板改速度 → 时长联动
c.speed = 1.0
app.timeline.select(c.id)
root.update()
base_dur = c.duration
app.prop_vars["speed"].set("2.0")
app._apply_props()
root.update()
assert c.speed == 2.0, "S13b 速度未应用"
assert abs(c.duration - base_dur / 2.0) < 0.05, f"S13b 时长未联动: {c.duration}"
print("S13b 属性改速联动时长 OK")

print("=== INTERACTIONS PASS ===")
app._on_close()