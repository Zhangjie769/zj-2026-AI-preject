# -*- coding: utf-8 -*-
"""UI 冒烟测试：实例化 EditorApp，驱动若干轮事件循环，确认无异常，然后退出。"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from editor.editor_app import EditorApp

root = tk.Tk()
root.withdraw()  # 不显示窗口也能初始化

app = EditorApp(root)
for _ in range(30):
    root.update()
    root.after(20)

# 从干净项目开始（上一轮测试可能留下了 autosave.vcp 会被恢复）
# 注意：不要用 _new_project()（有确认对话框会阻塞/挂起自动化测试）
from editor.model import Project as _P
app.project = _P()
app.timeline.project = app.project
for _ in range(10):
    root.update()

# 模拟：加一个片段到时间轴（用样例媒体）
sample_dir = os.path.join(os.path.dirname(__file__), "samples")
if not os.path.isdir(sample_dir):
    os.makedirs(sample_dir, exist_ok=True)
    from test_engine import make_samples
    make_samples(sample_dir)

v1 = os.path.join(sample_dir, "v1.mp4")
music = os.path.join(sample_dir, "music.wav")
app.dir_var.set(sample_dir)
app._refresh_media()
assert app.media_files, "媒体扫描为空"
paths = [p for _, p in app.media_files]
assert v1 in paths, "视频未被扫描"

# 选中 v1.mp4 后：三个加入按钮都应可用（修过的 bug：主轨按钮曾永远禁用）
idx = paths.index(v1)
app.media_list.selection_set(str(idx))
root.update()
app._media_select_changed()
for b in (app.btn_media_main, app.btn_media_pip, app.btn_media_audio):
    assert "disabled" not in b.state(), "选中素材后按钮应可用"
print("素材按钮状态 OK")
app._media_add_main()
root.update()
assert len(app.project.all_clips()) == 1, "添加主轨片段失败"
app._media_add_pip()
root.update()
assert len(app.project.all_clips()) == 2, "添加画中画片段失败"

# 音频轨：用"双击自动入轨"路径添加（新交互）
if music in paths:
    idx = paths.index(music)
    app.media_list.selection_set(str(idx))
    root.update()
    app._media_add_auto()
    root.update()
    assert len(app.project.all_clips()) == 3, "添加音频片段失败"
    from editor.model import AudioClip
    assert any(isinstance(c, AudioClip) for c in app.project.all_clips()), "音频类型错误"
    print("双击自动入轨(音频) OK")

# 画中画顺序化：连加两个画中画，时间轴 ts 不应重叠（叠着是 bug）
app.media_list.selection_set(str(paths.index(v1)))
app._media_add_pip()
root.update()
app._media_add_pip()
root.update()
ov = app.project.overlay_tracks()
assert ov and len(ov) == 1, "画中画应顺序追加到同一条轨"
clips = sorted(ov[0].clips, key=lambda c: c.ts)
assert len(clips) >= 2 and clips[1].ts >= clips[0].ts + clips[0].timeline_duration() - 0.01, \
    "画中画片段叠着（应顺序排列）"
print("画中画顺序化 OK")

# 全屏轨（第二主轨）
app._media_add_full()
root.update()
fulls = [t for t in app.project.tracks if t.kind == "overlay"]
assert len(fulls) >= 1
last = fulls[-1].clips[-1]
assert last.w == app.project.canvas_w and last.h == app.project.canvas_h, "全屏轨未满屏"
print("全屏轨 OK")

# 拖拽落点逻辑（直接调 _drop_media）：视频必须顺序跟主轨，而不是进画中画
v3 = os.path.join(sample_dir, "v3.mp4")
n0 = len(app.project.all_clips())
app._drop_media(v1, 1.0, 60)   # 拖第一个视频
root.update()
app._drop_media(v3, 9999.0, 1)  # 拖第二个视频（任意区域）
root.update()
mt = app.project.track("main")
assert len(mt.clips) >= 2, "拖拽视频应顺序跟主轨"
s = sorted(mt.clips, key=lambda c: c.ts)
gap = s[1].ts - (s[0].ts + s[0].timeline_duration())
assert abs(gap) < 0.02, f"主轨未顺序衔接: gap={gap}"
assert len(app.project.all_clips()) == n0 + 2, "拖拽数量不对"
print("拖拽路由(视频顺序跟主轨) OK")

# 时间轴滚轮缩放不崩溃 + 右键变速
app.timeline.zoom(1.0)
app.timeline._on_wheel(type("e", (), {"delta": 120, "state": 0x4})())
assert app.timeline.pps > 12, "滚轮放大未生效"
apple = app.project.all_clips()[0]
app.timeline.select(apple.id)
spd0 = apple.speed
app._timeline_speed(1.25)
assert abs(apple.speed - spd0 * 1.25) < 1e-6, "右键加速未生效"
print("滚轮缩放/右键变速 OK")

# 撤销/重做：先复制+粘贴(数量+1)，再撤销回原数
n = len(app.project.all_clips())
clip_x = app.project.all_clips()[0]
app.timeline.select(clip_x.id)
app._copy_clip()
app.timeline.playhead = max(app.project.total_duration() + 5, 30.0)
app._paste_clip()
root.update()
assert len(app.project.all_clips()) == n + 1, "粘贴失败"
app._undo()
root.update()
assert len(app.project.all_clips()) == n, "撤销失败"
app._redo()
root.update()
assert len(app.project.all_clips()) == n + 1, "重做失败"
app._undo()
root.update()

# 项目设置对话框逻辑（直接改）
app._push_undo()
app.project.canvas_w, app.project.canvas_h, app.project.fps = 1280, 720, 30
root.update()
app._after_model_change()
assert app.project.canvas_h == 720, "分辨率设置失败"

# 日志文件与状态记忆检查
import time
time.sleep(0.2)
assert os.path.isfile(os.path.join(app.base_dir, "logs", "app.log")), "日志未生成"
app._persist_state()  # 模拟用户关闭窗口时的状态记忆
assert os.path.isfile(os.path.join(app.base_dir, "settings.json")), "状态未记忆"

# 选中 + 属性填充
clip = app.project.all_clips()[0]
app.timeline.select(clip.id)
root.update()
assert app.prop_vars["speed"].get() != "", "属性面板未填充"

# 时间轴缩放/刷新
app.timeline.zoom(2.0)
app.timeline.fit()
app.timeline.refresh()
root.update()

# 自动保存检查
app.store.request_autosave(app.project, app.base_dir)
import time
time.sleep(0.6)
assert os.path.isfile(app.store.autosave_path(app.base_dir)), "自动保存未生成"

# 闭合空隙（波纹）检查：先制造空隙再闭合
mt = app.project.track("main")
clips0 = sorted(mt.clips, key=lambda c: c.ts)
if len(clips0) >= 2:
    clips0[1].ts += 3.0  # 人为制造空隙
    moved = mt.close_gaps()
    assert moved >= 1, "闭合空隙未生效"
    s2 = sorted(mt.clips, key=lambda c: c.ts)
    gaps = [s2[i + 1].ts - (s2[i].ts + s2[i].timeline_duration())
            for i in range(len(s2) - 1)]
    assert all(abs(g) < 0.02 for g in gaps), f"仍有空隙: {gaps}"
    print("闭合空隙 OK")

# 磁吸检查（时间轴控件）
app.timeline.snap_enabled = True
app.timeline._snap(9.97)  # 不应抛异常
app.timeline.snap_enabled = False
print("磁吸逻辑 OK")

# 复制/粘贴检查
n0 = len(app.project.all_clips())
clip = app.project.all_clips()[0]
app.timeline.select(clip.id)
root.update()
app._copy_clip()
app.timeline.playhead = 20.0
app._paste_clip()
root.update()
assert len(app.project.all_clips()) == n0 + 1, "粘贴失败"
print("复制/粘贴 OK")

# 控件可用性检查（UX：没加载素材时播放/进度条应禁用）
app.player.stop()  # 卸载预览
app.player._path = None
app._refresh_controls()
assert "disabled" in app.seek_bar.state(), "无素材时进度条应禁用"
assert "disabled" in app.btn_play.state(), "无素材时播放按钮应禁用"
print("控件禁用逻辑 OK")
print("UI 冒烟测试全部通过")
app._on_close()

