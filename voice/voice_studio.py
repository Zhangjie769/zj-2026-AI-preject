# -*- coding: utf-8 -*-
"""
语音工坊 App（voice_studio）
============================
上层：音乐播放器（播放列表 / 播放·暂停·停止 / 上一首·下一首 / 进度拖动 / 音量）
下层：双模式语音工坊（素材按关键词改方向 / 文字按关键词直接造）——合成结果自动加入播放列表

启动：双击「启动语音工坊.bat」，或 py voice_studio.py
依赖：sounddevice soundfile librosa numpy（已装）；文字模式需联网（edge-tts）
"""
import os
import sys
import threading

import numpy as np
import soundfile as sf
import librosa

SR = 22050

import voice_workshop as vw          # 复用关键词解析与处理引擎


# ======================================================================
# 播放器内核（与 GUI 解耦，便于测试）
# ======================================================================
class Player:
    def __init__(self):
        self.stream = None
        self.sr = SR
        self.data = None
        self.pos = 0                 # 当前采样位置
        self.volume = 0.8
        self.paused = False
        self.finished = False
        self.n_samples = 0

    def load(self, path):
        self.data, self.sr = librosa.load(path, sr=None, mono=True)
        self.n_samples = len(self.data)
        self.pos = 0
        self.paused = False
        self.finished = False

    @property
    def duration(self):
        return self.n_samples / self.sr if self.n_samples else 0.0

    def _callback(self, outdata, frames, time_info, status):
        if self.data is None or self.paused:
            outdata.fill(0)
            return
        start = self.pos
        end = min(start + frames, self.n_samples)
        if end > start:
            outdata[: end - start, 0] = self.data[start:end] * self.volume
        if end - start < frames:
            outdata[end - start:, 0] = 0
        self.pos = end
        if self.pos >= self.n_samples:
            self.pos = 0
            self.finished = True     # GUI 轮询到后自动下一首

    def play(self):
        import sounddevice as sd
        if self.data is None:
            return
        self.finished = False
        if self.stream is None:
            self.stream = sd.OutputStream(samplerate=self.sr, channels=1,
                                          dtype="float32", callback=self._callback,
                                          blocksize=1024)
            self.stream.start()
        else:
            if not self.stream.active:
                self.stream.start()
        self.paused = False

    def pause_toggle(self):
        if self.stream is not None:
            self.paused = not self.paused

    def stop(self):
        self.paused = False
        self.pos = 0
        if self.stream is not None:
            self.stream.stop()

    def seek_ratio(self, ratio):
        """按 0~1 比例跳转"""
        if self.data is not None:
            self.pos = int(ratio * self.n_samples)

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


# ======================================================================
# GUI
# ======================================================================
def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    try:
        import sounddevice as sd   # 仅用于触发默认设备就绪检查
        _ = sd.query_devices()
    except Exception:
        pass

    player = Player()
    root = tk.Tk()
    root.title("语音工坊 App · 音频处理 + 音乐播放器")
    root.geometry("940x700")
    if os.environ.get("VWS_TEST"):   # 自动化测试：1.2 秒后自动关闭
        root.after(1200, root.destroy)

    # ---------- 播放列表 ----------
    playlist = []   # [(路径, 显示名)]

    def refresh_list():
        lb.delete(0, tk.END)
        for _, name in playlist:
            lb.insert(tk.END, name)
        cnt_label.config(text=f"共 {len(playlist)} 首")

    def scan_folders():
        for folder in ("demo_wavs", "material_lib", "vary_10"):
            if not os.path.isdir(folder):
                continue
            for fn in sorted(os.listdir(folder)):
                if fn.lower().endswith((".wav", ".mp3", ".m4a", ".flac", ".ogg")):
                    p = os.path.join(folder, fn)
                    if p not in [x[0] for x in playlist]:
                        playlist.append((p, f"[{folder}] {fn}"))
        refresh_list()

    def add_files():
        files = filedialog.askopenfilenames(
            title="选择音频", filetypes=[("音频文件", "*.wav *.mp3 *.m4a *.flac *.ogg")])
        for f in files:
            playlist.append((f, os.path.basename(f)))
        refresh_list()

    def remove_selected():
        sel = lb.curselection()
        if sel:
            for i in reversed(sel):
                playlist.pop(i)
            refresh_list()

    def play_at(idx):
        if 0 <= idx < len(playlist):
            path, _ = playlist[idx]
            try:
                player.load(path)
                player.play()
                status.config(text=f"▶ 播放：{playlist[idx][1]}")
            except Exception as e:
                messagebox.showerror("播放失败", f"{path}\n{e}")

    def on_double(e):
        sel = lb.curselection()
        if sel:
            play_at(sel[0])

    # ---- 播放器区 ----
    top = ttk.LabelFrame(root, text="音乐播放器")
    top.pack(fill="x", padx=8, pady=(8, 4))

    box_panel = tk.Frame(top)
    box_panel.pack(fill="x", padx=6, pady=4)
    lb = tk.Listbox(box_panel, height=7, font=("Microsoft YaHei", 9))
    lb.pack(side="left", fill="both", expand=True)
    lb.bind("<Double-Button-1>", on_double)
    sb = ttk.Scrollbar(box_panel, orient="vertical", command=lb.yview)
    sb.pack(side="left", fill="y")
    lb.config(yscrollcommand=sb.set)
    btn_col = tk.Frame(box_panel)
    btn_col.pack(side="left", padx=6)
    ttk.Button(btn_col, text="＋ 添加音频", command=add_files).pack(fill="x", pady=1)
    ttk.Button(btn_col, text="－ 移除选中", command=remove_selected).pack(fill="x", pady=1)
    ttk.Button(btn_col, text="↻ 重新扫描", command=lambda: (playlist.clear(), scan_folders())).pack(fill="x", pady=1)
    cnt_label = ttk.Label(btn_col, text="共 0 首")
    cnt_label.pack(pady=4)

    # 控制行
    ctrl = tk.Frame(top)
    ctrl.pack(fill="x", padx=6, pady=2)
    cur = [0]   # 当前播放索引

    def do_prev():
        if playlist:
            cur[0] = (cur[0] - 1) % len(playlist)
            play_at(cur[0])

    def do_next():
        if playlist:
            cur[0] = (cur[0] + 1) % len(playlist)
            play_at(cur[0])

    ttk.Button(ctrl, text="⏮ 上一首", width=9, command=do_prev).pack(side="left", padx=2)
    play_btn = ttk.Button(ctrl, text="▶ 播放", width=8,
                          command=lambda: play_at(cur[0]) if playlist else None)
    play_btn.pack(side="left", padx=2)
    ttk.Button(ctrl, text="⏸ 暂停/继续", width=10, command=player.pause_toggle).pack(side="left", padx=2)
    ttk.Button(ctrl, text="⏹ 停止", width=7, command=lambda: (player.stop(),
              status.config(text="⏹ 已停止"))).pack(side="left", padx=2)
    ttk.Button(ctrl, text="⏭ 下一首", width=9, command=do_next).pack(side="left", padx=2)
    ttk.Label(ctrl, text="音量").pack(side="left", padx=(14, 2))
    vol = ttk.Scale(ctrl, from_=0, to=100, length=110,
                    command=lambda v: setattr(player, "volume", float(v) / 100))
    vol.set(80)
    vol.pack(side="left")

    # 进度行
    prog = tk.Frame(top)
    prog.pack(fill="x", padx=6, pady=3)
    time_label = ttk.Label(prog, text="00:00 / 00:00", width=16)
    time_label.pack(side="right")
    scale = ttk.Scale(prog, from_=0, to=1000, length=700)
    scale.set(0)
    scale.pack(side="left", fill="x", expand=True)
    # 拖动跳转
    dragging = [False]

    def on_press(e):
        dragging[0] = True

    def on_release(e):
        dragging[0] = False
        player.seek_ratio(scale.get() / 1000)

    scale.bind("<ButtonPress-1>", on_press)
    scale.bind("<ButtonRelease-1>", on_release)

    # ---------- 工坊区（复用 voice_workshop 引擎） ----------
    mid = ttk.Notebook(root)
    mid.pack(fill="both", expand=True, padx=8, pady=4)

    f1 = ttk.Frame(mid)
    mid.add(f1, text="① 素材模式：改音频")
    tk.Label(f1, text="音频文件：").grid(row=0, column=0, sticky="w", padx=10, pady=6)
    src_var = tk.StringVar()
    tk.Entry(f1, textvariable=src_var, width=56).grid(row=0, column=1, padx=4)
    def browse_src():
        v = filedialog.askopenfilename(
            filetypes=[("音频", "*.wav *.mp3 *.m4a *.flac *.ogg")])
        if v:
            src_var.set(v)
            # 顺手加入播放列表（含目录名更直观，这里用 basename）
            if v not in [x[0] for x in playlist]:
                playlist.append((v, os.path.basename(v)))
                refresh_list()
    ttk.Button(f1, text="浏览…", command=browse_src).grid(row=0, column=2)
    tk.Label(f1, text="我想改成（关键词）：").grid(row=1, column=0, sticky="w", padx=10, pady=6)
    kw1 = tk.StringVar(value="女生 柔媚 音调略高")
    tk.Entry(f1, textvariable=kw1, font=("Microsoft YaHei", 11), width=56).grid(
        row=1, column=1, padx=4, sticky="w")

    f2 = ttk.Frame(mid)
    mid.add(f2, text="② 文字模式：直接造")
    tk.Label(f2, text="文字内容：").grid(row=0, column=0, sticky="w", padx=10, pady=6)
    txt = tk.StringVar(value="北京欢迎你")
    tk.Entry(f2, textvariable=txt, font=("Microsoft YaHei", 11), width=56).grid(
        row=0, column=1, padx=4, sticky="w")
    tk.Label(f2, text="我想做成（关键词）：").grid(row=1, column=0, sticky="w", padx=10, pady=6)
    kw2 = tk.StringVar(value="少女 活泼 音调高 快")
    tk.Entry(f2, textvariable=kw2, font=("Microsoft YaHei", 11), width=56).grid(
        row=1, column=1, padx=4, sticky="w")

    def after_synth(out):
        if out not in [x[0] for x in playlist]:
            playlist.append((out, f"[合成] {os.path.basename(out)}"))
            refresh_list()
        idx = [i for i, (p, _) in enumerate(playlist) if p == out][0]
        play_at(idx)

    def do_audio_mode():
        p = src_var.get().strip()
        if not p:
            messagebox.showwarning("提示", "请先选择音频文件")
            return
        out = f"voice_out/{os.path.basename(p).rsplit('.', 1)[0]}_改.wav"
        os.makedirs("voice_out", exist_ok=True)

        def work():
            try:
                vw.run_audio(p, kw1.get(), out)
                after_synth(out)
                status.config(text=f"✅ 素材模式完成：{out}\n旋钮：{vw.describe(vw.parse_keywords(kw1.get()))}")
            except Exception as e:
                status.config(text=f"❌ 失败：{e}")

        threading.Thread(target=work, daemon=True).start()

    def do_text_mode():
        t = txt.get().strip()
        if not t:
            messagebox.showwarning("提示", "请输入文字")
            return
        out = "voice_out/app_文字.wav"
        os.makedirs("voice_out", exist_ok=True)

        def work():
            try:
                vw.run_text(t, kw2.get(), out)
                after_synth(out)
                status.config(text=f"✅ 文字模式完成：{out}\n旋钮：{vw.describe(vw.parse_keywords(kw2.get()))}")
            except Exception as e:
                status.config(text=f"❌ 失败：{e}（文字模式需联网）")

        threading.Thread(target=work, daemon=True).start()

    btns = tk.Frame(mid)
    btns.pack(pady=4)
    ttk.Button(btns, text="① 改这段音频", width=18, command=do_audio_mode).pack(side="left", padx=8)
    ttk.Button(btns, text="② 造出这段音频", width=18, command=do_text_mode).pack(side="left", padx=8)

    status = tk.Label(root, text="就绪。关键词示例：少女 可爱 音调高 快 / 男声 沉稳 混响 / 怪兽 / 复古 / 太空",
                      fg="#444", anchor="w", justify="left", wraplength=900,
                      font=("Microsoft YaHei", 9))
    status.pack(fill="x", padx=10, pady=(2, 6))

    # ---------- 轮询：进度条 + 自动下一首 ----------
    def tick():
        if player.data is not None and not dragging[0]:
            pos_s, dur_s = player.pos / player.sr, player.duration
            scale.set(pos_s / dur_s * 1000 if dur_s else 0)
            time_label.config(text=f"{int(pos_s // 60):02d}:{int(pos_s % 60):02d}"
                                   f" / {int(dur_s // 60):02d}:{int(dur_s % 60):02d}")
        if player.finished:
            player.finished = False
            do_next()
        root.after(100, tick)

    scan_folders()
    root.after(100, tick)
    root.protocol("WM_DELETE_WINDOW", lambda: (player.close(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        # 自检：播放 1 秒测试音
        t = np.arange(SR) / SR
        sf.write("_t.wav", 0.4 * np.sin(2 * np.pi * 440 * t), SR)
        p = Player()
        p.load("_t.wav")
        p.volume = 0.3
        p.play()
        import time
        time.sleep(1.4)
        p.stop()
        p.close()
        os.remove("_t.wav")
        print("APP SMOKE OK")
    else:
        gui()