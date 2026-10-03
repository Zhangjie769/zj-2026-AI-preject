# -*- coding: utf-8 -*-
"""
音频工坊 voice_workshop
=======================
两种模式，一个入口，都按"关键词"描述方向：

  【素材模式】给我一段音频，按我的方向（关键词）改它
      py voice_workshop.py --audio 素材.wav --keywords "女生 柔媚 音调略高"
  【文字模式】没素材？给我文字 + 关键词，直接生成
      py voice_workshop.py --text "北京欢迎你" --keywords "少女 活泼 音调高 快"
  【图形界面】两种模式都有选项卡
      py voice_workshop.py --gui

关键词清单：py voice_workshop.py --list
（性别/音调/语速/语气/效果 全部自然语言，见 --list 或脚本内 KEYWORDS)
"""
import argparse
import asyncio
import os
import random
import sys
import tempfile

import numpy as np
import soundfile as sf
import librosa

SR = 22050

# 音色表（文字模式底层用 edge-tts）
VOICES = {
    "女声·晓晓": "zh-CN-XiaoxiaoNeural",
    "少女·晓伊": "zh-CN-XiaoyiNeural",
    "男生·云希": "zh-CN-YunxiNeural",
    "男声·云健": "zh-CN-YunjianNeural",
}
GENDER_WORDS = {"女生": "女声·晓晓", "女声": "女声·晓晓", "少女": "少女·晓伊",
                "男声": "男声·云健", "男生": "男生·云希", "男孩": "男生·云希"}


def parse_keywords(kw: str) -> dict:
    """大白话关键词 → 声学旋钮。规则简单可读，改这里就改'方向'的定义"""
    a = dict(speed=1.00, pitch=0.0, tail=0.0, echo=0.0, fade=0.0,
             hp=0, robot=0, gain=1.0, vinyl=0, space=0, ghost=0, monster=0, eightbit=0)
    t = kw

    # —— 语气包（命中最先出现的就叠加工序）——
    if "撒娇" in t or "嗲" in t:
        a["tail"] = max(a["tail"], 2.5); a["speed"] -= 0.10; a["fade"] = max(a["fade"], 0.15)
    if "柔媚" in t or "温柔" in t:
        a["speed"] -= 0.08; a["tail"] = max(a["tail"], 2.0); a["fade"] = max(a["fade"], 0.12)
    if "可爱" in t:
        a["pitch"] += 2.5; a["tail"] = max(a["tail"], 2.2); a["speed"] += 0.06
    if "活泼" in t:
        a["speed"] += 0.10; a["pitch"] += 1.8; a["tail"] = max(a["tail"], 1.0)
    if "沉稳" in t or "稳重" in t:
        a["speed"] -= 0.12; a["pitch"] -= 1.0
    if "悲伤" in t or "忧郁" in t:
        a["speed"] -= 0.12; a["pitch"] -= 2.0; a["fade"] = max(a["fade"], 0.20)
    if "兴奋" in t or "激动" in t:
        a["speed"] += 0.12; a["pitch"] += 2.5
    if "慵懒" in t:
        a["speed"] -= 0.16; a["echo"] = max(a["echo"], 0.8)

    # —— 音调（注意：先匹配长词）——
    if "音调很高" in t:
        a["pitch"] += 6
    elif "音调高" in t or "偏高" in t:
        a["pitch"] += 4
    elif "音调略高" in t or "略高" in t:
        a["pitch"] += 2
    elif "音调很低" in t:
        a["pitch"] -= 6
    elif "音调低" in t or "低沉" in t or "偏低" in t:
        a["pitch"] -= 4
    elif "略低" in t:
        a["pitch"] -= 2

    # —— 语速 ——
    if "很慢" in t:
        a["speed"] -= 0.25
    elif "慢" in t or "舒缓" in t:
        a["speed"] -= 0.10
    elif "快" in t or "急促" in t:
        a["speed"] += 0.12

    # —— 效果 ——
    if "电话" in t:
        a["hp"] = 3400                       # 低通=电话带宽
    if "机器人" in t or "机械" in t:
        a["robot"] = 1                       # 叠加 +12 半音副本 → 合成器感
    if "混响" in t or "空旷" in t or "回声" in t or "空间感" in t:
        a["echo"] = max(a["echo"], 1.0)
    if "响亮" in t or "大声" in t:
        a["gain"] = 1.15
    if "复古" in t or "老唱片" in t or "留声机" in t:
        a["vinyl"] = 1
    if "磁带" in t or "录音机" in t:
        a["vinyl"] = 2                       # 磁带 = 复古 + 失真抖动
    if "太空" in t or "宇宙" in t or "外太空" in t:
        a["space"] = 1
    if "幽灵" in t or "阴森" in t or "恐怖" in t or "鬼" in t:
        a["ghost"] = 1
    if "怪兽" in t or "巨人" in t or "庞然大物" in t:
        a["monster"] = 1
    if "8bit" in t or "芯片" in t or "游戏机" in t or "红白机" in t:
        a["eightbit"] = 1
    return a


KEYWORDS_HELP = (
    "性别/音色：女生 少女 男声 男生\n"
    "音调：音调很高 音调高 音调略高 偏高 略高 音调很低 音调低 低沉 偏低 略低\n"
    "语速：很慢 慢 舒缓 快 急促\n"
    "语气：柔媚 撒娇 嗲 温柔 可爱 活泼 沉稳 稳重 悲伤 忧郁 兴奋 激动 慵懒\n"
    "效果：电话 机器人 机械 混响 空旷 回声 空间感 响亮 大声\n"
    "      复古 老唱片 留声机 磁带 录音机 太空 宇宙 幽灵 阴森 恐怖 怪兽 巨人 8bit 芯片 游戏机\n")


def list_keywords():
    print("【音频工坊关键词词典】\n")
    print(KEYWORDS_HELP)


def describe(attrs, voice=None) -> str:
    s = (f"变速 ×{attrs['speed']:.2f} ｜ 变调 {attrs['pitch']:+.1f} 半音"
         f" ｜ 句尾上扬 {attrs['tail']:+.1f} 半音"
         f" ｜ 回声 {'开' if attrs['echo'] else '关'}"
         f" ｜ 收势 {attrs['fade'] or 0:.0%}"
         f" ｜ 电话感 {'开' if attrs['hp'] else '关'}"
         f" ｜ 机器感 {'开' if attrs['robot'] else '关'}")
    for tag, key in (("复古", "vinyl"), ("太空", "space"), ("幽灵", "ghost"),
                     ("怪兽", "monster"), ("8bit", "eightbit")):
        s += f" ｜ {tag}感 {'开' if attrs[key] else '关'}"
    return s


# ---------- 处理引擎 ----------

def add_echo(x, sr, level=1.0):
    out = x.copy()
    for d, g in ((0.07, 0.14 * level), (0.13, 0.09 * level), (0.22, 0.05 * level)):
        n = int(d * sr)
        if n < len(x):
            out[n:] += g * x[:-n]
    m = np.max(np.abs(out))
    return out * (0.9 / m) if m > 0 else out


def process(y, sr, a):
    """把旋钮施加到音频（顺序固定：速率→音调→尾音→收势→效果→响度）"""
    y = librosa.effects.time_stretch(y, rate=a["speed"])
    if a["pitch"]:
        y = librosa.effects.pitch_shift(y, sr=sr, n_steps=a["pitch"])
    if a["tail"]:
        n = len(y); k = int(n * 0.35)
        y[-k:] = librosa.effects.pitch_shift(y[-k:], sr=sr, n_steps=a["tail"])
    env = np.ones(len(y))
    if a["fade"]:
        m = int(len(y) * a["fade"])
        env[-m:] *= np.linspace(1, 0.15, m)
    y = y * env
    if a["echo"]:
        y = add_echo(y, sr, a["echo"])
    if a["hp"]:
        y = _lowpass(y, a["hp"], sr)
    if a["robot"]:
        y = y + 0.3 * librosa.effects.pitch_shift(y, sr=sr, n_steps=12)
    # —— 效果模式（把'方向'变成'听觉'）——
    if a["vinyl"]:
        y = _lowpass(y, 3200, sr)
        if a["vinyl"] == 2:                       # 磁带：逐段音高抖动
            n = len(y); k = max(n // 8, 1)
            for i in range(8):
                seg = y[i * k:(i + 1) * k]
                if len(seg) > 0.05 * sr:
                    y[i * k:(i + 1) * k] = librosa.effects.pitch_shift(
                        seg, sr=sr, n_steps=random.uniform(-0.35, 0.35))
        y = y + 0.012 * np.random.randn(len(y))   # 唱片底噪
    if a["space"]:
        y = y - 0.8 * _lowpass(y, 800, sr)        # 高通 800
        y = add_echo(y, sr, 1.6)
    if a["ghost"]:
        y = librosa.effects.pitch_shift(y, sr=sr, n_steps=-4)
        y = librosa.effects.time_stretch(y, rate=0.85)
        y = add_echo(y, sr, 1.8)
    if a["monster"]:
        y = librosa.effects.pitch_shift(y, sr=sr, n_steps=-7)
        y = librosa.effects.time_stretch(y, rate=0.70)
        y = add_echo(y, sr, 1.2)
    if a["eightbit"]:
        y = np.round(y / 0.125) * 0.125           # 量化成 8 级 → 芯片感
        y = _lowpass(y, 3200, sr)
    y = y * a["gain"]
    m = np.max(np.abs(y))
    if m > 0:
        y = y * (0.9 / m)
    f = int(0.015 * sr)
    y[:f] *= np.linspace(0, 1, f)
    y[-f:] *= np.linspace(1, 0, f)
    return y


def _lowpass(x, cutoff, sr):
    # 简单一阶低通（够做"电话感"演示）
    a = np.exp(-2 * np.pi * cutoff / sr)
    out = np.zeros_like(x)
    for i in range(1, len(x)):
        out[i] = (1 - a) * x[i] + a * out[i - 1]
    return out


# ---------- 两种模式的合成入口 ----------

def tts_mp3(text, voice_id):
    import edge_tts
    tmp = os.path.join(tempfile.gettempdir(), f"vws_{os.getpid()}.mp3")
    asyncio.run(_save_edge(text, voice_id, tmp))
    return tmp


async def _save_edge(text, voice_id, path):
    import edge_tts
    await edge_tts.Communicate(text, voice_id).save(path)


def run_audio(src, keywords, out):
    """素材模式：读 wav/mp3 → 关键词 → 处理"""
    y, sr = librosa.load(src, sr=SR, mono=True)
    a = parse_keywords(keywords)
    y2 = process(y, sr, a)
    sf.write(out, y2, sr)
    print(f"素材「{os.path.basename(src)}」（{len(y)/sr:.1f}s）→ 关键词「{keywords}」")
    print(f"实际旋钮：{describe(a)}")


def pick_voice(keywords, default):
    """在关键词里搜索性别词 → 音色"""
    for word, voice in GENDER_WORDS.items():
        if word in keywords:
            return voice
    return default


def run_text(text, keywords, out, voice="女声·晓晓"):
    """文字模式：edge-tts 生成 → 关键词 → 处理"""
    kw_voice = pick_voice(keywords, voice)
    y, sr = librosa.load(tts_mp3(text, VOICES[kw_voice]), sr=SR, mono=True)
    a = parse_keywords(keywords)
    y2 = process(y, sr, a)
    sf.write(out, y2, sr)
    print(f"文本「{text}」→ 关键词「{keywords}」→ 音色 {kw_voice}")
    print(f"实际旋钮：{describe(a)}")


# ---------- CLI ----------

def cli():
    ap = argparse.ArgumentParser(description="音频工坊：素材按关键词改 / 文字按关键词造")
    ap.add_argument("--list", action="store_true", help="打印关键词词典")
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--audio", help="素材文件（wav/mp3）")
    g.add_argument("--text", help="文字内容（自动 TTS）")
    ap.add_argument("--keywords", default="女生 柔媚 音调略高", help="大白话方向，例如：女生 柔媚 音调略高")
    ap.add_argument("--voice", default="女声·晓晓", choices=list(VOICES), help="文字模式的音色")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.list:
        list_keywords()
        sys.exit(0)

    out = args.out or (f"out_{args.audio and '素材' or '文字'}_{os.getpid()}.wav")
    if args.audio:
        run_audio(args.audio, args.keywords, out)
    elif args.text:
        run_text(args.text, args.keywords, out, args.voice)
    else:
        print("用法：\n  素材模式 py voice_workshop.py --audio 素材.wav --keywords \"女生 柔媚 音调略高\"\n"
              "  文字模式 py voice_workshop.py --text \"北京欢迎你\" --keywords \"少女 活泼 音调高 快\"")
        sys.exit(1)
    print(f"[OK] → {out}")


# ---------- GUI ----------

def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import threading

    try:
        import sounddevice as sd
    except ImportError:
        sd = None

    root = tk.Tk()
    root.title("音频工坊 voice_workshop")
    root.geometry("640x460")

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=8, pady=8)

    # ── 素材模式页 ──
    f1 = ttk.Frame(nb)
    nb.add(f1, text="① 素材模式：改音频")
    tk.Label(f1, text="音频文件：").grid(row=0, column=0, sticky="w", padx=10, pady=6)
    src_path = tk.StringVar()
    tk.Entry(f1, textvariable=src_path, width=46).grid(row=0, column=1, padx=4)
    tk.Button(f1, text="浏览…", command=lambda: src_path.set(
        filedialog.askopenfilename(filetypes=[("音频", "*.wav *.mp3")]) or src_path.get()
    )).grid(row=0, column=2)
    tk.Label(f1, text="我想改成（关键词）：").grid(row=1, column=0, sticky="w", padx=10, pady=6)
    kw1 = tk.StringVar(value="女生 柔媚 音调略高")
    tk.Entry(f1, textvariable=kw1, font=("Microsoft YaHei", 11), width=50).grid(
        row=1, column=1, columnspan=2, padx=4, sticky="w")

    # ── 文字模式页 ──
    f2 = ttk.Frame(nb)
    nb.add(f2, text="② 文字模式：直接造")
    tk.Label(f2, text="文字内容：").grid(row=0, column=0, sticky="w", padx=10, pady=6)
    text_var = tk.StringVar(value="北京欢迎你")
    tk.Entry(f2, textvariable=text_var, font=("Microsoft YaHei", 11), width=50).grid(
        row=0, column=1, padx=4, sticky="w")
    tk.Label(f2, text="我想做成（关键词）：").grid(row=1, column=0, sticky="w", padx=10, pady=6)
    kw2 = tk.StringVar(value="少女 活泼 音调高 快")
    tk.Entry(f2, textvariable=kw2, font=("Microsoft YaHei", 11), width=50).grid(
        row=1, column=1, padx=4, sticky="w")

    status = tk.Label(root, text="就绪。关键词示例：女生 柔媚 音调略高 / 男声 沉稳 混响 / 少女 可爱 快",
                      fg="#555", anchor="w", justify="left", wraplength=620)
    status.pack(fill="x", padx=10, pady=4)

    def do_audio():
        p = src_path.get().strip()
        if not p:
            messagebox.showwarning("提示", "请选择音频文件"); return
        out = f"out_素材_柔媚改_{os.getpid()}.wav"
        def work():
            try:
                run_audio(p, kw1.get(), out)
                msg = f"[OK] → {out}\n" + describe(parse_keywords(kw1.get()))
                if sd is not None:
                    y, _ = librosa.load(out, sr=SR, mono=True)
                    sd.play(y, SR); msg += "（正在播放）"
            except Exception as e:
                msg = f"失败：{e}"
            status.config(text=msg)
        threading.Thread(target=work, daemon=True).start()

    def do_text():
        t = text_var.get().strip()
        if not t:
            messagebox.showwarning("提示", "请输入文字"); return
        out = f"out_文字_{os.getpid()}.wav"
        def work():
            try:
                run_text(t, kw2.get(), out)
                msg = f"[OK] → {out}\n" + describe(parse_keywords(kw2.get()))
                if sd is not None:
                    y, _ = librosa.load(out, sr=SR, mono=True)
                    sd.play(y, SR); msg += "（正在播放）"
            except Exception as e:
                msg = f"失败：{e}（文字模式需联网调 edge-tts）"
            status.config(text=msg)
        threading.Thread(target=work, daemon=True).start()

    btns = tk.Frame(root)
    btns.pack(pady=6)
    tk.Button(btns, text="① 改这段音频", width=16, command=do_audio).pack(side="left", padx=8)
    tk.Button(btns, text="② 造出这段音频", width=16, command=do_text).pack(side="left", padx=8)
    tk.Label(root, text="关键词词典：性别(女生/少女/男声) 音调(略高/高/很低/低沉) 语速(快/慢/舒缓)\n"
                        "语气(柔媚/撒娇/活泼/可爱/沉稳/悲伤/兴奋/慵懒/温柔)\n"
                        "效果(电话/机器人/混响/复古/磁带/太空/幽灵/怪兽/8bit/响亮) —— 详见 py voice_workshop.py --list",
             fg="#888", font=("Microsoft YaHei", 8), justify="left").pack(side="bottom", pady=6)
    root.mainloop()


if __name__ == "__main__":
    if "--gui" in sys.argv:
        gui()
    else:
        cli()