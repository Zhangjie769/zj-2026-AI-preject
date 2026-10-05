# -*- coding: utf-8 -*-
"""
editor/editor_app.py —— 主窗口组装（v2）
媒体栏 / 预览(画面+音频) / 属性 / 时间轴 / 导出 / 撤销重做 / 状态恢复 / 日志

功能速览：
  - 素材：视频/图片/音频 三类，分别进 主轨/画中画轨/音频轨
  - 预览：画面 + 声音同步播放（sounddevice），空格播放暂停
  - 项目：目标分辨率/帧率设置；.vcp 保存打开；自动保存 + 恢复
  - 人性化：撤销/重做(Ctrl+Z/Y)、记住上次窗口/目录/时间轴状态、
           最近项目菜单、日志查看器、删除键删片段
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from . import __version__, resolve_ffmpeg, resolve_ffprobe
from .theme import apply_dark_theme
from . import logger as _logmod
from .engine import Engine, RenderError, TRANSITIONS
from PIL import Image as _PILImage
from .model import (AudioClip, ImageClip, Project, TextClip, VideoClip,
                    get_filter, set_filter)
from .preview import PreviewPlayer
from .project_store import ProjectStore
from .settings_store import SettingsStore
from .thumbs import ThumbCache
from .timeline_widget import TimelineWidget
from .undo import UndoManager
import time as _time_now
from .wave import WaveCache
from .model import get_filter, set_filter

log = _logmod.get_logger("editor_app")

MEDIA_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".flv",
                    ".wmv", ".webm", ".m4v", ".mpg", ".mpeg", ".3gp"}
MEDIA_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
MEDIA_AUDIO_EXTS = {".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg",
                    ".opus", ".wma"}

PIP_PRESETS = {
    "满屏": None,
    "左上": (0.02, 0.02),
    "右上": (0.64, 0.02),
    "左下": (0.02, 0.64),
    "右下": (0.64, 0.64),
}
CANVAS_PRESETS = [
    ("1920×1080 (横屏)", 1920, 1080),
    ("1280×720", 1280, 720),
    ("3840×2160 (4K)", 3840, 2160),
    ("1080×1920 (竖屏)", 1080, 1920),
]


def fmt1(x: float) -> str:
    r = f"{x:.3f}"
    if "." in r:
        r = r.rstrip("0").rstrip(".")
    return r


class EditorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"视频剪辑器 v{__version__}")

        _logmod.setup_logging(self._app_dir())
        log.info("应用启动 v%s", __version__)

        self.ffmpeg = resolve_ffmpeg()
        self.ffprobe = resolve_ffprobe()
        self.engine = Engine(ffmpeg=self.ffmpeg or "ffmpeg",
                             ffprobe=self.ffprobe or "ffprobe")
        self.store = ProjectStore()
        self.settings = SettingsStore(self._app_dir())
        self.project = Project()
        self.base_dir = self._app_dir()

        self.q: "queue.Queue" = queue.Queue()
        self.rendering = False
        self._preview_clip_id: str | None = None
        self._preview_ts = 0.0   # 预览片段在时间轴上的起点（播放头=绝对时间）
        self._timeline_play = False  # 整条时间轴连续播放模式
        self.undo = UndoManager()
        # 缩略图 / 波形缓存
        cache_dir = os.path.join(self._app_dir(), "thumbs_cache")
        self.thumbs = ThumbCache(cache_dir, self.ffmpeg or "ffmpeg")
        self.thumbs.on_ready = self._on_thumb_ready
        self.waves = WaveCache(cache_dir, self.ffmpeg or "ffmpeg")
        self.waves.on_ready = self._on_wave_ready
        self.wave_peaks: dict = {}          # path -> peaks
        self.thumb_photos: dict = {}        # path -> PhotoImage（防回收）
        self._thumb_kind: dict = {}         # path -> kind
        self.background_tasks = True        # 重活是否放后台线程（测试可设 False）
        self._task_busy = False
        self._task_name = ""
        self._busy_mask = None
        self._busy_lbl = None
        self._title_base = None
        self.ui_q: "queue.Queue" = queue.Queue()   # 后台线程 → UI 线程 的任务队列

        self._build_ui()
        self._restore_state()
        self._refresh_media()

        self.root.after(120, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(33, self._preview_tick)
        self.root.after(2000, self._auto_refresh_media)
        self.root.after(150, self._refresh_controls)
        self._bind_shortcuts()
        self.root.after(700, self._maybe_show_guide)

    def _bind_shortcuts(self):
        """集中键盘快捷键（曾因补丁被误删，现统一回归）。"""
        r = self.root
        r.bind("<Control-z>", lambda e: self._undo())
        r.bind("<Control-Z>", lambda e: self._undo())
        r.bind("<Control-y>", lambda e: self._redo())
        r.bind("<Control-Y>", lambda e: self._redo())
        r.bind("<Control-o>", lambda e: self._open_project())
        r.bind("<Control-O>", lambda e: self._open_project())
        r.bind("<Control-s>", lambda e: self._save_project())
        r.bind("<Control-S>", lambda e: self._save_project())
        r.bind("<Control-c>", lambda e: self._copy_clip())
        r.bind("<Control-C>", lambda e: self._copy_clip())
        r.bind("<Control-v>", lambda e: self._paste_clip())
        r.bind("<Control-V>", lambda e: self._paste_clip())
        r.bind("<Delete>", lambda e: self._delete_selected())
        r.bind("<space>", lambda e: self._toggle_play())
        r.bind("<F5>", lambda e: self._refresh_media())
        r.bind("<Up>", lambda e: self._cycle_selection(-1))
        r.bind("<Down>", lambda e: self._cycle_selection(1))

    def _app_dir(self) -> str:
        """数据目录：源码运行=项目根；打包运行=exe 同目录。"""
        from . import bundled_dir
        return bundled_dir()

    # ================================================================ UI
    def _build_ui(self):
        menubar = tk.Menu(self.root)

        fm = tk.Menu(menubar, tearoff=0)
        fm.add_command(label="新建项目", command=self._new_project)
        fm.add_command(label="打开项目…", command=self._open_project,
                       accelerator="Ctrl+O")
        self.recent_menu = tk.Menu(fm, tearoff=0)
        fm.add_cascade(label="最近项目", menu=self.recent_menu)
        fm.add_command(label="⚡ 快速成片…", command=self._quick_produce_dialog)
        fm.add_separator()
        fm.add_command(label="保存项目…", command=self._save_project,
                       accelerator="Ctrl+S")
        fm.add_separator()
        fm.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=fm)

        em = tk.Menu(menubar, tearoff=0)
        em.add_command(label="撤销", command=self._undo, accelerator="Ctrl+Z")
        em.add_command(label="重做", command=self._redo, accelerator="Ctrl+Y")
        em.add_separator()
        em.add_command(label="删除选中片段", command=self._delete_selected,
                       accelerator="Delete")
        menubar.add_cascade(label="编辑", menu=em)

        pm = tk.Menu(menubar, tearoff=0)
        pm.add_command(label="项目设置（分辨率/帧率）…",
                       command=self._project_settings)
        menubar.add_cascade(label="项目", menu=pm)

        hm = tk.Menu(menubar, tearoff=0)
        hm.add_command(label="使用说明", command=self._show_help)
        hm.add_command(label="查看日志文件", command=self._open_log_file)
        hm.add_command(label="日志面板", command=self._log_panel)
        menubar.add_cascade(label="帮助", menu=hm)
        self.root.config(menu=menubar)

        # ---- 工具栏（只留高频项；其余在 菜单/右键/时间轴栏） ----
        toolbar = ttk.Frame(self.root, padding=(6, 2))
        toolbar.pack(fill="x")

        def tbtn(text, cmd, tip=""):
            b = ttk.Button(toolbar, text=text, command=cmd)
            b.pack(side="left", padx=(0, 4))
            if tip:
                self._tooltip(b, tip)
            return b

        tbtn("新建", self._new_project, "新建项目（Ctrl+N）")
        tbtn("打开", self._open_project, "打开 .vcp 项目（Ctrl+O）")
        tbtn("保存", self._save_project, "保存项目（Ctrl+S）")
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y",
                                                       padx=6)
        tbtn("⚡ 快速成片", self._quick_produce_dialog,
             "选素材→自动拼接→导出，三步成片")
        self.tbtn_render = tbtn("🎬 导出视频", self._render_project,
                                "导出成品视频（格式/画质/输出位置可调）")
        tbtn("⟳ 预览", self._preview_refresh,
             "手动刷新预览（编辑轨道不会自动打断预览）")
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y",
                                                       padx=6)
        tbtn("↩ 撤销", self._undo, "撤销（Ctrl+Z）")
        tbtn("↪ 重做", self._redo, "重做（Ctrl+Y）")
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y",
                                                       padx=6)
        tbtn("◧ 画布", self._project_settings,
             "分辨率/帧率设置（例如 1920×1080、竖屏 9:16）")
        tbtn("▦ 侧栏", self.prop_frame_recover,
             "显示/隐藏右侧侧栏（画中画大小/速度/音量/导出）")
        tbtn("🗂 图层", self._layers_dialog,
             "图层面板：显示/隐藏、调整堆叠顺序、删轨道")
        tbtn("✂ 删除", self._delete_selected, "删除选中片段（Delete）")

        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True, padx=4, pady=4)

        # ============ 左：媒体栏 ============
        left = ttk.Frame(main, width=250)
        main.add(left, weight=0)

        ttk.Label(left, text="素材文件夹").pack(anchor="w", padx=6, pady=(6, 0))
        fd = ttk.Frame(left)
        fd.pack(fill="x", padx=6)
        self.dir_var = tk.StringVar()
        ttk.Entry(fd, textvariable=self.dir_var).pack(side="left", fill="x",
                                                      expand=True)
        ttk.Button(fd, text="…", width=3, command=self._browse_dir).pack(
            side="left", padx=(3, 0))
        self.btn_refresh_media = ttk.Button(fd, text="⟳", width=3,
                                            command=self._refresh_media)
        self.btn_refresh_media.pack(side="left", padx=(3, 0))

        style = ttk.Style(self.root)
        try:
            style.configure("Media.Treeview", rowheight=58,
                            font=("Microsoft YaHei UI", 9))
            style.configure("Media.Treeview.Item",
                            padding=(4, 2))
        except Exception:
            pass
        media_body = ttk.Frame(left)
        media_body.pack(fill="both", expand=True, padx=6, pady=4)
        self.media_list = ttk.Treeview(media_body, columns=("name",),
                                       show="tree", height=14,
                                       style="Media.Treeview")
        self.media_list.heading("#0", text="")
        self.media_list.column("#0", width=116, stretch=False)
        self.media_list.heading("name", text="素材（双击加主轨）")
        self.media_list.column("name", width=140, stretch=True)
        self.media_list.pack(side="left", fill="both", expand=True)
        media_scroll = ttk.Scrollbar(media_body, orient="vertical",
                                     command=self.media_list.yview)
        media_scroll.pack(side="right", fill="y")
        self.media_list.configure(yscrollcommand=media_scroll.set)
        self.media_list.bind("<Double-Button-1>", lambda e: self._media_add_auto())
        self.media_list.bind("<Button-3>", self._media_context_menu)
        self.media_list.bind("<ButtonPress-1>", self._media_drag_press)
        self.media_list.bind("<B1-Motion>", self._media_drag_motion)
        self.media_list.bind("<ButtonRelease-1>", self._media_drag_release)
        self._media_drag_path = None
        self._drag_ghost = None
        self._drag_ghost_photo = None
        self.media_list.bind("<<TreeviewSelect>>", self._media_select_changed)
        self.media_files: list = []

        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill="x", padx=6, pady=(0, 2))
        self.btn_media_main = ttk.Button(btn_frame, text="→ 主轨",
                                         command=self._media_add_main)
        self.btn_media_main.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.btn_media_pip = ttk.Button(btn_frame, text="→ 画中画",
                                        command=self._media_add_pip)
        self.btn_media_pip.pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.btn_media_audio = ttk.Button(btn_frame, text="→ 音频轨",
                                          command=self._media_add_audio)
        self.btn_media_audio.pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.btn_media_full = ttk.Button(btn_frame, text="全屏轨",
                                         command=self._media_add_full)
        self.btn_media_full.pack(side="left", fill="x", expand=True, padx=(2, 0))
        self._tooltip(self.btn_media_main, "把选中素材加到主轨（满屏、顺序拼接）")
        self._tooltip(self.btn_media_pip, "把选中素材加到画中画层（PiP，顺序排列不重叠）")
        self._tooltip(self.btn_media_audio, "把选中素材加到音频轨（背景乐/配音）")
        self._tooltip(self.btn_media_full, "加到全屏轨（可作为第二条主轨）")
        ttk.Label(left,
                  text="双击素材 = 自动加入（视频→主轨，图→画中画，音频→音频轨）\n"
                       "或 单击选中后点上方按钮；右键有菜单",
                  foreground="#ffd54f", font=("Microsoft YaHei UI", 8),
                  wraplength=230) \
            .pack(anchor="w", padx=6, pady=(0, 2))

        # ============ 右：预览 + 属性 + 时间轴 ============
        right = ttk.Frame(main)
        main.add(right, weight=1)

        # ---- 预览区 ----
        pv_frame = ttk.LabelFrame(right, text="预览（画面+声音）")
        pv_frame.pack(fill="x", padx=4, pady=(4, 2))
        self.preview_canvas = tk.Canvas(pv_frame, width=640, height=300,
                                        background="#111",
                                        highlightthickness=0)
        self.preview_canvas.pack(fill="x")
        self.player = PreviewPlayer(self.preview_canvas, self.ffmpeg or "ffmpeg",
                                    self.ffprobe or "ffprobe")
        self.player.on_tick = self._player_tick
        self.player.on_state = self._player_state

        ctrl = ttk.Frame(pv_frame)
        ctrl.pack(fill="x", padx=4, pady=3)
        self.btn_play = ttk.Button(ctrl, text="▶ 播放", width=8,
                                   command=self._toggle_play)
        self.btn_play.pack(side="left")
        self.btn_rewind = ttk.Button(ctrl, text="⏮ 回零", width=6,
                                     command=lambda: self.player.seek(0))
        self.btn_rewind.pack(side="left", padx=(3, 0))
        self.seek_var = tk.DoubleVar(value=0)
        self.seek_bar = ttk.Scale(ctrl, from_=0, to=100, variable=self.seek_var,
                                  command=self._seek_bar_drag)
        self.seek_bar.pack(side="left", fill="x", expand=True, padx=8)
        self.time_var = tk.StringVar(value="00:00 / 00:00")
        ttk.Label(ctrl, textvariable=self.time_var,
                  font=("Consolas", 9)).pack(side="left")
        self.btn_audition = ttk.Button(ctrl, text="试听音频", width=8,
                                       command=self._audition)
        self.btn_audition.pack(side="left", padx=(8, 0))

        # ---- 属性侧栏（右侧固定，可滚动）：片段属性 + 画中画 + 导出 ----
        self.main_paned = main
        self.side = ttk.Frame(main, width=352)
        main.add(self.side, weight=0)

        side_wrap = ttk.Frame(self.side)
        side_wrap.pack(fill="both", expand=True)
        try:
            _side_bg = ttk.Style(self.root).lookup("TFrame", "background")
        except Exception:
            _side_bg = ""
        self._side_canvas = tk.Canvas(side_wrap, bg=_side_bg or "#f0f0f0",
                                      highlightthickness=0, width=336)
        side_scroll = ttk.Scrollbar(side_wrap, orient="vertical",
                                    command=self._side_canvas.yview)
        self._side_inner = ttk.Frame(self._side_canvas)
        self._side_inner.bind(
            "<Configure>",
            lambda e: self._side_canvas.configure(
                scrollregion=self._side_canvas.bbox("all")))
        self._side_win_id = self._side_canvas.create_window(
            (0, 0), window=self._side_inner, anchor="nw")
        self._side_canvas.bind(
            "<Configure>",
            lambda e: self._side_canvas.itemconfigure(self._side_win_id,
                                                      width=e.width))
        self._side_canvas.configure(yscrollcommand=side_scroll.set)
        self._side_canvas.pack(side="left", fill="both", expand=True)
        side_scroll.pack(side="right", fill="y")
        self.root.bind_all("<MouseWheel>", self._side_scroll_wheel, add="+")
        self._prop_visible = True

        # ===== 导出成片（放最上面：一眼看到"视频放哪、点哪导出"）=====
        exp_side = ttk.LabelFrame(self._side_inner,
                                  text="导出成片（成品放这里）")
        exp_side.pack(fill="x", padx=4, pady=(4, 4))
        ttk.Button(exp_side, text="🎬 导出视频…",
                   command=self._render_project).pack(fill="x", padx=6,
                                                      pady=(6, 2))
        self._last_export_path = ""
        self._last_export_dir = ""
        self.last_export_var = tk.StringVar(value="导出位置：尚未导出")
        ttk.Label(exp_side, textvariable=self.last_export_var,
                  wraplength=310, foreground="#9a9a9a",
                  justify="left").pack(anchor="w", padx=6, pady=2)
        ttk.Button(exp_side, text="打开导出文件夹",
                   command=self._open_last_export_dir).pack(anchor="w",
                                                            padx=6,
                                                            pady=(0, 6))

        # ===== 片段属性 =====
        prop = ttk.LabelFrame(self._side_inner,
                              text="片段属性（选中片段后修改）")
        self._prop_frame = prop
        prop.pack(fill="x", padx=4, pady=4)
        grid = ttk.Frame(prop)
        grid.pack(fill="x", padx=6, pady=4)

        self.prop_vars = {}

        def pfield(parent, row, col, label, key, width=6):
            ttk.Label(parent, text=label).grid(row=row, column=col,
                                               sticky="e", padx=(2, 1), pady=2)
            var = tk.StringVar(value="")
            ttk.Entry(parent, textvariable=var, width=width).grid(
                row=row, column=col + 1, sticky="w", padx=(0, 8), pady=2)
            self.prop_vars[key] = var
            return var

        pfield(grid, 0, 0, "源起点(秒)", "in_point")
        pfield(grid, 0, 2, "源终点(秒)", "out_point")
        pfield(grid, 1, 0, "时长(秒)", "duration")
        pfield(grid, 1, 2, "不透明度", "opacity")
        pfield(grid, 2, 0, "速度(x)", "speed")
        pfield(grid, 2, 2, "音量(x)", "volume")
        pfield(grid, 3, 0, "淡入(秒)", "fade_in", 5)
        pfield(grid, 3, 2, "淡出(秒)", "fade_out", 5)
        pfield(grid, 4, 0, "渐变起速(x)", "ramp_start", 5)
        pfield(grid, 4, 2, "渐变末速(x)", "ramp_end", 5)
        pfield(grid, 5, 0, "渐变时长(秒)", "ramp_dur", 5)

        # 常用速度快捷按钮
        spd_row = ttk.Frame(grid)
        spd_row.grid(row=6, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(spd_row, text="快捷速度").pack(side="left")
        self.spd_btns = []
        for sp in ("0.5", "0.75", "1", "1.5", "2", "4"):
            b = ttk.Button(spd_row, text=f"{sp}x", width=3,
                           command=lambda v=float(sp): self._apply_speed(v))
            b.pack(side="left", padx=1)
            self.spd_btns.append(b)

        # 变速到目标时长
        tgt_row = ttk.Frame(grid)
        tgt_row.grid(row=7, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(tgt_row, text="变速到目标时长(秒)").pack(side="left")
        self.target_dur_var = tk.StringVar(value="10")
        ttk.Entry(tgt_row, textvariable=self.target_dur_var,
                  width=7).pack(side="left", padx=3)
        self.btn_target_dur = ttk.Button(tgt_row, text="应用", width=5,
                                         command=self._apply_target_duration)
        self.btn_target_dur.pack(side="left")

        # 滤镜
        f_row = ttk.Frame(grid)
        f_row.grid(row=8, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(f_row, text="滤镜").pack(side="left")
        self.filter_vars = {}
        for fk, ftxt in [("brightness", "亮度"), ("contrast", "对比"),
                         ("saturation", "饱和")]:
            ttk.Label(f_row, text=ftxt).pack(side="left", padx=(4, 1))
            var = tk.StringVar(value="1.00")
            ttk.Entry(f_row, textvariable=var, width=4).pack(side="left")
            self.filter_vars[fk] = var
        self.gray_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f_row, text="黑白", variable=self.gray_var).pack(
            side="left", padx=(4, 0))

        # 转场（到下一段）
        tr_row = ttk.Frame(grid)
        tr_row.grid(row=9, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(tr_row, text="转场(到下一段)").pack(side="left")
        self.transition_var = tk.StringVar(value="无")
        self.transition_combo = ttk.Combobox(
            tr_row, textvariable=self.transition_var, state="readonly",
            width=9, values=["无"] + TRANSITIONS)
        self.transition_combo.pack(side="left", padx=3)
        self.transition_dur_var = tk.StringVar(value="0.5")
        ttk.Entry(tr_row, textvariable=self.transition_dur_var,
                  width=5).pack(side="left")
        ttk.Label(tr_row, text="秒", foreground="#888").pack(side="left")

        # ===== 文字 / 字幕 =====
        txt_frame = ttk.LabelFrame(self._side_inner, text="文字 / 字幕")
        txt_frame.pack(fill="x", padx=4, pady=(0, 4))
        tg = ttk.Frame(txt_frame)
        tg.pack(fill="x", padx=6, pady=4)
        ttk.Label(tg, text="内容").grid(row=0, column=0, sticky="e", padx=(2, 1))
        self.text_vars = {}
        tvar = tk.StringVar(value="")
        ttk.Entry(tg, textvariable=tvar, width=22).grid(
            row=0, column=1, columnspan=4, sticky="we", padx=(0, 6), pady=2)
        self.text_vars["content"] = tvar
        ttk.Label(tg, text="字号").grid(row=1, column=0, sticky="e", padx=(2, 1))
        fvar = tk.StringVar(value="48")
        ttk.Entry(tg, textvariable=fvar, width=4).grid(
            row=1, column=1, sticky="w", pady=2)
        self.text_vars["font_size"] = fvar
        ttk.Label(tg, text="颜色").grid(row=1, column=2, sticky="e",
                                        padx=(6, 1))
        cvar = tk.StringVar(value="#FFFFFF")
        ttk.Combobox(tg, textvariable=cvar, state="readonly", width=9,
                     values=["#FFFFFF 白", "#FFD700 黄", "#FF5555 红",
                             "#000000 黑", "#55DDFF 青"]).grid(
            row=1, column=3, sticky="w", pady=2)
        self.text_vars["color"] = cvar
        ttk.Label(tg, text="对齐").grid(row=1, column=4, sticky="e",
                                        padx=(6, 1))
        avar = tk.StringVar(value="bottom")
        ttk.Combobox(tg, textvariable=avar, state="readonly", width=6,
                     values=["bottom", "center", "top"]).grid(
            row=1, column=5, sticky="w", pady=2)
        self.text_vars["align"] = avar

        # ===== 画中画：大小 / 位置 =====
        pip_fr = ttk.LabelFrame(self._side_inner, text="画中画：大小 / 位置")
        pip_fr.pack(fill="x", padx=4, pady=(0, 4))
        pg = ttk.Frame(pip_fr)
        pg.pack(fill="x", padx=6, pady=4)
        for i, (key, label) in enumerate([("x", "位置 X"), ("y", "位置 Y"),
                                          ("w", "宽"), ("h", "高")]):
            ttk.Label(pg, text=label).grid(row=i // 2, column=(i % 2) * 2,
                                           sticky="e", padx=(2, 1), pady=2)
            var = tk.StringVar(value="")
            ttk.Entry(pg, textvariable=var, width=7).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w",
                padx=(0, 10), pady=2)
            self.prop_vars[key] = var
        ttk.Label(pip_fr, text="位置预设", foreground="#888").pack(
            anchor="w", padx=6)
        pos_row = ttk.Frame(pip_fr)
        pos_row.pack(fill="x", padx=6, pady=(0, 2))
        self.preset_btns = []
        for name in PIP_PRESETS:
            b = ttk.Button(pos_row, text=name, width=6,
                           command=lambda n=name: self._apply_preset(n))
            b.pack(side="left", padx=1)
            self.preset_btns.append(b)
        ttk.Label(pip_fr, text="大小预设（按画面比例，保持源比例）",
                  foreground="#888").pack(anchor="w", padx=6)
        size_row = ttk.Frame(pip_fr)
        size_row.pack(fill="x", padx=6, pady=(0, 6))
        self.size_btns = []
        for name, frac in (("原始", 1.0), ("3/4", 0.75), ("1/2", 0.5),
                           ("1/3", 1 / 3), ("1/4", 0.25)):
            b = ttk.Button(size_row, text=name, width=5,
                           command=lambda f=frac: self._apply_pip_scale(f))
            b.pack(side="left", padx=1)
            self.size_btns.append(b)

        # ===== 操作 =====
        act = ttk.LabelFrame(self._side_inner, text="操作")
        act.pack(fill="x", padx=4, pady=(0, 4))
        ag = ttk.Frame(act)
        ag.pack(fill="x", padx=6, pady=4)
        self.btn_apply = ttk.Button(ag, text="✔ 应用修改",
                                    command=self._apply_props)
        self.btn_apply.pack(fill="x", pady=2)
        self.btn_delete = ttk.Button(ag, text="删除片段",
                                     command=self._delete_selected)
        self.btn_delete.pack(fill="x", pady=2)
        self.btn_ripple = ttk.Button(ag, text="波纹删除（闭合接缝）",
                                     command=self._ripple_delete)
        self.btn_ripple.pack(fill="x", pady=2)
        self.btn_split = ttk.Button(ag, text="在播放头分割",
                                    command=self._split_at_playhead)
        self.btn_split.pack(fill="x", pady=2)
        self.btn_close_gaps = ttk.Button(ag, text="闭合本轨空隙",
                                         command=self._close_gaps)
        self.btn_close_gaps.pack(fill="x", pady=2)
        ur = ttk.Frame(ag)
        ur.pack(fill="x", pady=(6, 2))
        ttk.Button(ur, text="↩ 撤销", command=self._undo).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        ttk.Button(ur, text="↪ 重做", command=self._redo).pack(
            side="left", expand=True, fill="x", padx=(2, 0))

        # ---- 导出（进度与状态常驻，按钮在工具栏） ----
        self._exp_frame = ttk.Frame(right)
        exp = self._exp_frame
        exp.pack(fill="x", padx=4, pady=2)
        ttk.Label(exp, text="导出进度:").pack(side="left")
        self.render_progress = ttk.Progressbar(exp, mode="determinate")
        self.render_progress.pack(side="left", fill="x", expand=True, padx=8)
        self.status_var = tk.StringVar(value="就绪 · 导出点右侧「🎬 导出视频」")
        ttk.Label(exp, textvariable=self.status_var,
                  foreground="#888").pack(side="left")

        # ---- 时间轴 ----
        tl_frame = ttk.LabelFrame(right, text="时间轴")
        tl_frame.pack(fill="both", expand=True, padx=4, pady=(2, 4))

        tl_toolbar = ttk.Frame(tl_frame)
        tl_toolbar.pack(fill="x", padx=4, pady=2)
        ttk.Button(tl_toolbar, text="− 缩小", width=7,
                   command=lambda: self.timeline.zoom(0.6)).pack(side="left")
        ttk.Button(tl_toolbar, text="＋ 放大", width=7,
                   command=lambda: self.timeline.zoom(1.6)).pack(
            side="left", padx=(3, 0))
        ttk.Button(tl_toolbar, text="适配", width=7,
                   command=lambda: self.timeline.fit()).pack(side="left", padx=(3, 0))
        self.snap_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(tl_toolbar, text="磁吸", variable=self.snap_var,
                        command=self._toggle_snap).pack(side="left", padx=(8, 0))
        ttk.Button(tl_toolbar, text="闭合全部空隙", width=10,
                   command=self._close_all_gaps).pack(side="left", padx=(4, 0))
        self.tl_time_var = tk.StringVar(value="00:00")
        ttk.Label(tl_toolbar, textvariable=self.tl_time_var,
                  font=("Consolas", 10)).pack(side="right")

        tl_body = ttk.Frame(tl_frame)
        tl_body.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.timeline = TimelineWidget(tl_body, self.project)
        ttk.Scrollbar(tl_body, orient="horizontal",
                      command=self.timeline.xview).pack(side="bottom", fill="x")
        self.timeline.pack(fill="both", expand=True)

        self.timeline.on_select = self._on_clip_selected
        self.timeline.on_open = self._preview_clip
        self.timeline.on_seek = self._on_timeline_seek
        self.timeline.on_clips_changed = self._on_clips_changed_light
        self.timeline.on_edit_commit = self._commit_timeline_edit
        self.timeline.on_drag_start = self._push_undo
        self.timeline.get_wave = lambda path: self.wave_peaks.get(path)
        self.timeline.on_rightclick = self._timeline_context_menu
        self.timeline.on_release = self._flush_seek
        self.timeline.on_move_track = self._timeline_drop_track

    # ================================================================ 状态记忆
    def _restore_state(self):
        s = self.settings
        geo = s.get("window_geometry")
        if geo:
            try:
                self.root.geometry(geo)
            except Exception:
                pass
        last_dir = s.get("last_dir")
        if last_dir and os.path.isdir(last_dir):
            self.dir_var.set(last_dir)
        # 恢复上次项目（存在则打开）
        lp = s.get("last_project")
        if lp and os.path.isfile(lp):
            try:
                self.project = self.store.load(lp)
                log.info("恢复上次项目: %s", lp)
            except Exception as e:
                log.warning("恢复上次项目失败: %s", e)
        # 恢复时间轴状态
        self.timeline.pps = float(s.get("timeline_pps", 12.0))
        self.timeline.playhead = float(s.get("timeline_playhead", 0.0))
        self.timeline.refresh()
        sel = s.get("selected_clip_id")
        if sel:
            self.timeline.select(sel)
        self._refresh_recent_menu()

    def _persist_state(self):
        s = self.settings
        s.set("window_geometry", self.root.geometry())
        s.set("last_dir", self.dir_var.get())
        s.set("last_project", self.store.last_path or
              (self.settings.get("last_project") or ""))
        s.set("timeline_pps", self.timeline.pps)
        s.set("timeline_playhead", self.timeline.playhead)
        s.set("selected_clip_id", self.timeline.selected_id or "")
        s.save()
        log.info("已记忆界面状态")

    def prop_frame_recover(self):
        """显示 / 隐藏右侧属性侧栏。"""
        try:
            if self._prop_visible:
                self.main_paned.forget(self.side)
                self._prop_visible = False
            else:
                self.main_paned.add(self.side, weight=0)
                self._prop_visible = True
        except Exception as e:
            log.debug("切换侧栏失败: %s", e)

    def _side_scroll_wheel(self, evt):
        """鼠标在侧栏上时滚轮滚动侧栏（不影响其它区域）。"""
        try:
            w = self._side_canvas.winfo_containing(evt.x_root, evt.y_root)
            node = w
            while node is not None and node is not self._side_canvas:
                node = getattr(node, "master", None)
            if node is None:
                return
            self._side_canvas.yview_scroll(-1 if evt.delta > 0 else 1, "units")
        except Exception:
            pass

    def _open_last_export_dir(self):
        """打开最近一次导出所在文件夹。"""
        p = getattr(self, "_last_export_path", "")
        d = os.path.dirname(p) if p else getattr(self, "_last_export_dir", "")
        if d and os.path.isdir(d):
            try:
                os.startfile(d)
            except Exception as e:
                messagebox.showerror("错误", f"打不开文件夹：{e}")
        else:
            messagebox.showinfo("提示", "还没有导出过成片。\n"
                                "点「🎬 导出视频…」即可导出到素材文件夹。")

    def _mark_exported(self, path: str):
        """记录最近一次导出，侧栏显示成片位置。"""
        self._last_export_path = path
        self._last_export_dir = os.path.dirname(path)
        try:
            self.last_export_var.set("最近导出：\n" + path)
        except Exception:
            pass

    def _apply_pip_scale(self, frac: float):
        """画中画大小预设：缩到画面的 frac 倍（保持源比例，不越界）。"""
        clip = self.project.find_clip(self.timeline.selected_id or "")
        if clip is None or isinstance(clip, TextClip):
            messagebox.showwarning("提示", "请先选中一个视频或图片片段。")
            return
        if isinstance(clip, VideoClip) and self._is_main_clip(clip):
            messagebox.showinfo("提示",
                                "主轨片段总是满屏；请把视频加到画中画轨再改大小。")
            return
        W, H = self.project.canvas_w, self.project.canvas_h
        self._push_undo()
        if frac >= 1.0:
            clip.x, clip.y, clip.w, clip.h = 0, 0, W, H
        else:
            sw, sh = W, H
            try:
                meta = self.engine._probe_info(clip.src)
                sw = int(meta.get("width", 0) or W) or W
                sh = int(meta.get("height", 0) or H) or H
            except Exception:
                pass
            w = W * frac
            h = w * sh / max(sw, 1)
            x = float(getattr(clip, "x", -1))
            y = float(getattr(clip, "y", -1))
            if x < 0 or y < 0:
                x, y = (W - w) / 2.0, (H - h) / 2.0
            x = min(max(x, 0.0), max(W - w, 0.0))
            y = min(max(y, 0.0), max(H - h, 0.0))
            clip.x, clip.y, clip.w, clip.h = x, y, w, h
        self._fill_props(clip)
        self._after_model_change()
        self._preview_clip(clip)
        self.status_var.set(
            f"画中画大小 {frac:.0%}：{clip.w:.0f}×{clip.h:.0f} 像素"
            f"（位置 {clip.x:.0f},{clip.y:.0f}）")

    # ============ 媒体 ============
    def _browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or ".")
        if d:
            self.dir_var.set(d)
            self._refresh_media()
            self._persist_state()

    def _refresh_media(self):
        d = self.dir_var.get().strip()
        self.media_files = []
        self.media_list.delete(*self.media_list.get_children())
        if not d or not os.path.isdir(d):
            return
        try:
            names = sorted(os.listdir(d))
        except PermissionError as e:
            log.error("扫描目录失败 %s: %s", d, e)
            names = []
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            full = os.path.join(d, name)
            if not os.path.isfile(full):
                continue
            if ext in MEDIA_VIDEO_EXTS:
                tag, kind = "🎞", "video"
            elif ext in MEDIA_IMAGE_EXTS:
                tag, kind = "🖼", "image"
            elif ext in MEDIA_AUDIO_EXTS:
                tag, kind = "🎵", "audio"
            else:
                continue
            self.media_files.append((tag, full))
            self._thumb_kind[full] = kind
            self.media_list.insert("", "end", iid=str(len(self.media_files) - 1),
                                   text="", values=(f"{tag} {name}",))
            self.thumbs.request(full, kind)
        if self.media_files:
            self._thumb_done['n'] = 0
            self._thumb_done['total'] = len(self.media_files)
            self._busy(f"正在生成缩略图（{len(self.media_files)} 个素材）…",
                       False)
            self.thumbs.on_ready = self._on_thumb_ready

    _thumb_done = {"n": 0, "total": 0}

    def _thumb_ready_refresh(self, path: str, im):
        """（后台线程回调）→ 排到 UI 线程处理，防止 Tk 跨线程报错。"""
        self._post_ui(lambda: self._thumb_apply(path, im))

    def _thumb_apply(self, path: str, im):
        """（UI 线程）缩略图上屏 + 节流刷新时间轴。"""
        try:
            from PIL import ImageTk
            if im.size != (96, 54):
                im = im.resize((96, 54), _PILImage.LANCZOS)
            photo = ImageTk.PhotoImage(im)
            self.thumb_photos[path] = photo
            p = path.lower()
            for i, (_tag, full) in enumerate(self.media_files):
                if full.lower() == p:
                    iid = str(i)
                    if self.media_list.exists(iid):
                        self.media_list.item(iid, image=photo)
                    break
            if not getattr(self, "_thumb_refresh_pending", False):
                self._thumb_refresh_pending = True

                def _later():
                    self._thumb_refresh_pending = False
                    try:
                        self.timeline.refresh()
                    except Exception:
                        pass
                self.root.after(120, _later)
        except Exception as e:
            log.warning("缩略图上屏失败: %s", e)

    def _on_thumb_ready(self, path: str, im):
        """计数版：全部就绪后转普通回调；周转 UI 线程上屏。"""
        c = self._thumb_done
        c["n"] += 1
        done = c["n"] >= (c["total"] or c["n"])
        if done:
            self.thumbs.on_ready = self._on_thumb_ready_plain
        self._thumb_ready_refresh(path, im)
        if done:
            self._post_ui(lambda: self._idle(
                f"就绪（{len(self.media_files)} 个素材）"))

    def _on_thumb_ready_plain(self, path: str, im):
        """普通回调：周转 UI 线程上屏。"""
        self._thumb_ready_refresh(path, im)

    def _on_wave_ready(self, path: str, peaks):
        """（后台线程）波形就绪 → 排到 UI 线程刷新。"""
        self._post_ui(lambda: self._wave_apply(path, peaks))

    def _wave_apply(self, path: str, peaks):
        self.wave_peaks[path] = peaks
        try:
            self.timeline.refresh()
        except Exception as e:
            log.warning("波形刷新时间轴失败: %s", e)

    def _media_select_changed(self, _evt=None):
        """选中素材后三个加入按钮亮起；未选中全部禁用。"""
        has = bool(self.media_list.selection())
        for b in (self.btn_media_main, self.btn_media_pip,
                  self.btn_media_audio, self.btn_media_full):
            try:
                b.state(["!disabled" if has else "disabled"])
            except Exception:
                pass

    def _selected_media(self):
        sel = self.media_list.selection()
        if not sel:
            messagebox.showwarning("提示", "请先在素材列表里选择一个文件。")
            return None
        return self.media_files[int(sel[0])][1]

    def _media_kind(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        if ext in MEDIA_IMAGE_EXTS:
            return "image"
        if ext in MEDIA_AUDIO_EXTS:
            return "audio"
        return "video"

    def _media_add_main(self, _evt=None):
        path = self._selected_media()
        if not path:
            return
        if self._media_kind(path) != "video":
            messagebox.showwarning(
                "提示", "只有视频能进主轨（图片→画中画，音频→音频轨）。")
            return
        self._probe_then(path, "读取视频信息",
                         lambda span: self._do_add_path_main(path, span))

    def _probe_then(self, path: str, label: str, on_ready):
        """后台探测时长后回调 on_ready(span)（保持 UI 不冻结）。"""
        self._start_task(
            label, lambda: self.engine.source_length(path),
            lambda span: (
                on_ready(span) if span and span > 0
                else messagebox.showerror(
                    "错误", "无法读取媒体时长，文件可能有损坏。")),
            block=True)

    def _do_add_path_main(self, path: str, src_len: float):
        """主轨添加的收尾（已在 UI 线程，时长由后台提前探测）。"""
        now = _time_now.time()
        last = getattr(self, "_last_add", (None, 0.0))
        if last[0] == path and now - last[1] < 0.35:
            return
        self._last_add = (path, now)
        self._push_undo()
        track = self.project.track("main", create=True)
        clip = VideoClip(src=path, ts=track.end_time(),
                         duration=round(src_len, 3),
                         in_point=0, out_point=round(src_len, 3))
        track.add(clip)
        log.info("主轨添加片段: %s", path)
        self._after_model_change()
        self.timeline.select(clip.id)
        # 反馈 + 滚到新片段可见（必要时自动适配整条时间轴）
        self.status_var.set(f"✅ 已加入主轨（第 {len(track.clips)} 个视频）："
                            f"{os.path.basename(path)}")
        self._reveal_clip(clip)

    def _overlay_track_append(self):
        """找最后一条画中画轨（顺序追加用）；没有则新建。"""
        ovs = self.project.overlay_tracks()
        if ovs:
            return ovs[-1]
        return self.project.new_overlay_track()

    def _media_add_pip(self, _evt=None):
        path = self._selected_media()
        if not path:
            return
        kind = self._media_kind(path)
        if kind == "audio":
            messagebox.showwarning("提示", "音频请加到音频轨。")
            return
        if kind == "image":
            self._do_add_pip(path, 0.0)
            return
        self._probe_then(path, "读取视频信息",
                         lambda span: self._do_add_pip(path, span))

    def _do_add_pip(self, path: str, src_len: float):
        kind = self._media_kind(path)
        self._push_undo()
        W, H = self.project.canvas_w, self.project.canvas_h
        track = self._overlay_track_append()
        ts0 = round(track.end_time(), 3)
        if kind == "image":
            clip = ImageClip(
                src=path, ts=ts0,
                duration=max(self.project.total_duration(), 10),
                x=W * 0.64, y=H * 0.64, w=W * 0.34, h=H * 0.19,
                opacity=1.0)
        else:
            clip = VideoClip(src=path, ts=ts0, duration=round(src_len, 3),
                             in_point=0, out_point=round(src_len, 3),
                             x=W * 0.64, y=H * 0.02, w=W * 0.34, h=H * 0.28)
        track.add(clip)
        log.info("画中画轨追加片段(ts=%.2f): %s", ts0, path)
        self._after_model_change()
        self.timeline.select(clip.id)
        self.status_var.set(
            f"✅ 已插入画中画（选中后可改位置/尺寸）：{os.path.basename(path)}")

    def _media_add_full(self, _evt=None):
        """加到全屏轨：满屏、顺序拼接，相当于第二条主轨。"""
        path = self._selected_media()
        if not path:
            return
        if self._media_kind(path) != "video":
            messagebox.showwarning("提示", "只有视频能加到全屏轨。")
            return
        self._probe_then(path, "读取视频信息",
                         lambda span: self._do_add_full(path, span))

    def _do_add_full(self, path: str, src_len: float):
        self._push_undo()
        W, H = self.project.canvas_w, self.project.canvas_h
        track = self.project.new_overlay_track()
        clip = VideoClip(src=path, ts=0, duration=round(src_len, 3),
                         in_point=0, out_point=round(src_len, 3),
                         x=0, y=0, w=W, h=H)
        track.add(clip)
        log.info("全屏轨添加片段: %s", path)
        self._after_model_change()
        self.timeline.select(clip.id)
        self.status_var.set(f"✅ 已加入全屏轨：{os.path.basename(path)}")

    def _media_add_audio(self, _evt=None):
        path = self._selected_media()
        if not path:
            return
        if self._media_kind(path) != "audio":
            messagebox.showwarning("提示", "只有音频文件（mp3/wav/aac 等）能进音频轨。")
            return
        self._probe_then(path, "读取音频信息",
                         lambda span: self._do_add_audio(path, span))

    def _do_add_audio(self, path: str, src_len: float):
        self._push_undo()
        track = self.project.new_audio_track()
        clip = AudioClip(src=path, ts=0, duration=round(src_len, 3),
                         in_point=0, out_point=round(src_len, 3),
                         volume=1.0)
        track.add(clip)
        log.info("音频轨添加片段: %s", path)
        self._after_model_change()
        self.timeline.select(clip.id)
        self.status_var.set(
            f"✅ 已插入音频轨：{os.path.basename(path)}，可拖边缘裁剪")

    # ============ 拖拽加入时间轴 ============
    def _media_drag_press(self, evt):
        self._drag_xy = (evt.x, evt.y)
        row = self.media_list.identify_row(evt.y)
        if row:
            self.media_list.selection_set(row)
            self._media_drag_path = self.media_files[int(row)][1]
        else:
            self._media_drag_path = None

    # ---------- 拖拽幽灵（缩略图跟随光标）+ 落点提示 ----------
    def _media_drag_motion(self, evt):
        path = getattr(self, "_media_drag_path", None)
        if not path:
            return
        sx, sy = getattr(self, "_drag_xy", (evt.x, evt.y))
        if abs(evt.x - sx) < 12 and abs(evt.y - sy) < 12:
            return   # 还没算开始拖
        self._drag_ghost_show(path, evt.x_root, evt.y_root)
        # 落点提示：指针是否在时间轴上
        node = self.root.winfo_containing(evt.x_root, evt.y_root)
        while node is not None and node is not self.timeline:
            node = node.master if node.master else None
        if node is self.timeline:
            x_px = evt.x_root - self.timeline.winfo_rootx()
            self.timeline.set_drop_hint(self.timeline.time_at_x(x_px))
        else:
            self.timeline.clear_drop_hint()

    def _drag_ghost_show(self, path: str, x_root: int, y_root: int):
        try:
            if self._drag_ghost is None:
                top = tk.Toplevel(self.root)
                top.wm_overrideredirect(True)
                try:
                    top.wm_attributes("-topmost", True)
                except Exception:
                    pass
                frame = tk.Frame(top, bg="#252526",
                                 highlightthickness=1,
                                 highlightbackground="#4a9eff")
                frame.pack()
                img_lbl = tk.Label(frame, bg="#252526")
                img_lbl.pack()
                txt = tk.Label(frame, text=os.path.basename(path),
                               bg="#252526", fg="#e0e0e0",
                               font=("Microsoft YaHei UI", 9))
                txt.pack(padx=4, pady=(0, 3))
                self._drag_ghost = top
                self._drag_ghost_img, self._drag_ghost_txt = img_lbl, txt
            ph = self.thumb_photos.get(path)
            if ph is not None and ph is not self._drag_ghost_photo:
                self._drag_ghost_photo = ph
                self._drag_ghost_img.config(image=ph)
            self._drag_ghost_txt.config(text=os.path.basename(path))
            # 偏移一点，避免幽灵窗口夺走鼠标事件
            self._drag_ghost.geometry(f"+{x_root + 18}+{y_root + 12}")
        except Exception as e:
            log.debug("拖拽幽灵失败: %s", e)

    def _drag_ghost_hide(self):
        try:
            if self._drag_ghost is not None:
                self._drag_ghost.destroy()
        except Exception:
            pass
        self._drag_ghost = None
        self._drag_ghost_photo = None

    def _media_drag_release(self, evt):
        path = getattr(self, "_media_drag_path", None)
        self._media_drag_path = None
        self._drag_ghost_hide()
        try:
            self.timeline.clear_drop_hint()
        except Exception:
            pass
        if not path:
            return
        # 必须是真正的拖拽（≥12px），且落点必须在时间轴内——
        # 否则双击时的手抖会被误判成拖拽，导致"加了两次"
        sx, sy = getattr(self, "_drag_xy", (0, 0))
        if abs(evt.x - sx) < 12 and abs(evt.y - sy) < 12:
            return
        # 检查指针是否落在时间轴上
        widget = self.root.winfo_containing(evt.x_root, evt.y_root)
        node = widget
        while node is not None and node != self.timeline:
            node = node.master if node.master else None
        if node is None:
            # 落点在时间轴之外：不加入（避免误触重复添加）
            self.status_var.set("拖到时间轴区域松手才会加入素材")
            return
        x_px = evt.x_root - self.timeline.winfo_rootx()
        y_px = evt.y_root - self.timeline.winfo_rooty()
        sec = self.timeline.time_at_x(x_px)
        self._drop_media(path, sec, y_px)

    def _drop_media(self, path: str, sec: float, y_px: float):
        """拖拽落点：视频→顺序跟主轨末尾；图片→画中画；音频→音频轨。"""
        kind = self._media_kind(path)
        if kind == "image":
            self._do_drop(path, sec, 0.0)
            return
        self._probe_then(path, "读取媒体信息",
                         lambda span: self._do_drop(path, sec, span))

    def _do_drop(self, path: str, sec: float, span: float):
        kind = self._media_kind(path)
        W, H = self.project.canvas_w, self.project.canvas_h
        self._push_undo()
        if kind == "video":
            track = self.project.track("main", create=True)
            clip = VideoClip(src=path, ts=max(sec, track.end_time()),
                             duration=round(span, 3),
                             in_point=0, out_point=round(span, 3))
        elif kind == "image":
            track = self._overlay_track_append()
            clip = ImageClip(src=path, ts=max(sec, track.end_time()),
                             duration=max(self.project.total_duration(), 10),
                             x=W * 0.64, y=H * 0.64, w=W * 0.34,
                             h=H * 0.19, opacity=1.0)
        else:
            track = self.project.new_audio_track()
            clip = AudioClip(src=path, ts=max(sec, track.end_time()),
                             duration=round(span, 3),
                             in_point=0, out_point=round(span, 3))
        track.add(clip)
        log.info("拖拽加入 %s -> %s @ %.2fs", os.path.basename(path),
                 track.kind, clip.ts)
        self._after_model_change()
        self.timeline.select(clip.id)

    # ============ 素材快捷添加 ============
    def _media_add_auto(self, _evt=None):
        """双击自动入轨：按素材类型路由（视频→主轨，图片→画中画，音频→音频轨）。"""
        path = self._selected_media()
        if not path:
            return
        kind = self._media_kind(path)
        target = {"video": self._media_add_main,
                  "image": self._media_add_pip,
                  "audio": self._media_add_audio}.get(kind)
        if target:
            target()

    def _media_context_menu(self, _evt=None):
        """右键菜单：显式选择加入哪个轨道。"""
        if not self.media_list.selection():
            # 没选中时把右键所在行选上
            row = self.media_list.identify_row(_evt.y)
            if row:
                self.media_list.selection_set(row)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="加到主轨（满屏拼接）",
                         command=self._media_add_main)
        menu.add_command(label="加到画中画（PiP）",
                         command=self._media_add_pip)
        menu.add_command(label="加到音频轨（背景乐/配音）",
                         command=self._media_add_audio)
        try:
            menu.tk_popup(_evt.x_root, _evt.y_root)
        finally:
            menu.grab_release()

    # ============ 文字/字幕 ============
    def _add_text_dialog(self):
        """添加文字/字幕片段：内容/时长/对齐/字号/颜色/淡入淡出。"""
        win = tk.Toplevel(self.root)
        win.title("添加文字/字幕片段")
        win.geometry("420x320")
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text="文字内容:").grid(row=0, column=0, sticky="ne",
                                              padx=8, pady=6)
        content = tk.Text(win, width=34, height=3, font=("Microsoft YaHei UI", 10))
        content.grid(row=0, column=1, sticky="w")
        content.insert("1.0", "请输入文字…")
        ttk.Label(win, text="时长(秒):").grid(row=1, column=0, sticky="e", padx=8)
        dur_var = tk.StringVar(value="4")
        ttk.Entry(win, textvariable=dur_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(win, text="对齐:").grid(row=2, column=0, sticky="e", padx=8)
        align_var = tk.StringVar(value="bottom")
        ttk.Combobox(win, textvariable=align_var, state="readonly", width=8,
                     values=["bottom", "center", "top"]) \
            .grid(row=2, column=1, sticky="w")
        ttk.Label(win, text="字号:").grid(row=3, column=0, sticky="e", padx=8)
        size_var = tk.StringVar(value="48")
        ttk.Entry(win, textvariable=size_var, width=8).grid(row=3, column=1, sticky="w")
        ttk.Label(win, text="颜色:").grid(row=4, column=0, sticky="e", padx=8)
        color_var = tk.StringVar(value="#FFFFFF")
        ttk.Combobox(win, textvariable=color_var, state="readonly", width=8,
                     values=["#FFFFFF 白", "#FFD700 黄", "#FF5555 红",
                             "#000000 黑", "#55DDFF 青"]) \
            .grid(row=4, column=1, sticky="w")
        ttk.Label(win, text="淡入/淡出(秒):").grid(row=5, column=0, sticky="e", padx=8)
        fio = ttk.Frame(win)
        fio.grid(row=5, column=1, sticky="w")
        fi_var = tk.StringVar(value="0")
        fo_var = tk.StringVar(value="0")
        ttk.Entry(fio, textvariable=fi_var, width=6).pack(side="left")
        ttk.Label(fio, text="/").pack(side="left")
        ttk.Entry(fio, textvariable=fo_var, width=6).pack(side="left")

        def on_ok():
            txt = content.get("1.0", "end").strip()
            if not txt:
                messagebox.showerror("错误", "文字内容不能为空。")
                return
            try:
                dur = max(float(dur_var.get()), 0.5)
                fsize = max(float(size_var.get()), 8)
            except ValueError:
                messagebox.showerror("错误", "时长/字号必须是数字。")
                return
            color = color_var.get().strip().split()[0]
            self._push_undo()
            t = self.project.new_text_track()
            clip = TextClip(text=txt, ts=self.timeline.playhead,
                            duration=round(dur, 3),
                            align=align_var.get(), font_size=fsize,
                            color=color,
                            fade_in=max(float(fi_var.get() or 0), 0),
                            fade_out=max(float(fo_var.get() or 0), 0))
            t.add(clip)
            log.info("添加文字片段: %r", txt[:30])
            self._after_model_change()
            self.timeline.select(clip.id)
            win.destroy()

        ttk.Button(win, text="确定添加", command=on_ok) \
            .grid(row=6, column=1, sticky="w", padx=8, pady=14)
        self.root.wait_window(win)

# ================================================================ 撤销/重做
    def _push_undo(self):
        self.undo.push(self.project)
        log.debug("撤销快照入栈（当前 %d 步）", len(self.undo._undo))

    def _undo(self):
        restored = self.undo.undo(self.project)
        if restored is None:
            self.status_var.set("没有可撤销的操作")
            return
        self._restore_project(restored)
        log.info("撤销 -> 恢复 %d 片段", len(restored.all_clips()))

    def _redo(self):
        restored = self.undo.redo(self.project)
        if restored is None:
            self.status_var.set("没有可重做的操作")
            return
        self._restore_project(restored)
        log.info("重做 -> 恢复 %d 片段", len(restored.all_clips()))

    def _restore_project(self, project: Project):
        self.project = project
        self.timeline.project = project
        self.timeline.refresh()
        # 选中片段可能已不存在
        if self.timeline.selected_id and \
                project.find_clip(self.timeline.selected_id) is None:
            self.timeline.selected_id = None
            self._fill_props(None)
        self.store.request_autosave(project, self.base_dir)
        self.status_var.set(
            f"已恢复（片段 {len(project.all_clips())}，总长 {self._fmt(project.total_duration())}）")

    # ================================================================ 时间轴联动
    def _on_clips_changed_light(self):
        """拖动过程中的轻量回调：只报状态，不做 autosave/控件/重绘风暴。"""
        try:
            self.status_var.set(
                f"拖动中… 总时长 {self._fmt(self.project.total_duration())}")
        except Exception:
            pass

    def _commit_timeline_edit(self):
        """拖动松手：一次性提交（自动保存 + 控件状态 + 完整刷新）。"""
        self.store.request_autosave(self.project, self.base_dir)
        self.timeline.refresh()
        self._refresh_controls()
        self.status_var.set(
            f"✅ 已更新｜总时长 {self._fmt(self.project.total_duration())}"
            f"｜片段 {len(self.project.all_clips())}")

    def _after_model_change(self):
        self.store.request_autosave(self.project, self.base_dir)
        self.timeline.refresh()
        self.status_var.set(
            f"项目总时长 {self._fmt(self.project.total_duration())}，"
            f"片段 {len(self.project.all_clips())}，"
            f"画布 {self.project.canvas_w}×{self.project.canvas_h}"
            f"（工具栏「◧ 画布」可改）")
        self._refresh_controls()
        # 预取音频波形（异步，完成后自动刷新时间轴）
        for c in self.project.all_clips():
            if isinstance(c, AudioClip):
                self.waves.request(c.src)

    def _fmt(self, sec: float) -> str:
        m, s = divmod(int(sec), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _reveal_clip(self, clip):
        """拼完后的视图策略：长视频按比例缩放（一眼看全，刻度自适应），
        短视频保持合适缩放并滚到新片段。"""
        try:
            w = self.timeline.winfo_width()
            if w <= 50:
                return
            # 整条时间轴在当前缩放下超过约 3 屏 → 等比缩放回一屏（长视频不铺成超长条）
            if self.timeline.content_width() > w * 3:
                self.timeline.fit()
                self.timeline.see_playhead()
                return
            total = self.project.total_duration()
            if total * 4 <= w:
                self.timeline.fit()
                return
            tw = clip.timeline_duration()
            if tw > 0 and tw * self.timeline.pps < 60:
                self.timeline.pps = max(60 / tw, self.timeline.pps)
                self.timeline.refresh()
            self.timeline.set_playhead(clip.ts, drive_timeline=False)
            self.timeline.see_playhead()
        except Exception:
            pass

    def _on_clip_selected(self, clip):
        self._fill_props(clip)
        self._refresh_controls()
        # 不再自动弹出属性窗（需要时点工具栏「▦ 属性」）

    def _fill_props(self, clip):
        if clip is None:
            for v in self.prop_vars.values():
                v.set("")
            self.transition_var.set("无")
            return
        m = self.prop_vars
        m["in_point"].set(fmt1(clip.in_point))
        m["out_point"].set(fmt1(clip.out_point))
        m["duration"].set(fmt1(clip.duration))
        m["speed"].set(fmt1(clip.speed))
        m["volume"].set(fmt1(getattr(clip, "volume", 1.0)))
        m["fade_in"].set(fmt1(getattr(clip, "fade_in", 0.0)))
        m["fade_out"].set(fmt1(getattr(clip, "fade_out", 0.0)))
        m["x"].set(fmt1(getattr(clip, "x", -1)))
        m["y"].set(fmt1(getattr(clip, "y", -1)))
        m["w"].set(fmt1(getattr(clip, "w", -1)))
        m["h"].set(fmt1(getattr(clip, "h", -1)))
        m["opacity"].set(fmt1(getattr(clip, "opacity", 1.0)))
        # 渐变速度（仅视频片段有）
        m["ramp_start"].set(fmt1(getattr(clip, "ramp_start", 0.0)))
        m["ramp_end"].set(fmt1(getattr(clip, "ramp_end", 0.0)))
        m["ramp_dur"].set(fmt1(getattr(clip, "ramp_dur", 0.0)))
        # 转场（到下一片段）
        tr = getattr(clip, "transition", None)
        if tr and tr.get("name") in TRANSITIONS:
            self.transition_var.set(tr["name"])
            self.transition_dur_var.set(fmt1(float(tr.get("dur", 0.5))))
        else:
            self.transition_var.set("无")
        # 滤镜（视频/图片片段）
        if isinstance(clip, (VideoClip, ImageClip)):
            f = get_filter(clip)
            self.filter_vars["brightness"].set(fmt1(f["brightness"]))
            self.filter_vars["contrast"].set(fmt1(f["contrast"]))
            self.filter_vars["saturation"].set(fmt1(f["saturation"]))
            self.gray_var.set(bool(f["grayscale"]))
        # 文字/字幕片段
        if isinstance(clip, TextClip):
            self.text_vars["content"].set(clip.text)
            self.text_vars["font_size"].set(fmt1(clip.font_size))
            self.text_vars["color"].set(self._color_label(clip.color))
            self.text_vars["align"].set(clip.align)

    @staticmethod
    def _color_label(color: str) -> str:
        names = {"#FFFFFF": "白", "#FFD700": "黄", "#FF5555": "红",
                 "#000000": "黑", "#55DDFF": "青"}
        c = (color or "#FFFFFF").upper()
        return c + (" " + names[c] if c in names else "")

    def _apply_props(self):
        clip = self.project.find_clip(self.timeline.selected_id or "")
        if clip is None:
            messagebox.showwarning("提示", "请先选中一个片段。")
            return
        m = self.prop_vars
        try:
            clip.in_point = float(m["in_point"].get())
            clip.out_point = float(m["out_point"].get())
            clip.duration = float(m["duration"].get())
            clip.speed = float(m["speed"].get())
            clip.volume = float(m["volume"].get())
            if isinstance(clip, (AudioClip, TextClip)):
                clip.fade_in = max(float(m["fade_in"].get()), 0.0)
                clip.fade_out = max(float(m["fade_out"].get()), 0.0)
            for k in ("x", "y", "w", "h"):
                setattr(clip, k, float(m[k].get()))
            clip.opacity = float(m["opacity"].get())
            # 文字片段：内容/字号/颜色/对齐
            if isinstance(clip, TextClip):
                clip.text = self.text_vars["content"].get()
                clip.font_size = max(float(self.text_vars["font_size"].get()), 8)
                color = self.text_vars["color"].get().strip().split()[0]
                clip.color = color
                clip.align = self.text_vars["align"].get()
            # 渐变速度（仅视频片段）
            if isinstance(clip, VideoClip):
                rs = float(m["ramp_start"].get())
                re_ = float(m["ramp_end"].get())
                rd = float(m["ramp_dur"].get())
                if rs > 0 and re_ > 0 and rd > 0:
                    clip.ramp_start, clip.ramp_end, clip.ramp_dur = rs, re_, rd
                    avg = (rs + re_) / 2.0
                    clip.out_point = min(clip.in_point + avg * rd,
                                         clip.out_point)
                    clip.duration = rd
                else:
                    clip.ramp_start = clip.ramp_end = clip.ramp_dur = 0.0
            # 转场（视频/图片片段：作用于到下一片段）
            if isinstance(clip, (VideoClip, ImageClip)):
                tname = self.transition_var.get()
                tdur = float(self.transition_dur_var.get())
                if tname in TRANSITIONS and tdur > 0:
                    clip.transition = {"name": tname, "dur": tdur}
                else:
                    clip.transition = None
            # 滤镜（视频/图片片段）
            if isinstance(clip, (VideoClip, ImageClip)):
                set_filter(clip,
                           brightness=float(self.filter_vars["brightness"].get()),
                           contrast=float(self.filter_vars["contrast"].get()),
                           saturation=float(self.filter_vars["saturation"].get()),
                           grayscale=self.gray_var.get())
        except ValueError as e:
            log.warning("属性输入非法: %s", e)
            messagebox.showerror("错误", "属性必须填数字。")
            return
        if clip.speed <= 0:
            clip.speed = 1.0
        # 常速编辑：时长跟随速度联动（否则看起来"改了没反应"）
        if isinstance(clip, (VideoClip, AudioClip)) and not (
                hasattr(clip, "ramp_start") and clip.ramp_start > 0):
            span = self._src_span(clip)
            if span > 0:
                clip.duration = round(span / clip.speed, 3)
        if (not isinstance(clip, (ImageClip, TextClip)) and
                clip.out_point <= clip.in_point):
            messagebox.showerror("错误", "源终点必须大于源起点。")
            return
        self._push_undo()
        log.info("应用属性: id=%s speed=%s vol=%s", clip.id, clip.speed, clip.volume)
        self._after_model_change()
        self._preview_clip(clip)
        self.status_var.set("✔ 已应用修改（点 ▶ 或 ⟳ 预览看效果）")
        # 预览不打扰：需要看新效果请点 ▶ 或 ⟳ 预览刷新
    def _apply_preset(self, name: str):
        clip = self.project.find_clip(self.timeline.selected_id or "")
        if clip is None:
            messagebox.showwarning("提示", "请先选中一个画中画片段。")
            return
        if isinstance(clip, TextClip):
            messagebox.showwarning("提示", "文字片段请用属性面板调整（对齐/字号/颜色）。")
            return
        if isinstance(clip, VideoClip) and self._is_main_clip(clip) and name != "满屏":
            messagebox.showinfo("提示", "主轨片段总是满屏；请把视频加到画中画轨再改位置。")
            return
        self._push_undo()
        preset = PIP_PRESETS[name]
        W, H = self.project.canvas_w, self.project.canvas_h
        if preset is None:
            clip.x, clip.y, clip.w, clip.h = 0, 0, W, H
        else:
            fx, fy = preset
            clip.x, clip.y = W * fx, H * fy
            clip.w = W * 0.34
            clip.h = clip.w * (H / W) * 0.78
        self._fill_props(clip)
        self._after_model_change()
        self._preview_clip(clip)

    def _is_main_clip(self, clip) -> bool:
        mt = self.project.track("main", create=False)
        return mt is not None and clip.track_id == mt.id

    # ============ 吸附 / 接缝 / 变速（人性化） ============
    def _toggle_snap(self):
        self.timeline.snap_enabled = bool(self.snap_var.get())
        log.info("磁吸 %s", "开" if self.timeline.snap_enabled else "关")

    def _close_all_gaps(self):
        """闭合所有轨道的空隙（波纹）。"""
        moved = 0
        self._push_undo()
        for t in self.project.tracks:
            moved += t.close_gaps()
        if moved:
            log.info("闭合空隙: 移动 %d 个片段", moved)
            self._after_model_change()
            self.status_var.set(f"已闭合 {moved} 处空隙")
        else:
            self.status_var.set("没有空隙需要闭合")

    def _close_gaps(self):
        """闭合选中片段所在轨的空隙。"""
        clip = self.project.find_clip(self.timeline.selected_id or "")
        if clip is None:
            messagebox.showwarning("提示", "请先选中一个片段。")
            return
        track = self._track_of(clip)
        if track is None:
            return
        self._push_undo()
        moved = track.close_gaps()
        log.info("闭合本轨空隙: 移动 %d 个片段", moved)
        self._after_model_change()
        self.status_var.set(f"本轨已闭合 {moved} 处空隙")

    def _ripple_delete(self):
        """波纹删除：删除选中片段并闭合其所在的空隙（后续片段左移）。"""
        clip = self.project.find_clip(self.timeline.selected_id or "")
        if clip is None:
            messagebox.showwarning("提示", "请先选中一个片段。")
            return
        track = self._track_of(clip)
        if track is None:
            return
        self._push_undo()
        track.clips.remove(clip)
        moved = track.close_gaps()
        log.info("波纹删除片段 %s（移动 %d 个后续片段）", clip.name, moved)
        self.timeline.select(None, notify=True)
        self._after_model_change()

    def _apply_speed(self, speed: float):
        clip = self.project.find_clip(self.timeline.selected_id or "")
        if clip is None or isinstance(clip, (ImageClip, TextClip)):
            messagebox.showwarning("提示", "请先选中视频或音频片段。")
            return
        self._push_undo()
        spd = max(speed, 0.1)
        clip.speed = spd
        if hasattr(clip, "ramp_start"):
            clip.ramp_start = clip.ramp_end = clip.ramp_dur = 0.0
        clip.duration = round(self._src_span(clip) / spd, 3)
        self._fill_props(clip)
        self._after_model_change()
        log.info("设置片段速度 %.2fx", spd)

    def _apply_target_duration(self):
        clip = self.project.find_clip(self.timeline.selected_id or "")
        if clip is None or isinstance(clip, (ImageClip, TextClip)):
            messagebox.showwarning("提示", "请先选中视频或音频片段。")
            return
        try:
            target = float(self.target_dur_var.get())
            assert target > 0.1
        except Exception:
            messagebox.showerror("错误", "目标时长必须是正数（秒）。")
            return
        span = self._src_span(clip)
        if span <= 0:
            messagebox.showerror("错误", "无法计算源长度。")
            return
        self._push_undo()
        clip.speed = round(span / target, 4)
        if hasattr(clip, "ramp_start"):
            clip.ramp_start = clip.ramp_end = clip.ramp_dur = 0.0
        clip.duration = round(target, 3)
        self._fill_props(clip)
        self._after_model_change()
        log.info("变速到 %.2fs -> speed=%.3fx", target, clip.speed)

    def _src_span(self, clip) -> float:
        """片段源区间长度（秒）。"""
        if isinstance(clip, VideoClip) and clip.out_point > 0:
            return max(clip.out_point - clip.in_point, 0)
        out = clip.out_point or self.engine.source_length(clip.src)
        return max(out - clip.in_point, 0)

    def _timeline_context_menu(self, clip, x_root, y_root):
        """时间轴右键：常用编辑一把梭（加速/减速/重置/复制/删除/分割）。"""
        menu = tk.Menu(self.root, tearoff=0)
        if clip is not None:
            menu.add_command(label=f"加速 ×1.25（{clip.name[:12]}…）",
                             command=lambda: self._timeline_speed(1.25))
            menu.add_command(label="减速 ×0.8",
                             command=lambda: self._timeline_speed(0.8))
            menu.add_command(label="重置速度 ×1（恢复常速）",
                             command=self._timeline_speed_reset)
            menu.add_separator()
            menu.add_command(label="复制片段", command=self._copy_clip)
            menu.add_command(label="删除片段", command=self._delete_selected)
            menu.add_command(label="在播放头分割", command=self._split_at_playhead)
            menu.add_separator()
        menu.add_command(label="闭合本轨空隙", command=self._close_gaps)
        menu.add_command(label="闭合全部空隙", command=self._close_all_gaps)
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _timeline_speed_reset(self):
        """重置为常速（×1.0）：清渐变，时长=源区间长度。"""
        clip = self.project.find_clip(self.timeline.selected_id or "")
        if clip is None or isinstance(clip, (ImageClip, TextClip)):
            return
        self._push_undo()
        clip.speed = 1.0
        if hasattr(clip, "ramp_start"):
            clip.ramp_start = clip.ramp_end = clip.ramp_dur = 0.0
        span = self._src_span(clip)
        if span > 0:
            clip.duration = round(span, 3)
        self._fill_props(clip)
        self._after_model_change()
        log.info("重置片段速度为常速: %s", clip.id)

    def _timeline_speed(self, factor: float):
        """对选中片段（支持多选）统一变速。"""
        ids = self.timeline.selected_ids()
        self._push_undo()
        done = 0
        for cid in ids:
            clip = self.project.find_clip(cid)
            if clip is None or isinstance(clip, (ImageClip, TextClip)):
                continue
            spd = max(factor, 0.1)
            clip.speed = spd
            if hasattr(clip, "ramp_start"):
                clip.ramp_start = clip.ramp_end = clip.ramp_dur = 0.0
            span = self._src_span(clip)
            if span > 0:
                clip.duration = round(span / spd, 3)
            done += 1
        self._fill_props(self.project.find_clip(self.timeline.selected_id or ""))
        self._after_model_change()
        log.info("批量变速 %d 个片段 x%.3f", done, factor)

    def _load_clip_preview(self, clip, autoplay: bool = True,
                           seek_after: float | None = None):
        """加载片段到预览。重活（探测元数据）在后台线程，UI 不冻结。"""
        if isinstance(clip, TextClip):
            self.player.pause()
            self.player.draw_text_center(
                f"✎ {clip.text}\n（{clip.align} / {clip.font_size:.0f}px / {clip.color}）")
            return
        if isinstance(clip, ImageClip):
            self.player.pause()
            self.player.draw_text_center("🖼 图片片段（渲染时叠加到画面）")
            return
        spd = clip.speed if clip.speed > 0 else 1.0
        src_len = (clip.out_point - clip.in_point) / spd
        if src_len <= 0:
            return
        base = os.path.basename(clip.src)
        self._start_task(
            f"打开预览：{base}",
            lambda: self.engine.source_meta(clip.src),
            lambda meta: self._do_player_load(clip, spd, src_len, meta,
                                              autoplay, seek_after),
            block=True)

    def _do_player_load(self, clip, spd, src_len, meta, autoplay,
                        seek_after):
        """（UI 线程）用后台拿到的元数据装载播放器并定位。"""
        self.player.load(clip.src, clip.in_point, src_len, spd, 960, 540,
                         audio_src=clip.src, audio_in=clip.in_point,
                         audio_len=(clip.out_point - clip.in_point),
                         audio_vol=clip.volume,
                         src_w=int(meta.get("width", 0) or 0),
                         src_h=int(meta.get("height", 0) or 0),
                         fps=float(meta.get("fps", 0) or 0))
        self._preview_clip_id = clip.id
        self._preview_ts = clip.ts
        if seek_after is not None:
            self.player.seek(seek_after)
        if autoplay:
            self.player.play()
        self._refresh_controls()
        self._idle("预览就绪")

    def _advance_timeline(self):
        """时间轴模式下播完一段自动接下一段（主轨顺序）。"""
        cur = self.project.find_clip(self._preview_clip_id or "")
        mt = self.project.track("main", create=False)
        if cur is None or mt is None:
            self._timeline_play = False
            return
        sorted_clips = sorted(mt.clips, key=lambda c: c.ts)
        idx = next((i for i, c in enumerate(sorted_clips)
                    if c.id == cur.id), -1)
        if idx >= 0 and idx + 1 < len(sorted_clips):
            nxt = sorted_clips[idx + 1]
            if isinstance(nxt, VideoClip):
                self._load_clip_preview(nxt)
                return
        # 到底了：停在结尾
        self._timeline_play = False
        self.timeline.set_playhead(self.project.total_duration(),
                                   drive_timeline=False)

    def _timeline_thumb(self, path: str):
        """时间轴片段迷你缩略图：只取缓存，未就绪则后台生成（不阻塞）。"""
        ph = self.thumb_photos.get(path)
        if ph is not None:
            return ph
        # 后台排队生成；完成后 _on_thumb_ready 会刷新时间轴
        self.thumbs.request(path, self._thumb_kind.get(path, "video"))
        return None

    def _preview_refresh(self):
        """⟳：手动刷新预览（默认编辑不打扰预览）。"""
        clip = self.project.find_clip(self.timeline.selected_id or "")
        if clip is None:
            self._play_timeline()
            return
        self._preview_clip(clip)

    def _timeline_drop_track(self, clip, row_kind: str):
        """跨轨拖拽落点：按目标轨类型移动片段。"""
        if isinstance(clip, VideoClip) and row_kind in ("main", "overlay",
                                                        "subtitle"):
            self._convert_track(clip, to_main=(row_kind == "main"))
            return
        log.info("跨轨拖拽 -> %s", row_kind)

    def _convert_track(self, clip, to_main: bool):
        """跨轨转换：主轨↔画中画。"""
        if not isinstance(clip, VideoClip):
            messagebox.showwarning("提示", "只有视频能跨轨转换。")
            return
        src_track = self._track_of(clip)
        if src_track is None:
            return
        self._push_undo()
        src_track.clips.remove(clip)
        if to_main:
            mt = self.project.track("main", create=True)
            clip.x = clip.y = clip.w = clip.h = -1
            clip.ts = max(clip.ts, mt.end_time())
            mt.add(clip)
        else:
            W, H = self.project.canvas_w, self.project.canvas_h
            clip.x, clip.y = W * 0.64, H * 0.02
            clip.w, clip.h = W * 0.34, H * 0.28
            ov = self._overlay_track_append()
            clip.ts = max(clip.ts, ov.end_time())
            ov.add(clip)
        self._after_model_change()
        self.timeline.select(clip.id)
        log.info("跨轨转换 -> %s", "主轨" if to_main else "画中画")

    def _cycle_selection(self, delta: int):
        """↑/↓ 在主轨片段间切换选中。"""
        mt = self.project.track("main", create=False)
        if not mt or not mt.clips:
            return
        ids = [c.id for c in sorted(mt.clips, key=lambda c: c.ts)]
        cur = self.timeline.selected_id
        idx = ids.index(cur) if cur in ids else -1
        nxt = ids[(idx + (1 if delta > 0 else -1)) % len(ids)]
        self.timeline.select(nxt)

    # ============ 复制 / 粘贴 ============
    def _copy_clip(self):
        clip = self.project.find_clip(self.timeline.selected_id or "")
        if clip is None:
            messagebox.showwarning("提示", "请先选中一个片段。")
            return
        import copy as _copy
        self._clipboard = _copy.deepcopy(clip.to_dict())
        self.status_var.set(f"已复制: {clip.name}")
        log.info("复制片段: %s", clip.name)

    def _paste_clip(self):
        """把剪贴板片段粘贴到播放头（新 id；同轨找空位，避免重叠）。"""
        if not getattr(self, "_clipboard", None):
            messagebox.showwarning("提示", "剪贴板为空，请先复制一个片段。")
            return
        from .model import clip_from_dict, new_id
        d = dict(self._clipboard)
        d["id"] = new_id()
        d["ts"] = self.timeline.playhead
        new_clip = clip_from_dict(d)
        if isinstance(new_clip, VideoClip) and d.get("x", -1) <= 0:
            track = self.project.track("main", create=True)
        elif isinstance(new_clip, (VideoClip, ImageClip)):
            track = self.project.new_overlay_track()
            if isinstance(new_clip, VideoClip) and new_clip.w <= 0:
                new_clip.x, new_clip.y = self.project.canvas_w * 0.64, \
                    self.project.canvas_h * 0.02
                new_clip.w, new_clip.h = self.project.canvas_w * 0.34, \
                    self.project.canvas_h * 0.28
        elif isinstance(new_clip, TextClip):
            track = self.project.new_text_track()
        else:
            track = self.project.new_audio_track()
        start = self.timeline.playhead
        span = new_clip.timeline_duration()
        while True:
            clash = [c for c in track.clips
                     if not (start + span <= c.ts + 1e-3 or
                             start >= c.ts + c.timeline_duration() - 1e-3)]
            if not clash:
                break
            start = max(c.ts + c.timeline_duration() for c in clash)
        new_clip.ts = round(start, 3)
        self._push_undo()
        track.add(new_clip)
        log.info("粘贴片段 %s @ %.2fs（轨 %s）", new_clip.name, new_clip.ts,
                 track.kind)
        self._after_model_change()
        self.timeline.select(new_clip.id)

    # ============ 控件可用性（UX：没素材时按钮不可点） ============
    def _refresh_controls(self):
        """根据当前状态启用/禁用控件，避免"空手能按按钮"的反人类体验。"""
        has_src = getattr(self.player, "_path", None) is not None
        for w in (self.btn_play, self.btn_rewind, self.seek_bar,
                  self.btn_audition):
            try:
                w.state(["!disabled" if has_src else "disabled"])
            except Exception:
                pass
        has_sel = self.timeline.selected_id is not None
        for w in ([self.btn_apply, self.btn_delete, self.btn_ripple,
                   self.btn_split, self.btn_close_gaps,
                   self.btn_target_dur] + list(self.spd_btns) +
                  list(self.preset_btns)):
            try:
                w.state(["!disabled" if has_sel else "disabled"])
            except Exception:
                pass
        can_render = (not self.rendering and
                      self.project.total_duration() > 0)
        try:
            self.tbtn_render.state(["!disabled" if can_render else "disabled"])
        except Exception:
            pass

    # ============ 忙碌指示（让用户知道软件在干嘛） ============
    # ============ 任务系统（后台线程 + 忙碌遮罩） ============
    def _post_ui(self, fn):
        """后台线程安全地把回调排到 UI 线程（主循环 drain）。"""
        try:
            self.ui_q.put(fn)
        except Exception:
            pass

    def _drain_ui_q(self):
        while True:
            try:
                fn = self.ui_q.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                log.warning("UI 任务执行失败: %s", e)

    def _start_task(self, name, fn, on_done=None, on_error=None,
                    block: bool = True):
        """把重活丢后台线程；期间显示中央遮罩并吞掉点击。
        background_tasks=False 时同步执行（供自动化测试）。"""
        if self._task_busy:
            try:
                self.status_var.set(f"⏳ 正在处理「{self._task_name}」，请稍候…")
            except Exception:
                pass
            return False

        if not self.background_tasks:
            try:
                result = fn()
            except Exception as e:
                log.exception("任务失败: %s", name)
                if on_error:
                    on_error(e)
                elif block:
                    messagebox.showerror("出错", f"{name} 失败：{e}")
                return True
            if on_done:
                on_done(result)
            return True

        self._task_busy = True
        self._task_name = name
        if block:
            self._show_busy_overlay(name)
        else:
            self._busy(name + "…", indeterminate=True)

        def worker():
            result, err = None, None
            try:
                result = fn()
            except Exception as e:  # noqa: BLE001
                err = e
            # 线程安全：排到 UI 队列，由主循环 drain 执行（不能跨线程调 Tk）
            self._post_ui(lambda: self._finish_task(name, result, err,
                                                    on_done, on_error, block))

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _finish_task(self, name, result, err, on_done, on_error, block):
        self._task_busy = False
        if block:
            self._hide_busy_overlay()
        else:
            self._idle("就绪")
        if err is not None:
            log.exception("任务失败: %s", name)
            if on_error:
                on_error(err)
            else:
                messagebox.showerror("出错", f"{name} 失败：{err}")
            return
        if on_done:
            try:
                on_done(result)
            except Exception as e:  # noqa: BLE001
                log.exception("任务收尾失败: %s", name)
                messagebox.showerror("出错", f"{name} 处理结果失败：{e}")

    def _wait_idle(self, timeout: float = 30.0):
        """（测试用）泵事件循环直到没有后台任务。"""
        t0 = _time_now.time()
        while self._task_busy and _time_now.time() - t0 < timeout:
            try:
                self.root.update()
            except Exception:
                break
            _time_now.sleep(0.01)
        return not self._task_busy

    # ---------- 中央忙碌遮罩（吞点击，避免越点越卡） ----------
    def _show_busy_overlay(self, name: str):
        try:
            if self._busy_mask is not None:
                self._busy_mask.lift()
                return
            mask = tk.Frame(self.root, bg="#0d0d0d")
            mask.place(relx=0, rely=0, relwidth=1, relheight=1)
            card = tk.Frame(mask, bg="#252526", highlightthickness=1,
                            highlightbackground="#4a9eff")
            card.place(relx=0.5, rely=0.5, anchor="center")
            lbl = tk.Label(card, text="", bg="#252526", fg="#e0e0e0",
                           font=("Microsoft YaHei UI", 12), padx=34, pady=22,
                           justify="center")
            lbl.pack()
            for w in (mask, card, lbl):
                w.bind("<Button-1>", lambda e: "break")
            self._busy_mask, self._busy_lbl = mask, lbl
            self._busy_t0 = _time_now.time()
            self._tick_busy_overlay()
        except Exception as e:
            log.warning("忙碌遮罩创建失败: %s", e)

    def _tick_busy_overlay(self):
        if self._busy_mask is None:
            return
        try:
            el = int(_time_now.time() - getattr(self, "_busy_t0",
                                                _time_now.time()))
            self._busy_lbl.config(
                text="⏳ 正在" + self._task_name + "\n已等待 "
                     + str(el) + "s\n（处理中，请稍候…）")
        except Exception:
            pass
        self.root.after(300, self._tick_busy_overlay)

    def _hide_busy_overlay(self):
        try:
            if self._busy_mask is not None:
                self._busy_mask.destroy()
        except Exception:
            pass
        self._busy_mask, self._busy_lbl = None, None

    def _busy(self, text: str, indeterminate: bool = True):
        """状态栏+进度条转圈提示；同时标题加 ⏳（一眼看出在忙）。"""
        self._busy_t0 = getattr(self, "_busy_t0", _time_now.time())
        if not getattr(self, "_title_base", None):
            self._title_base = self.root.title()
        try:
            if "⏳" not in self.root.title():
                self.root.title("⏳ " + self._title_base)
        except Exception:
            pass
        try:
            if indeterminate:
                self.render_progress.configure(mode="indeterminate")
                self.render_progress.start(80)
            else:
                self.render_progress.stop()
                self.render_progress.configure(mode="determinate")
        except Exception:
            pass
        self.root.after(400, self._busy_refresh)
        self.root.update_idletasks()

    def _busy_refresh(self):
        """每 400ms 刷新忙碌秒数（让用户知道任务在推进）。"""
        if self.status_var.get().startswith("⏳"):
            t0 = getattr(self, "_busy_t0", _time_now.time())
            self.status_var.set(f"⏳ 任务进行中… 已等待 {int(_time_now.time() - t0)}s")

    def _idle(self, msg: str = "就绪"):
        try:
            if getattr(self, "_title_base", None):
                self.root.title(self._title_base)
        except Exception:
            pass
        self.status_var.set(msg)
        try:
            self.render_progress.stop()
            self.render_progress.configure(mode="determinate", value=0)
        except Exception:
            pass

    # ============ 图层面板 ============
    def _layers_dialog(self):
        """图层：主轨/画中画/音频/字幕 的可见、堆叠顺序（上移=更上层）。"""
        win = tk.Toplevel(self.root)
        win.title("图层（顺序=渲染堆叠，列表下方=更上层）")
        win.geometry("380x300")
        win.transient(self.root)
        self._show_modal(win, 380, 300)
        tree = ttk.Treeview(win, columns=("kind", "clips"), show="headings",
                            height=10)
        tree.heading("kind", text="图层")
        tree.heading("clips", text="片段数")
        tree.column("kind", width=200)
        tree.column("clips", width=70, anchor="center")
        tree.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        def refresh():
            tree.delete(*tree.get_children())
            labels = {"main": "主轨", "overlay": "画中画", "audio": "音频轨",
                      "subtitle": "字幕"}
            for i, t in enumerate(self.project.tracks):
                eye = "👁" if t.visible else "🚫"
                lbl = labels.get(t.kind, t.kind)
                tree.insert("", "end", iid=str(i),
                            values=(f"{eye} {lbl}", len(t.clips)))

        def move(delta):
            sel = tree.selection()
            if not sel:
                return
            t = self.project.tracks[int(sel[0])]
            if t.move(delta, self.project):
                self._push_undo()
                self._after_model_change()
                refresh()

        def toggle_vis():
            sel = tree.selection()
            if not sel:
                return
            t = self.project.tracks[int(sel[0])]
            self._push_undo()
            t.visible = not t.visible
            self._after_model_change()
            refresh()

        def del_track():
            sel = tree.selection()
            if not sel:
                return
            t = self.project.tracks[int(sel[0])]
            if t.clips and not messagebox.askyesno(
                    "删除图层", f"图层 {t.kind} 里有 {len(t.clips)} 个片段，确定删除？"):
                return
            self._push_undo()
            self.project.tracks.remove(t)
            self._after_model_change()
            refresh()

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btns, text="⬆ 上移(更上层)", command=lambda: move(-1)) \
            .pack(side="left", padx=2)
        ttk.Button(btns, text="⬇ 下移", command=lambda: move(1)) \
            .pack(side="left", padx=2)
        ttk.Button(btns, text="👁 显示/隐藏", command=toggle_vis) \
            .pack(side="left", padx=2)
        ttk.Button(btns, text="🗑 删除图层", command=del_track) \
            .pack(side="left", padx=2)
        refresh()

    # ============ 提示气泡 ============
    def _tooltip(self, widget, text: str):
        tip = [None]

        def show(_e):
            if tip[0] is not None:
                return
            x = widget.winfo_rootx() + 12
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            t = tk.Toplevel(widget)
            t.wm_overrideredirect(True)
            t.wm_geometry(f"+{x}+{y}")
            tk.Label(t, text=text, background="#333333", foreground="#eee",
                     font=("Microsoft YaHei UI", 9), padx=6, pady=2).pack()
            tip[0] = t

        def hide(_e):
            if tip[0] is not None:
                try:
                    tip[0].destroy()
                except Exception:
                    pass
                tip[0] = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    # ============ 素材自动刷新 ============
    def _auto_refresh_media(self):
        """每 2 秒检查文件夹内容是否变化，变化则自动刷新（人工可随时点⟳）。"""
        try:
            d = self.dir_var.get().strip()
            if d and os.path.isdir(d) and not self.rendering:
                current = tuple(sorted(os.listdir(d)))
                if current != getattr(self, "_media_sig", None):
                    self._media_sig = current
                    self._refresh_media()
        except Exception as e:
            log.debug("自动刷新媒体失败: %s", e)
        self.root.after(2000, self._auto_refresh_media)

    def _delete_selected(self):
        """删除选中片段（支持多选）。"""
        ids = self.timeline.selected_ids()
        if not ids:
            return
        self._push_undo()
        removed = 0
        for cid in ids:
            if self.project.remove_clip(cid):
                removed += 1
        self._last_add = (None, 0.0)   # 清去重记录，允许删除后立即重加
        log.info("删除片段（批量 %d）", removed)
        self.timeline.select(None, notify=True)
        self._after_model_change()

    def _split_at_playhead(self):
        cid = self.timeline.selected_id
        clip = self.project.find_clip(cid or "")
        if clip is None or isinstance(clip, ImageClip) or isinstance(clip, TextClip):
            messagebox.showwarning("提示", "只能分割视频或音频片段。")
            return
        pos = self.timeline.playhead
        if not (clip.ts < pos < clip.ts + clip.timeline_duration()):
            messagebox.showwarning("提示", "播放头不在该片段内部。")
            return
        spd = clip.speed if clip.speed > 0 else 1.0
        cut_src = clip.in_point + (pos - clip.ts) * spd
        track = self._track_of(clip)
        if track is None:
            return
        dur1 = (cut_src - clip.in_point) / spd
        cls = type(clip)
        a = cls(src=clip.src, ts=clip.ts, duration=round(dur1, 3),
                in_point=clip.in_point, out_point=cut_src,
                speed=clip.speed, volume=clip.volume,
                effects=list(clip.effects))
        b = cls(src=clip.src, ts=clip.ts + dur1,
                duration=round(clip.duration - dur1, 3),
                in_point=cut_src, out_point=clip.out_point,
                speed=clip.speed, volume=clip.volume,
                effects=list(clip.effects))
        for d in (a, b):
            for attr in ("x", "y", "w", "h", "opacity", "fade_in", "fade_out",
                         "ramp_start", "ramp_end", "ramp_dur"):
                if hasattr(clip, attr):
                    setattr(d, attr, getattr(clip, attr))
        # 转场属于"到下一段"：保留在 b 上（a 的下一段是 b）
        if hasattr(clip, "transition"):
            a.transition = None
            b.transition = dict(clip.transition) if clip.transition else None
        self._push_undo()
        track.clips.remove(clip)
        track.add(a)
        track.add(b)
        log.info("分割片段 %s @ %.2fs", clip.id, pos)
        self._after_model_change()

    def _track_of(self, clip):
        for t in self.project.tracks:
            if t.id == clip.track_id:
                return t
        return None

    # ================================================================ 预览（含音频）
    def _preview_clip(self, clip):
        """双击片段 = 只预览该片段（退出时间轴连续模式）。"""
        if clip is None:
            return
        self._timeline_play = False
        try:
            if isinstance(clip, AudioClip):
                self._load_audio_preview(clip)
                return
            self._load_clip_preview(clip)
        except Exception as e:
            log.exception("预览加载失败: %s", e)
            messagebox.showerror("预览失败", str(e))

    def _load_audio_preview(self, clip):
        spd = clip.speed if clip.speed > 0 else 1.0
        src_len = (clip.out_point - clip.in_point) / spd
        if src_len <= 0:
            return
        self.player.load(clip.src, clip.in_point, src_len, spd, 960, 540,
                         audio_src=clip.src, audio_in=clip.in_point,
                         audio_len=(clip.out_point - clip.in_point),
                         audio_vol=clip.volume)
        self.player.draw_text_center("🎵 音频片段（正在播放声音）")
        self._preview_clip_id = clip.id
        self._preview_ts = clip.ts
        self.player.play()
        self._refresh_controls()

    def _toggle_play(self):
        """▶播放：永远=整条时间轴连续播放（时长=项目总时长）。"""
        if self.player._playing and self._timeline_play:
            self.player.pause()
            return
        if not self._timeline_play and getattr(self.player, "_path", None):
            self._play_timeline()   # 单段预览残留 → 切回整条时间轴
            return
        self._play_timeline()

    def _play_timeline(self):
        """按时间轴顺序连续播放：从播放头所在片段开始，播完自动接下一段。"""
        proj_total = self.project.total_duration()
        if proj_total <= 0:
            messagebox.showinfo("提示", "时间轴是空的，请先添加素材。")
            return
        clip = None
        # 优先：播放头所在片段；否则第一个主轨片段
        for c in sorted(self.project.all_clips(), key=lambda cc: cc.ts):
            if (not isinstance(c, (ImageClip, TextClip)) and
                    c.ts <= self.timeline.playhead < c.ts + c.timeline_duration()):
                clip = c
                break
        if clip is None:
            mt = self.project.track("main", create=False)
            if mt and mt.clips:
                clip = min(mt.clips, key=lambda c: c.ts)
        if clip is None:
            messagebox.showinfo("提示", "还没有可播放的视频片段。")
            return
        self._timeline_play = True
        self._load_clip_preview(clip)
        self._refresh_controls()

    def _player_tick(self, pos):
        if self._timeline_play:
            total = self.project.total_duration()
            self.time_var.set(f"{self._fmt(self._preview_ts + pos)} / "
                              f"{self._fmt(total)}")
            self.seek_var.set(100.0 * (self._preview_ts + pos) /
                              max(total, 1e-6))
        else:
            self.time_var.set(f"{self._fmt(pos)} / {self._fmt(self.player.total())}")
            self.seek_var.set(100.0 * pos / max(self.player.total(), 1e-6))
        # 播放头=预览片段时间轴起点+片段内时间（绝对时间，防止跳回 0）
        self.timeline.set_playhead(self._preview_ts + pos,
                                   drive_timeline=False)

    def _player_state(self, state, msg):
        self.btn_play.config(text="▶ 播放" if state != "playing" else "⏸ 暂停")
        if state in ("playing", "paused") and self.status_var.get().startswith("⏳"):
            self._idle("预览就绪")
        if state == "ended" and self._timeline_play:
            self._advance_timeline()

    def _preview_tick(self):
        self._drain_ui_q()
        self.player.tick()
        self._sync_overlays()
        self.root.after(33, self._preview_tick)

    def _sync_overlays(self):
        """把当前时间轴上活跃的画中画片段同步到预览叠加层（实时合成）。"""
        try:
            t_abs = self._preview_ts + self.player._pos
            specs = []
            for t in self.project.overlay_tracks():
                if not t.visible:
                    continue
                for c in t.clips:
                    if c.ts <= t_abs < c.ts + c.timeline_duration():
                        spd = c.speed if c.speed > 0 else 1.0
                        local = (t_abs - c.ts) * spd
                        remain = max(c.timeline_duration() - local / spd, 0.05)
                        meta = self.engine._probe_info(c.src)
                        specs.append({
                            "id": c.id,
                            "src": c.src,
                            "in_pt": c.in_point + local,
                            "len": remain,
                            "speed": spd,
                            "src_w": meta.get("width", 0),
                            "src_h": meta.get("height", 0),
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
            if specs and not self.status_var.get().startswith("⏳"):
                self.status_var.set(f"画中画活跃: {len(specs)} 层")
            if not self.player._playing and self.player.has_overlays():
                self.player.reframe()
        except Exception as e:
            log.debug("叠加层同步失败: %s", e)

    def _seek_bar_drag(self, val):
        if self.player.total() > 0:
            self.player.seek(float(val) / 100.0 * self.player.total())

    def _on_timeline_seek(self, sec):
        """时间轴播放头拖动 → 节流定位（0.15s 一跳，松手必跳准）。"""
        self.tl_time_var.set(self._fmt(sec))
        now = _time_now.time()
        last = getattr(self, "_last_seek", 0.0)
        if now - last < 0.15:
            self._pending_seek = sec
            return
        self._last_seek = now
        self._pending_seek = None
        self._do_seek(sec)

    def _flush_seek(self):
        pending = getattr(self, "_pending_seek", None)
        if pending is not None:
            self._pending_seek = None
            self._do_seek(pending)

    def _do_seek(self, sec):
        was_tl = self._timeline_play
        was_playing = self.player._playing
        clip = None
        for c in self.project.all_clips():
            if (not isinstance(c, ImageClip) and
                    c.ts <= sec < c.ts + c.timeline_duration()):
                clip = c
                break
        if clip is None:
            return
        spd = clip.speed if clip.speed > 0 else 1.0
        local = (sec - clip.ts) * spd
        if clip.id != self._preview_clip_id:
            self._timeline_play = False
            # 换片段：加载完成后再定位（异步任务，避免 UI 冻结）
            self._load_clip_preview(clip, autoplay=was_playing,
                                    seek_after=local)
            self._timeline_play = was_tl
            return
        self.player.seek(local)
        self._timeline_play = was_tl
        if was_playing:
            self.player.play()

    def _audition(self):
        """试听音频 = 在应用内从播放头播放整条时间轴（带声音）。"""
        clip = self.project.find_clip(self.timeline.selected_id or "")
        if clip is None:
            self._play_timeline()
            return
        self.timeline.set_playhead(clip.ts, drive_timeline=False)
        self._play_timeline()

    # ================================================================ 项目文件
    def _new_project(self):
        if messagebox.askyesno("新建", "新建项目会清空当前时间轴，确定？"):
            self.undo.clear()
            self.project = Project()
            self.timeline.project = self.project
            self._after_model_change()
            log.info("新建项目")

    def _open_project(self):
        p = filedialog.askopenfilename(
            filetypes=[("剪辑项目", "*.vcp"), ("所有文件", "*.*")])
        if not p:
            return
        try:
            self.project = self.store.load(p)
        except Exception as e:
            log.exception("打开项目失败 %s: %s", p, e)
            messagebox.showerror("打开失败", str(e))
            return
        self.timeline.project = self.project
        self.settings.add_recent_project(p)
        self._refresh_recent_menu()
        self._after_model_change()
        log.info("打开项目: %s", p)

    def _save_project(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".vcp",
            filetypes=[("剪辑项目", "*.vcp")],
            initialfile=f"{self.project.name or 'project'}.vcp")
        if not p:
            return
        try:
            self.store.save(self.project, p)
            self.settings.add_recent_project(p)
            self._refresh_recent_menu()
            self.status_var.set(f"已保存: {p}")
            log.info("保存项目: %s", p)
        except Exception as e:
            log.exception("保存项目失败: %s", e)
            messagebox.showerror("保存失败", str(e))

    def _refresh_recent_menu(self):
        self.recent_menu.delete(0, tk.END)
        for p in self.settings.recent_projects():
            self.recent_menu.add_command(
                label=p, command=lambda pp=p: self._open_recent(pp))

    def _open_recent(self, p: str):
        if not os.path.isfile(p):
            messagebox.showinfo("提示", f"文件不存在:\n{p}")
            return
        try:
            self.project = self.store.load(p)
        except Exception as e:
            log.exception("打开最近项目失败: %s", e)
            messagebox.showerror("打开失败", str(e))
            return
        self.timeline.project = self.project
        self._after_model_change()
        log.info("打开最近项目: %s", p)

    def _on_close(self):
        try:
            self._persist_state()
        except Exception as e:
            log.warning("状态记忆失败: %s", e)
        try:
            self.player.cleanup()
        except Exception:
            pass
        self.store.request_autosave(self.project, self.base_dir)
        log.info("应用退出")
        self.root.destroy()

    # ================================================================ 项目设置
    def _project_settings(self):
        win = tk.Toplevel(self.root)
        win.title("项目设置（目标分辨率/帧率）")
        win.geometry("360x260")
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text="画布分辨率（导出目标）:").pack(anchor="w", padx=12, pady=(10, 2))
        var = tk.StringVar()
        combo = ttk.Combobox(win, textvariable=var, state="readonly", width=28)
        combo["values"] = [f"{n} ({w}x{h})" for n, w, h in CANVAS_PRESETS] + \
                          [f"自定义 {self.project.canvas_w}x{self.project.canvas_h}"]
        combo.set(f"{self.project.canvas_w}x{self.project.canvas_h}")
        combo.pack(anchor="w", padx=12)
        ttk.Label(win, text="或自定义宽×高:").pack(anchor="w", padx=12, pady=(8, 2))
        wh = ttk.Frame(win)
        wh.pack(anchor="w", padx=12)
        self.cw_var = tk.StringVar(value=str(self.project.canvas_w))
        self.ch_var = tk.StringVar(value=str(self.project.canvas_h))
        ttk.Entry(wh, textvariable=self.cw_var, width=8).pack(side="left")
        ttk.Label(wh, text=" × ").pack(side="left")
        ttk.Entry(wh, textvariable=self.ch_var, width=8).pack(side="left")
        ttk.Label(win, text="帧率（fps）:").pack(anchor="w", padx=12, pady=(8, 2))
        self.fps_var = tk.StringVar(value=f"{self.project.fps:g}")
        ttk.Entry(win, textvariable=self.fps_var, width=8).pack(anchor="w", padx=12)

        def on_ok():
            try:
                w, h = int(self.cw_var.get()), int(self.ch_var.get())
                fps = float(self.fps_var.get())
                assert w > 0 and h > 0 and 1 <= fps <= 120
            except Exception:
                messagebox.showerror("错误", "宽/高/帧率必须是正数（fps 1~120）。")
                return
            self._push_undo()
            self.project.canvas_w, self.project.canvas_h = w, h
            self.project.fps = fps
            self._after_model_change()
            log.info("项目设置变更: %dx%d @%.1ffps", w, h, fps)
            win.destroy()

        ttk.Button(win, text="应用", command=on_ok).pack(anchor="w", padx=12, pady=14)

    # ================================================================ 日志
    def _open_log_file(self):
        path = _logmod.log_path()
        if path and os.path.isfile(path):
            os.startfile(os.path.dirname(path))  # type: ignore[attr-defined]
        else:
            messagebox.showinfo("日志", "还没有日志文件。")

    def _log_panel(self):
        win = tk.Toplevel(self.root)
        win.title("日志面板（最近 200 条）")
        win.geometry("760x420")
        txt = tk.Text(win, font=("Consolas", 9), wrap="none")
        txt.pack(fill="both", expand=True, padx=6, pady=6)
        btn = ttk.Button(win, text="刷新", command=lambda: _fill())
        btn.pack(pady=(0, 6))

        def _fill():
            txt.delete("1.0", tk.END)
            for line in _logmod.tail_lines(200):
                txt.insert(tk.END, line + "\n")
        _fill()

    # ================================================================ 渲染
    def _render_project(self):
        if self.rendering:
            return
        if self.project.total_duration() <= 0:
            messagebox.showwarning("提示", "时间轴为空。")
            return
        if not self.ffmpeg or not os.path.isfile(self.ffmpeg):
            messagebox.showerror("错误",
                                 "找不到 ffmpeg，请把 ffmpeg.exe 放到程序同目录。")
            return
        out = self._export_dialog()
        if not out:
            return
        self.rendering = True
        self.render_progress.configure(value=0)
        self.status_var.set("渲染中…")
        self._refresh_controls()
        log.info("开始渲染 -> %(path)s (%(container)s crf=%(crf)d) keep=%(keep)s",
                 out)
        t = threading.Thread(target=self._render_worker, args=(out,), daemon=True)
        t.start()

    def _quick_produce_dialog(self):
        """快速成片：多选素材→自动拼接（带转场）→选分辨率→导出。三步成片。"""
        d = self.dir_var.get().strip()
        videos = []
        if d and os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                if os.path.splitext(name)[1].lower() in MEDIA_VIDEO_EXTS:
                    videos.append(os.path.join(d, name))
        if not videos:
            messagebox.showwarning("提示", "先选一个包含视频的素材文件夹。")
            return
        win = tk.Toplevel(self.root)
        win.title("⚡ 快速成片")
        win.transient(self.root)
        win.grab_set()
        self._show_modal(win, 520, 420)
        ttk.Label(win, text="1. 选择要拼接的视频（可多选，按列表顺序成片）:")\
            .pack(anchor="w", padx=10, pady=(10, 2))
        lb = tk.Listbox(win, selectmode="extended", height=8,
                        font=("Microsoft YaHei UI", 9))
        for v in videos:
            lb.insert("end", os.path.basename(v))
        for i in range(len(videos)):
            lb.selection_set(i)
        lb.pack(fill="x", padx=10)
        opt = ttk.Frame(win)
        opt.pack(fill="x", padx=10, pady=6)
        ttk.Label(opt, text="转场:").pack(side="left")
        trans_var = tk.StringVar(value="fade 0.5s")
        ttk.Combobox(opt, textvariable=trans_var, state="readonly", width=10,
                     values=["无", "fade 0.5s", "fade 1s", "dissolve 0.5s"]) \
            .pack(side="left", padx=(4, 14))
        ttk.Label(opt, text="分辨率:").pack(side="left")
        res_var = tk.StringVar(value="1920×1080 (横屏)")
        ttk.Combobox(opt, textvariable=res_var, state="readonly", width=18,
                     values=[f"{n}" for n, _w, _h in CANVAS_PRESETS]) \
            .pack(side="left", padx=(4, 0))
        ttk.Label(win, text="2. 输出:").pack(anchor="w", padx=10, pady=(6, 2))
        import datetime as _dt
        out_var = tk.StringVar(
            value=(f"快速成片_{_dt.datetime.now():%Y%m%d-%H%M}.mp4"))
        row = ttk.Frame(win)
        row.pack(fill="x", padx=10)
        ttk.Entry(row, textvariable=out_var).pack(side="left", fill="x",
                                                  expand=True)
        ttk.Button(row, text="…", width=3,
                   command=lambda: self._pick_export_path(out_var,
                                                          tk.StringVar(
                                                              value="mp4"))) \
            .pack(side="left", padx=(4, 0))
        ttk.Label(win, text="3. 点开始：自动拼主轨 → 渲染导出",
                  foreground="#9a9a9a").pack(anchor="w", padx=10, pady=(8, 0))
        result = {}

        def on_ok():
            sel = [videos[i] for i in lb.curselection()]
            if not sel:
                messagebox.showerror("错误", "请至少选择 1 个视频。")
                return
            try:
                w = int(res_var.get().split("×")[0].strip())
                h = int(res_var.get().split("×")[1].split()[0].strip())
            except Exception:
                w, h = 1920, 1080
            tr = trans_var.get()
            tdur = 0.5 if "0.5" in tr else (1.0 if "1s" in tr else 0.0)
            tname = "fade" if "fade" in tr else ("dissolve" if "dissolve" in tr else "")
            result["data"] = {"files": sel, "w": w, "h": h,
                              "tname": tname, "tdur": tdur,
                              "out": out_var.get().strip()}
            win.destroy()

        ttk.Button(win, text="⚡ 开始成片", command=on_ok) \
            .pack(anchor="w", padx=10, pady=12)
        self.root.wait_window(win)
        data = result.get("data")
        if not data:
            return
        # 组项目：清空时间轴 → 主轨按顺序全片拼接（带转场）
        self.undo.clear()
        proj = self._quick_build(data["files"], data["w"], data["h"],
                                 data["tname"], data["tdur"])
        if not proj.track("main").clips:
            messagebox.showerror("错误", "所选文件都无法读取时长。")
            return
        self.project = proj
        self.timeline.project = proj
        self._after_model_change()
        log.info("快速成片：%d 段，画布 %dx%d",
                 len(main.clips), data["w"], data["h"])
        # 直接渲染（走同一 worker 队列）
        self.rendering = True
        self.render_progress.configure(value=0)
        self.status_var.set("快速成片渲染中…")
        self._refresh_controls()
        opts = {"path": data["out"], "container": "mp4", "crf": 20,
                "keep": False}
        t = threading.Thread(target=self._render_worker, args=(opts,),
                             daemon=True)
        t.start()

    def _show_modal(self, win, w, h):
        """把模态弹窗居中并置顶，确保用户一定能看到。"""
        try:
            win.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
            y = self.root.winfo_rooty() + 40
            win.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
            win.deiconify()
            win.lift()
            win.focus_force()
        except Exception:
            pass

    def _quick_build(self, files, w, h, tname, tdur):
        """快速成片拼盘：按顺序全片拼接主轨并带转场（可独立测试/复用）。"""
        proj = Project(canvas_w=w, canvas_h=h)
        main = proj.track("main", create=True)
        ts = 0.0
        for i, f in enumerate(files):
            span = self.engine.source_length(f)
            if span <= 0:
                continue
            tr = None
            if i < len(files) - 1 and tname and tdur > 0:
                tr = {"name": tname, "dur": min(tdur, span)}
            c = VideoClip(src=f, ts=round(ts, 3), duration=round(span, 3),
                          in_point=0, out_point=round(span, 3), transition=tr)
            main.add(c)
            ts += span - (tdur if tr else 0.0)
        return proj

    def _export_dialog(self):
        """导出设置：格式 + 画质 + 路径 + 保留中间产物。返回 dict 或 None。"""
        win = tk.Toplevel(self.root)
        win.title("导出渲染设置")
        win.transient(self.root)
        win.grab_set()
        self._show_modal(win, 460, 240)
        ttk.Label(win, text="格式:").grid(row=0, column=0, sticky="e",
                                          padx=8, pady=6)
        fmt_var = tk.StringVar(value="mp4")
        ttk.Combobox(win, textvariable=fmt_var, state="readonly", width=10,
                     values=["mp4", "mov", "webm"]) \
            .grid(row=0, column=1, sticky="w")
        ttk.Label(win, text="画质:").grid(row=1, column=0, sticky="e", padx=8)
        qvar = tk.StringVar(value="中")
        ttk.Combobox(win, textvariable=qvar, state="readonly", width=14,
                     values=["高（CRF 16）", "中（CRF 20）",
                             "低（CRF 26）", "更低（CRF 30）",
                             "无损（文件巨大）"]) \
            .grid(row=1, column=1, sticky="w")
        ttk.Label(win, text="输出路径:").grid(row=2, column=0, sticky="e", padx=8)
        # 自动命名：项目名_分辨率_时间戳（避免重名覆盖）
        import datetime as _dt
        out_dir = (getattr(self, "_last_export_dir", "")
                   or self.dir_var.get().strip() or self.base_dir)
        auto = (f"{self.project.name or '未命名'}_{self.project.canvas_w}x"
                f"{self.project.canvas_h}_{_dt.datetime.now():%Y%m%d-%H%M}.mp4")
        path_var = tk.StringVar(value=os.path.abspath(
            os.path.join(out_dir, auto)))
        ttk.Entry(win, textvariable=path_var, width=34).grid(
            row=2, column=1, sticky="w", padx=(0, 4))
        ttk.Button(win, text="…", width=3,
                   command=lambda: self._pick_export_path(path_var, fmt_var)) \
            .grid(row=2, column=2)

        def _sync_ext(*_a):
            p = path_var.get().strip()
            if p:
                base, _e = os.path.splitext(p)
                path_var.set(base + "." + fmt_var.get())
        fmt_var.trace_add("write", _sync_ext)
        keep_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(win, text="保留中间产物（无色损轨文件，供调试/复用）",
                        variable=keep_var).grid(row=3, column=1, sticky="w")
        result = {}

        def on_ok():
            p = path_var.get().strip()
            if not p:
                messagebox.showerror("错误", "请选择输出路径。")
                return
            qmap = {"高（CRF 16）": 16, "中（CRF 20）": 20,
                    "低（CRF 26）": 26, "更低（CRF 30）": 30,
                    "无损（文件巨大）": 0}
            result["data"] = {"path": p, "container": fmt_var.get(),
                              "crf": qmap[qvar.get()],
                              "keep": keep_var.get()}
            win.destroy()

        ttk.Button(win, text="开始渲染", command=on_ok) \
            .grid(row=4, column=1, sticky="w", padx=8, pady=12)
        self.root.wait_window(win)
        return result.get("data")

    def _pick_export_path(self, path_var, fmt_var):
        ext = fmt_var.get()
        p = filedialog.asksaveasfilename(
            defaultextension=f".{ext}",
            filetypes=[(f"{ext.upper()} 视频", f"*.{ext}")],
            initialfile=f"render.{ext}")
        if p:
            path_var.set(p)

    def _render_worker(self, opts: dict):
        try:
            inter_dir = None
            if opts.get("keep"):
                base = os.path.splitext(opts["path"])[0]
                inter_dir = os.path.join(base + "_中间产物")
            self.engine.render(
                self.project, opts["path"],
                on_progress=lambda p: self.q.put(("progress", p)),
                on_log=lambda s: self.q.put(("log", s)),
                container=opts.get("container", "mp4"),
                crf=int(opts.get("crf", 20)),
                intermediates_dir=inter_dir)
            self.q.put(("done", opts["path"]))
        except RenderError as e:
            log.error("渲染失败: %s", e)
            self.q.put(("fail", str(e)))
        except Exception as e:
            log.exception("渲染异常: %s", e)
            self.q.put(("fail", str(e)))

    def _render_done_dialog(self, path: str):
        """渲染完成：显示完整路径，可打开所在文件夹 / 预览 / 关闭。"""
        if not os.path.isfile(path):
            messagebox.showerror("渲染完成", f"完成但找不到文件:\n{path}\n"
                                 "（若系统默认磁盘在别处，建议下次把路径改到素材文件夹）")
            return
        win = tk.Toplevel(self.root)
        win.title("渲染完成")
        win.transient(self.root)
        win.grab_set()
        self._show_modal(win, 520, 150)
        ttk.Label(win, text="✅ 导出成功：" + path,
                  wraplength=480).pack(anchor="w", padx=12, pady=(12, 4))
        row = ttk.Frame(win)
        row.pack(anchor="w", padx=12, pady=6)
        ttk.Button(row, text="打开所在文件夹",
                   command=lambda: (os.startfile(os.path.dirname(path)),
                                    win.destroy())).pack(side="left", padx=4)
        ttk.Button(row, text="在预览中播放",
                   command=lambda: self._preview_rendered(path)).pack(
            side="left", padx=4)
        def _copy():
            try:
                win.clipboard_clear()
                win.clipboard_append(path)
                self.status_var.set("已复制成片路径")
            except Exception:
                pass
        ttk.Button(row, text="复制路径", command=_copy).pack(side="left", padx=4)
        ttk.Button(row, text="关闭", command=win.destroy).pack(side="left", padx=4)

    def _preview_rendered(self, path: str):
        """在预览中播放渲染结果（元数据后台探测，不冻结 UI）。"""
        self._timeline_play = False
        self._start_task(
            "打开成片预览",
            lambda: self.engine.source_meta(path),
            lambda meta: self._do_preview_rendered(path, meta),
            block=True)

    def _do_preview_rendered(self, path: str, meta: dict):
        src_len = float(meta.get("duration", 0) or 0)
        self.player.load(path, 0.0, src_len or 0.1, 1.0, 960, 540,
                         audio_src=path, audio_in=0.0,
                         audio_len=src_len or 0.1, audio_vol=1.0,
                         src_w=int(meta.get("width", 0) or 0),
                         src_h=int(meta.get("height", 0) or 0),
                         fps=float(meta.get("fps", 0) or 0))
        self._preview_clip_id = None
        self._preview_ts = 0.0
        self.player.play()
        self._idle("成片预览中")

    def _poll_queue(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "progress":
                    self.render_progress.configure(value=data * 100)
                    self.status_var.set(f"渲染中… {int(data * 100)}%")
                elif kind == "done":
                    self.rendering = False
                    self.render_progress.configure(value=100)
                    self.status_var.set(f"✅ 渲染完成: {data}")
                    self._refresh_controls()
                    log.info("渲染完成: %s", data)
                    self._mark_exported(data)
                    self._render_done_dialog(data)
                    src_len = self.engine.source_length(data)
                    self.player.load(data, 0.0, src_len, 1.0, 960, 540,
                                     audio_src=data, audio_in=0.0,
                                     audio_len=src_len, audio_vol=1.0)
                    self._preview_ts = 0.0
                    self.player.play()
                elif kind == "fail":
                    self.rendering = False
                    self.status_var.set("渲染失败（详见日志）")
                    self._refresh_controls()
                    messagebox.showerror("渲染失败", data)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    # ================================================================ 帮助
    def _maybe_show_guide(self):
        """首次启动显示三步引导（只一次；窗口不可见时不弹）。"""
        if self.settings.get("guide_shown"):
            return
        if not getattr(self.root, "winfo_viewable", lambda: True)():
            return
        self.settings.set("guide_shown", True)
        self.settings.save()
        messagebox.showinfo(
            "三步上手",
            "1. 左侧选素材文件夹，双击/拖拽素材进时间轴主轨\n"
            "2. ▶ 从头播放整条时间轴；点时间轴任意位置跳转；\n"
            "   右键片段有 变速/跨轨/复制/分割 等菜单\n"
            "3. 🎬 导出前点 ◧ 画布选分辨率，成品自动带预览\n\n"
            "（你的每一步都会自动保存，随时可以继续）")

    def _show_help(self):
        messagebox.showinfo(
            "使用说明",
            "1. 左侧选文件夹：🎞视频/🖼图片/🎵音频 自动列出\n"
            "2. 视频→主轨（满屏拼接）或画中画（PiP）；图片→画中画；音频→音频轨\n"
            "3. 时间轴：单击选中｜双击预览(含声音)｜拖动移动(带磁吸)｜拖边缘裁剪\n"
            "4. 空格 播放/暂停；属性面板改速度/音量/淡入淡出/位置\n"
            "5. 转场：选中前段→选转场类型和秒数→应用（需两段无缝相邻，磁吸可对齐）\n"
            "6. 变速：常用速度按钮 / 变速到目标时长 / 渐变起速-末速(视频)\n"
            "7. 接缝：磁吸对齐 → 拖动微调；『闭合空隙』或『波纹删除』闭合接缝\n"
            "8. 项目→项目设置：设导出分辨率/帧率；编辑→撤销/重做 (Ctrl+Z/Y)\n"
            "9. 🎬导出渲染生成成品；完成后自动在预览里播放；状态自动记忆")


def main():
    from . import bundled_dir
    _logmod.setup_logging(bundled_dir())
    root = tk.Tk()
    apply_dark_theme(root)
    root.geometry("1440x820")
    root.minsize(1020, 660)
    try:
        EditorApp(root)
        root.mainloop()
    except Exception:
        log.exception("程序崩溃")
        messagebox.showerror("程序错误", "发生未预期错误，详见 logs 目录。")
        raise