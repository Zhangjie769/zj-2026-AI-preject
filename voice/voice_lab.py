# -*- coding: utf-8 -*-
"""
语音属性合成器：输入文本，像"点属性"一样选性别/语气/音调，一键合成音频
========================================================================
两种用法：
  GUI：  py voice_lab.py --gui          # 图形界面：下拉框选属性
  CLI：  py voice_lab.py "北京欢迎你" --voice 女声 --mood 柔媚 --pitch 略高 --rate 正常 --out 北京欢迎你.wav

底层流水线（业界标准做法）：
  1) edge-tts 免费 API 生成原声（需联网；也可换本地 Piper 等）
  2) librosa 施加属性：变速(time_stretch) + 变调(pitch_shift) + 句尾上扬 + 收势 + 微回声
     —— 全部对应教程第一部分的旋钮表
"""
import argparse
import asyncio
import os
import sys
import tempfile

import numpy as np
import soundfile as sf
import librosa

SR = 22050

# ---------- 属性 → 声学旋钮 的映射表（可推敲、可改） ----------

VOICES = {
    "女声·晓晓": "zh-CN-XiaoxiaoNeural",
    "少女·晓伊": "zh-CN-XiaoyiNeural",
    "男声·云希": "zh-CN-YunxiNeural",
    "男声·云健": "zh-CN-YunjianNeural",
}

MOODS = {
    "默认": dict(speed=1.00, pitch=0.0, tail=0.0, echo=0, fade=0.0, gain=0.95),
    "柔媚": dict(speed=0.90, pitch=1.5, tail=2.2, echo=0, fade=0.15, gain=0.90),
    "活泼": dict(speed=1.08, pitch=2.0, tail=1.2, echo=0, fade=0.0, gain=0.95),
    "沉稳": dict(speed=0.86, pitch=-1.0, tail=0.0, echo=1, fade=0.0, gain=0.98),
    "可爱": dict(speed=1.10, pitch=3.0, tail=2.5, echo=0, fade=0.0, gain=0.95),
    "慵懒": dict(speed=0.82, pitch=0.0, tail=1.0, echo=1, fade=0.20, gain=0.85),
}

PITCH_LEVELS = {"很低": -4, "略低": -2, "正常": 0, "略高": 2, "高": 4}
RATE_LEVELS = {"慢": 0.9, "正常": 1.0, "快": 1.1}


def tts_mp3(text: str, voice_id: str) -> str:
    """edge-tts 生成 mp3（免费，需联网）"""
    import edge_tts

    tmp = os.path.join(tempfile.gettempdir(), f"voice_lab_{os.getpid()}.mp3")

    async def _gen():
        tts = edge_tts.Communicate(text, voice_id)
        await tts.save(tmp)

    asyncio.run(_gen())
    return tmp


def add_echo(x, sr, level=1.0):
    out = x.copy()
    for d, g in ((0.07, 0.14 * level), (0.13, 0.09 * level), (0.22, 0.05 * level)):
        n = int(d * sr)
        if n < len(x):
            out[n:] += g * x[:-n]
    m = np.max(np.abs(out))
    return out * (0.9 / m) if m > 0 else out


def apply_attrs(y, sr, mood, pitch_semi, rate, tail_extra=0.0):
    """把属性包施加到音频：变速→变调→句尾上扬→收势→回声"""
    y = librosa.effects.time_stretch(y, rate=rate * mood["speed"])
    y = librosa.effects.pitch_shift(y, sr=sr, n_steps=pitch_semi + mood["pitch"])
    tail = mood["tail"] + tail_extra
    if tail > 0:
        n = len(y)
        k = int(n * 0.35)
        y[-k:] = librosa.effects.pitch_shift(y[-k:], sr=sr, n_steps=tail)
    env = np.ones(len(y))
    if mood["fade"]:
        m = int(len(y) * mood["fade"])
        env[-m:] *= np.linspace(1, 0.15, m)
    y = y * env * mood["gain"]
    if mood["echo"]:
        y = add_echo(y, sr)
    f = int(0.015 * sr)
    y[:f] *= np.linspace(0, 1, f)
    y[-f:] *= np.linspace(1, 0, f)
    return y


def synthesize(text, voice_name, mood_name, pitch_name, rate_name, out_path):
    """完整流水线：TTS → 属性处理 → 写文件；返回参数说明"""
    rate = RATE_LEVELS[rate_name]
    pitch_semi = PITCH_LEVELS[pitch_name]
    mood = MOODS[mood_name]
    y, sr = librosa.load(tts_mp3(text, VOICES[voice_name]), sr=SR, mono=True)
    out = apply_attrs(y, sr, mood, pitch_semi, rate)
    m = np.max(np.abs(out))
    sf.write(out_path, out * (0.9 / m), sr)

    info = (f"文本「{text}」｜音色 {voice_name}｜语气 {mood_name}｜音调 {pitch_name}｜语速 {rate_name}\n"
            f"实际旋钮：变速 ×{rate * mood['speed']:.2f} ｜ 变调 {pitch_semi + mood['pitch']:+.1f} 半音"
            f" ｜ 句尾上扬 {mood['tail']:+.1f} 半音 ｜ 回声 {'开' if mood['echo'] else '关'} ｜ 收势 {mood['fade'] or 0:.0%}")
    return info


# ---------- CLI ----------

def cli():
    ap = argparse.ArgumentParser(description="语音属性合成器")
    ap.add_argument("text", nargs="?", default="北京欢迎你")
    ap.add_argument("--voice", default="女声·晓晓", choices=list(VOICES))
    ap.add_argument("--mood", default="柔媚", choices=list(MOODS))
    ap.add_argument("--pitch", default="略高", choices=list(PITCH_LEVELS))
    ap.add_argument("--rate", default="正常", choices=list(RATE_LEVELS))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = args.out or f"voice_out_{args.mood}_{args.pitch}.wav"
    info = synthesize(args.text, args.voice, args.mood, args.pitch, args.rate, out)
    print(info)
    print(f"[OK] 已合成 → {out}")


# ---------- GUI ----------

def gui():
    import tkinter as tk
    from tkinter import ttk, messagebox
    import threading

    try:
        import sounddevice as sd
    except ImportError:
        sd = None

    root = tk.Tk()
    root.title("语音属性合成器 voice_lab")
    root.geometry("520x420")

    tk.Label(root, text="输入文本：").pack(anchor="w", padx=12, pady=(14, 2))
    text_var = tk.StringVar(value="北京欢迎你")
    tk.Entry(root, textvariable=text_var, font=("Microsoft YaHei", 12)).pack(
        fill="x", padx=12)

    grid = tk.Frame(root)
    grid.pack(fill="x", padx=12, pady=8)
    rows = [("音色", VOICES, "女声·晓晓"), ("语气", MOODS, "柔媚"),
            ("音调", PITCH_LEVELS, "略高"), ("语速", RATE_LEVELS, "正常")]
    vars_ = {}
    for i, (label, opts, default) in enumerate(rows):
        tk.Label(grid, text=label).grid(row=i, column=0, sticky="w", padx=4, pady=3)
        v = tk.StringVar(value=default)
        ttk.Combobox(grid, textvariable=v, values=list(opts), state="readonly",
                     width=10).grid(row=i, column=1, sticky="w", padx=4)
        vars_[label] = v

    status = tk.Label(root, text="就绪", fg="#555", anchor="w", justify="left")
    status.pack(fill="x", padx=12, pady=6)

    def do_synth(auto_play=False):
        text = text_var.get().strip()
        if not text:
            messagebox.showwarning("提示", "请输入文本")
            return
        status.config(text="合成中（需联网调 edge-tts）…")
        root.update()

        def work():
            out = f"voice_out_{vars_['语气'].get()}_{vars_['音调'].get()}.wav"
            try:
                info = synthesize(text, vars_["音色"].get(), vars_["语气"].get(),
                                  vars_["音调"].get(), vars_["语速"].get(), out)
                msg = info + f"\n[OK] 已合成 → {out}"
                if auto_play and sd is not None:
                    y, _ = librosa.load(out, sr=SR, mono=True)
                    sd.play(y, SR)
                    msg += "（正在播放）"
            except Exception as e:
                msg = f"失败：{e}\n（edge-tts 需要联网）"
            status.config(text=msg)

        threading.Thread(target=work, daemon=True).start()

    btn = tk.Frame(root)
    btn.pack(pady=6)
    tk.Button(btn, text="🎵 只合成", width=12,
              command=lambda: do_synth(False)).pack(side="left", padx=6)
    tk.Button(btn, text="▶ 合成并播放", width=14,
              command=lambda: do_synth(True)).pack(side="left", padx=6)
    tk.Label(root,
             text="属性→旋钮：性别=换音色，语气=语速+F0+句尾上扬+回声+收势，音调=pitch shift\n"
                  "底层用 edge-tts 免费 API（需联网），处理用 librosa（本教程同款技术）",
             fg="#888", font=("Microsoft YaHei", 8), justify="left").pack(side="bottom", pady=8)
    root.mainloop()


if __name__ == "__main__":
    if "--gui" in sys.argv:
        gui()
    else:
        sys.argv = [a for a in sys.argv if a != "--gui"]
        cli()