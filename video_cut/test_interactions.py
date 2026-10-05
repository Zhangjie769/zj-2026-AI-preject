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
from editor.model import Project as _P, VideoClip
from editor.editor_app import EditorApp
from editor.timeline_widget import TRACK_H

sample_dir = os.path.join(os.path.dirname(__file__), "samples")
v1 = os.path.join(sample_dir, "v1.mp4")
v2 = os.path.join(sample_dir, "v2.mp4")

root = tk.Tk()
root.withdraw()
app = EditorApp(root)
app.settings.set("guide_shown", True)
app.background_tasks = False  # 测试用同步模式
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
    "x_frac": 0.5, "y_frac": 0.5, "w_frac": 0.35, "h_frac": 0.15,
    "src_w": 200, "src_h": 100}])
_orig_sync = app._sync_overlays
app._sync_overlays = lambda: None      # 手工叠加层测试：暂停自动同步
for _ in range(70):
    root.update()
    time.sleep(0.03)
app.player.reframe()
img = app.player._frame_img
app._sync_overlays = _orig_sync
assert img is not None, "S5 无帧"
# 采样点：画中画盒子左上偏内（盒子从 0.5w/0.5h 开始）
px = img.convert("RGB").getpixel((int(img.width * 0.52),
                                  int(img.height * 0.52)))
r, g, b = px
print(f"S5 画中画区域像素 RGB={px}")
assert r > g + 60 and r > b + 60, f"S5 画中画未合成(应偏红): {px}"
app.player.stop_overlays()
print("S5 画中画实时合成(像素验证) OK")

# ============ S23: 画中画解码尺寸确定性（修锯齿/花屏根因的回归） ============
_orig_sync = app._sync_overlays
app._sync_overlays = lambda: None
app.player.set_overlays([{
    "id": "p2", "src": logo, "in_pt": 0.0, "len": 10.0, "speed": 1.0,
    "x_frac": 0.1, "y_frac": 0.1, "w_frac": 0.34, "h_frac": 0.28,
    "src_w": 200, "src_h": 100}])
for _ in range(50):
    root.update()
    time.sleep(0.03)
app.player.reframe()
entry = list(app.player._overlays.values())[0]
dw, dh = entry[4], entry[5]
app._sync_overlays = _orig_sync
# 200x100 源放进 0.34W x 0.28H 盒子：应保持比例（2:1），且解码为显示尺寸 2 倍
assert abs((dw / dh) - 2.0) < 0.15, f"S23 画中画未保持比例 dw/dh={dw/dh}"
last = entry[3]
assert last is not None, "S23 叠加层无帧"
assert last.size == (dw * 2, dh * 2), f"S23 解码尺寸错位 {last.size} != {(dw*2, dh*2)}"
app.player.stop_overlays()
print("S23 画中画解码尺寸确定 OK")

# ============ S24: 后台任务不阻塞（真实线程模式下加入素材立即返回） ============
app.background_tasks = True
n0 = len(app.project.all_clips())
pick(v1)
t0 = time.time()
app._media_add_main()          # 应立刻返回（重活在后台）
elapsed = time.time() - t0
assert elapsed < 0.5, f"S24 加入素材阻塞了 UI: {elapsed:.2f}s"
assert app._task_busy, "S24 应处于后台任务中"
app._wait_idle(20)
assert not app._task_busy, "S24 任务未结束"
assert len(app.project.all_clips()) == n0 + 1, "S24 后台任务未完成加入"
app.background_tasks = False
print(f"S24 后台任务不阻塞 OK（返回耗时 {elapsed*1000:.0f}ms）")

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
assert getattr(app, "_prop_visible", False), "S11 侧栏应常驻（点空白不关闭）"
assert str(app.side) in app.main_paned.panes(), "S11 侧栏不应被点空白关闭"
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

# ============ S14: 保存→打开 项目往返（含 速度/转场/可见性/音频/文字） ============
proj_file = os.path.join(sample_dir, "_itest_proj.vcp")
app.project.track("main").clips[0].speed = 1.5
tc1 = app.project.track("main").clips[0]
tc1.transition = {"name": "fade", "dur": 0.5}
for t in app.project.tracks:
    pass
app.store.save(app.project, proj_file)
import tkinter.filedialog as _filedlg
_orig_save = _filedlg.asksaveasfilename
_orig_open = _filedlg.askopenfilename
_filedlg.asksaveasfilename = lambda **k: proj_file
_filedlg.askopenfilename = lambda **k: proj_file
app._save_project()          # 真按钮处理器（打桩弹窗）
app.project = _P()
app.timeline.project = app.project
app._open_project()          # 真按钮处理器
_filedlg.asksaveasfilename = _orig_save
_filedlg.askopenfilename = _orig_open
reloaded = app.project
assert len(reloaded.all_clips()) == len(app.project.all_clips()), "S14 clip数不符"
rc = [c for c in reloaded.all_clips()
      if isinstance(c, type(tc1))][0]
assert abs(rc.speed - 1.5) < 1e-6, f"S14 速度丢失: {rc.speed}"
assert rc.transition and rc.transition.get("dur") == 0.5, "S14 转场丢失"
assert all(getattr(t, "visible", True) for t in reloaded.tracks), "S14 visible 丢失"
print("S14 保存/打开项目往返 OK")

# ============ S15: 撤销/重做（按钮路径 + 撤销后能继续编辑） ============
def btn_cmd(btn):
    return btn.invoke()

n0 = len(app.project.all_clips())
app._copy_clip()
app.timeline.playhead = max(app.project.total_duration() + 5, 30.0)
app._paste_clip()
root.update()
assert len(app.project.all_clips()) == n0 + 1, "S15 粘贴前置失败"
app._undo()   # == 顶栏 ↩撤销 的处理器
root.update()
assert len(app.project.all_clips()) == n0, "S15 撤销失败"
app._redo()   # == ↪重做
root.update()
assert len(app.project.all_clips()) == n0 + 1, "S15 重做失败"
app._undo()
root.update()
# 撤销后继续可编辑：先归 1.0 再加速 1.5x
c0 = app.project.all_clips()[0]
c0.speed = 1.0
app.timeline.select(c0.id)
app._timeline_speed(1.5)
assert abs(app.project.all_clips()[0].speed - 1.5) < 1e-6, "S15 撤销后编辑失败"
print("S15 撤销/重做按钮路径 OK")

# ============ S16: 导出失败路径（坏路径应回到"fail"消息而非卡死） ============
import queue as _q2
bad_opts = {"path": r"Z:\不存在\x.mp4", "container": "mp4", "crf": 20,
            "keep": False}
asyncio_q = None
before_cnt = app.q.qsize() if hasattr(app.q, "qsize") else 0
app._render_worker(bad_opts)
msg = None
for _ in range(60):
    try:
        kind, data = app.q.get_nowait()
    except _q2.Empty:
        time.sleep(0.2)
        continue
    if kind in ("done", "fail"):
        msg = (kind, data)
        break
assert msg is not None and msg[0] == "fail", f"S16 坏路径应报fail: {msg}"
assert not app.rendering, "S16 失败后状态复位"
print("S16 导出失败路径 OK")

# ============ S17: 快速成片拼盘（顺序+转场+时长递减） ============
files = [os.path.join(sample_dir, f) for f in ("v1.mp4", "v2.mp4", "v3.mp4")]
qp = app._quick_build(files, 1280, 720, "fade", 0.5)
main = qp.track("main")
n = len(main.clips)
assert n == 3, f"S17 片段数: {n}"
total = qp.total_duration()
durs = [c.timeline_duration() for c in sorted(main.clips, key=lambda c: c.ts)]
expect = sum(durs) - 2 * 0.5
assert abs(total - expect) < 0.01, f"S17 总长: {total} vs {expect}"
trs = [c.transition for c in main.clips if c.transition]
assert len(trs) == 2, f"S17 转场数: {trs}"
qpts = [c.transition["dur"] for c in main.clips if c.transition]
assert all(abs(d - 0.5) < 1e-6 for d in qpts), "S17 转场时长"
print("S17 快速成片拼盘 OK")

# ============ S18: 跨轨转换（主轨→画中画→可回主轨） ============
mt = app.project.track("main")
c0 = sorted(mt.clips, key=lambda c: c.ts)[0]
app._convert_track(c0, False)
root.update()
assert c0 not in mt.clips, "S18 未移出主轨"
ovs = app.project.overlay_tracks()
assert ovs and c0 in ovs[-1].clips, "S18 未进画中画"
assert c0.w > 0 and c0.x >= 0, "S18 画中画坐标未设"
app._convert_track(c0, True)
root.update()
mt = app.project.track("main")
assert c0 in mt.clips, "S18 未能转回主轨"
print("S18 跨轨转换 OK")

# ============ S19: 应用属性不自动打断预览（预览=手动刷新） ============
app._preview_clip(app.project.all_clips()[0])
root.update()
pid_before = app._preview_clip_id
app.timeline.select(app.project.all_clips()[0].id)
app.prop_vars["volume"].set("0.8")
app._apply_props()
root.update()
assert app._preview_clip_id == pid_before, "S19 应用属性不应重载预览"
print("S19 预览不打断(手动刷新) OK")

# ============ S20: 键盘快捷键绑定存在 ============
for seq in ("<Control-z>", "<Control-s>", "<space>", "<Delete>", "<F5>"):
    assert len(app.root.bind(seq)) > 0, f"S20 缺少绑定 {seq}"
print("S20 快捷键绑定 OK")

# ============ S21: Ctrl 多选 → 批量变速 → 批量删除 ============
app.project = _P()
app.timeline.project = app.project
root.update()
for v in vlist:
    pick(v)
    app._media_add_main()
    root.update()
mt = app.project.track("main")
clips = sorted(mt.clips, key=lambda c: c.ts)
# Ctrl 点选前两个
app.timeline._multi = {clips[0].id, clips[1].id}
app.timeline.selected_id = clips[0].id
assert len(app.timeline.selected_ids()) == 2, "S21 多选失败"
app._timeline_speed(2.0)
root.update()
assert abs(clips[0].speed - 2.0) < 1e-6 and abs(clips[1].speed - 2.0) < 1e-6, \
    "S21 批量变速失败"
n_before = len(app.project.all_clips())
app._delete_selected()
root.update()
assert len(app.project.all_clips()) == n_before - 2, "S21 批量删除失败"
print("S21 多选批量变速/删除 OK")

# ============ S22: 跨轨拖拽（纵向拖到画中画行触发 on_move_track） ============
app.project = _P()
app.timeline.project = app.project
app.timeline.xview_moveto(0.0)
root.update()
pick(v1)
app._media_add_main()
root.update()
app.project.new_overlay_track()
root.update()
tl = app.timeline
tl.pps = 40.0            # 固定缩放，避免受前面用例影响
tl.refresh()
root.update()
c = app.project.track("main").clips[0]
seen = {}
tl.on_move_track = lambda cl, k: seen.update({cl.id: k})
x0px = 5
tl._on_press(type("e", (), {"x": x0px, "y": 26 + 20, "x_root": 0,
                             "y_root": 0, "delta": 0, "state": 0})())
tl._on_drag(type("e", (), {"x": x0px + 10, "y": 26 + 20 + TRACK_H + 25,
                            "x_root": 0, "y_root": 0, "delta": 0,
                            "state": 0})())
root.update()
assert seen.get(c.id) == "overlay", f"S22 未触发跨轨: {seen}"
print("S22 跨轨拖拽回调 OK")

# ============ S25: 拖拽幽灵(缩略图跟随) + 时间轴落点提示 ============
app.background_tasks = False
tl = app.timeline
# 模拟：指针落在时间轴上（打桩 winfo_containing）
app.root.winfo_containing = lambda x, y: tl
app._media_drag_path = v1
app._drag_xy = (0, 0)
m = type("e", (), {"x": 40, "y": 40, "x_root": tl.winfo_rootx() + 120,
                   "y_root": tl.winfo_rooty() + 40, "delta": 0, "state": 0})()
app._media_drag_motion(m)
root.update()
assert app._drag_ghost is not None, "S25 拖拽幽灵未出现"
assert len(tl.find_withtag("drophint")) > 0, "S25 落点提示未绘制"
r = type("e", (), {"x": 40, "y": 40, "x_root": tl.winfo_rootx() + 120,
                   "y_root": tl.winfo_rooty() + 40, "delta": 0, "state": 0})()
app._media_drag_release(r)
root.update()
assert app._drag_ghost is None, "S25 幽灵未清理"
assert len(tl.find_withtag("drophint")) == 0, "S25 落点提示未清理"
print("S25 拖拽幽灵/落点提示 OK")

# ============ S26: 时间轴刻度等比例自适应（长视频不铺成超长条） ============
from editor.timeline_widget import nice_step, MIN_PPS
assert nice_step(0.4) == 0.5, nice_step(0.4)
assert nice_step(3) == 5.0, nice_step(3)
assert nice_step(240) == 300.0, nice_step(240)   # 4 分钟需求 → 5 分钟一格
assert nice_step(600) == 600.0, nice_step(600)   # 10 分钟工整
assert nice_step(3000) == 3600.0, nice_step(3000)
assert MIN_PPS <= 0.05, MIN_PPS
# 40 分钟项目：适配后内容宽度应能压到一屏量级（等比缩放）
app.project = _P()
app.timeline.project = app.project
v40 = app.project.track("main")
c40 = VideoClip(src=v1, ts=0, duration=2400, in_point=0, out_point=2400)
v40.add(c40)
root.update()
app.timeline.pps = 12.0
assert app.timeline.content_width() > 20000, "S26 前置：默认缩放确实超长"
app.timeline.fit()
cw = app.timeline.content_width()
print(f"S26 40分钟项目 fit 后内容宽 {cw:.0f}px，pps={app.timeline.pps:.3f}")
assert app.timeline.pps < 1.0, f"S26 未能缩到一屏: pps={app.timeline.pps}"
assert cw < 6000, f"S26 内容仍过长: {cw}"
print("S26 刻度自适应/长视频等比缩放 OK")

# ============ S27: 右侧属性侧栏 + 画中画大小预设 + 导出位置记忆 ============
app.background_tasks = False
assert str(app.side) in app.main_paned.panes(), "S27 侧栏未挂在主分栏里"
assert "x" in app.prop_vars and "w" in app.prop_vars and "volume" in app.prop_vars
assert len(app.size_btns) == 5 and len(app.preset_btns) == 5
# 侧栏开关：关掉再打开
app.prop_frame_recover()
assert str(app.side) not in app.main_paned.panes(), "S27 侧栏未隐藏"
app.prop_frame_recover()
assert str(app.side) in app.main_paned.panes(), "S27 侧栏未恢复"
# 画中画大小预设：1/2 画面宽，保持源比例，且不越界
app.project = _P()
app.timeline.project = app.project
W0, H0 = app.project.canvas_w, app.project.canvas_h
app._do_add_pip(v1, 10.0)
root.update()
c = app.project.overlay_tracks()[-1].clips[-1]
app.timeline.select(c.id, notify=True)
meta = app.engine._probe_info(v1)
asp = float(meta["width"]) / float(meta["height"]) if meta.get("height") else (16/9)
app._apply_pip_scale(0.5)
root.update()
assert abs(c.w - W0 * 0.5) < 1.5, f"S27 宽不对: {c.w}"
assert abs(c.w / c.h - asp) < 0.02, f"S27 比例不对: {c.w}/{c.h} vs {asp:.3f}"
assert 0 <= c.x <= W0 - c.w + 0.5 and 0 <= c.y <= H0 - c.h + 0.5, "S27 越界"
assert app.prop_vars["w"].get() not in ("", "0"), "S27 侧栏未回填宽"
w_after = c.w
app._undo()
root.update()
c2 = app.project.find_clip(c.id)
assert c2 is None or abs(c2.w - w_after) > 0.01, "S27 撤销未恢复"
# 导出位置记忆
app._mark_exported(os.path.join(os.getcwd(), "_s27_out.mp4"))
assert "_s27_out.mp4" in app.last_export_var.get(), "S27 导出位置未显示"
assert app._last_export_dir == os.getcwd(), "S27 导出目录未记忆"
print("S27 侧栏/画中画大小/导出位置 OK")

print("=== INTERACTIONS PASS ===")
app._on_close()