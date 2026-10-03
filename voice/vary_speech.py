# -*- coding: utf-8 -*-
"""
同一句撒娇 → 十段"说法都不同"的版本
================================================
这是"数据增强"（data augmentation）思路的工程实现，业界训练 TTS/语音转换模型
时也用同样的扰动（变速/变调/节奏/能量）来扩充样本。

用法：
    py vary_speech.py                       # 自动用 edge-tts 生成一句撒娇样句再变十段
    py vary_speech.py 你的撒娇.wav          # 用自己的音频（建议 22050Hz 单声道，任意也行）
    py vary_speech.py x.wav --count 20 --seed 7

输出（vary_10/ 目录）：
    seg_01.wav ... seg_10.wav    每段独立
    all_10.wav                   十条连成一串
    params.csv                   每段参数表（Excel 可直接打开）

原理（对应教程第一部分旋钮表）：
    变速 = 音素时长旋钮；变调 = F0 旋钮；句尾上扬 = F0(t) 曲线；回声 = 空间感。
"""
import argparse
import asyncio
import csv
import os
import random
import sys

import numpy as np
import soundfile as sf
import librosa

SR = 22050


# ---------- 五类扰动（每个都可单独开关/改范围） ----------

def vary_one(y, sr, seg):
    """把一段音频按 seg 配方做变速/变调/句尾上扬/包络/回声"""
    # 1) 变速（音高不变）
    y = librosa.effects.time_stretch(y, rate=seg["speed"])
    # 2) 全局变调（时长不变）
    y = librosa.effects.pitch_shift(y, sr=sr, n_steps=seg["pitch"])
    # 3) 句尾上扬：后 35% 再升几个半音 → "嘛～"的撒娇尾音
    if seg["tail_lift"]:
        n = len(y)
        k = int(n * 0.35)
        y[-k:] = librosa.effects.pitch_shift(y[-k:], sr=sr, n_steps=seg["tail_lift"])
    # 4) 音量包络：整体增益 + 可选"收尾"（轻语收住/拖走）
    env = np.ones(len(y))
    if seg["fade_out"]:
        m = int(len(y) * seg["fade_out"])
        env[-m:] *= np.linspace(1, 0.15, m)
    y = y * env * seg["gain"]
    # 5) 微回声（空间感微差）
    if seg["echo"]:
        y = add_echo(y, sr)
    # 首尾 15ms 淡入淡出防爆音
    f = int(0.015 * sr)
    y[:f] *= np.linspace(0, 1, f)
    y[-f:] *= np.linspace(1, 0, f)
    return y


def add_echo(x, sr):
    out = x.copy()
    for d, g in ((0.06, 0.12), (0.11, 0.08), (0.19, 0.05)):
        n = int(d * sr)
        if n < len(x):
            out[n:] += g * x[:-n]
    m = np.max(np.abs(out))
    return out * (0.9 / m) if m > 0 else out


def make_seg(rng, idx):
    """随机生成一段'配方'：每一段的数值都不同"""
    return dict(
        idx=idx,
        speed=round(rng.uniform(0.88, 1.12), 3),     # 变速倍率（0.88=拖一点，1.12=快一点）
        pitch=round(rng.uniform(-1.5, 2.5), 2),      # 变调（半音，偏正 = 更嗲）
        tail_lift=(round(rng.uniform(1.0, 3.0), 2)
                   if rng.random() < 0.7 else 0.0),  # 句尾再上扬（半音），70% 概率
        lead=round(rng.uniform(0.05, 0.70), 2),      # 本段前导静音（秒）
        gap=round(rng.uniform(0.15, 0.55), 2),       # 本段后间隔（秒）
        fade_out=(round(rng.uniform(0.10, 0.25), 2)
                  if rng.random() < 0.6 else 0.0),   # 结尾收势比例，60% 概率
        gain=round(rng.uniform(0.75, 1.00), 2),      # 响度
        echo=1 if rng.random() < 0.4 else 0,         # 微回声 40% 概率
    )


# ---------- 入口 ----------

def build(seg):
    return "|".join(str(seg[k]) for k in
                    ("idx", "speed", "pitch", "tail_lift", "lead", "gap", "fade_out", "gain", "echo"))


def main():
    ap = argparse.ArgumentParser(description="撒娇音频 → 十段变化版")
    ap.add_argument("wav", nargs="?", default=None)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="vary_10")
    args = ap.parse_args()

    rng = random.Random(args.seed)

    # 来源：用户文件，或 edge-tts 生成样句
    if args.wav:
        src = args.wav
    else:
        src = os.path.join(args.out, "sample_quarrel.mp3")
        os.makedirs(args.out, exist_ok=True)
        print("[1/3] 用 edge-tts 生成撒娇样句（需要网络）...")

        async def _gen():
            import edge_tts
            tts = edge_tts.Communicate(
                "人家想要你陪我嘛～好不好嘛～就陪我一会儿嘛。", "zh-CN-XiaoxiaoNeural")
            await tts.save(src)

        try:
            asyncio.run(_gen())
        except Exception as e:
            print(f"[失败] edge-tts 需要网络：{e}")
            print("       用法：py vary_speech.py 你的撒娇.wav")
            sys.exit(1)

    y, sr = librosa.load(src, sr=SR, mono=True)

    segs = [make_seg(rng, i) for i in range(1, args.count + 1)]
    os.makedirs(args.out, exist_ok=True)

    print(f"[2/3] 生成 {args.count} 段变化（seed={args.seed}）...")
    timeline = []
    for s in segs:
        seg_audio = vary_one(y, sr, s)
        lead = int(s["lead"] * sr) if s["idx"] > 1 else int(0.04 * sr)
        timeline.append(np.zeros(lead))
        timeline.append(seg_audio)
        timeline.append(np.zeros(int(s["gap"] * sr)))
        sf.write(os.path.join(args.out, f"seg_{s['idx']:02d}.wav"), seg_audio, sr)

    sf.write(os.path.join(args.out, f"all_{args.count}.wav"),
             np.concatenate(timeline), sr)

    with open(os.path.join(args.out, "params.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(segs[0].keys()))
        w.writeheader()
        w.writerows(segs)

    print(f"[3/3] 完成：{args.out}/seg_01..{args.count:02d}.wav + all_{args.count}.wav + params.csv")
    print()
    print("每段配方（语速/变调/尾音上扬/前导/间隔/收尾/响度/回声）：")
    print(f"{'段':<3}{'变速':<7}{'变调半音':<9}{'尾音+':<7}{'前导s':<6}{'间隔s':<6}{'收尾':<6}{'响度':<6}回声")
    for s in segs:
        sgn = f"+{s['tail_lift']:.1f}" if s["tail_lift"] else "-"
        print(f"{s['idx']:<4}{s['speed']:<8}{s['pitch']:<9.1f}{sgn:<8}"
              f"{s['lead']:<7}{s['gap']:<7}{s['fade_out']:<8.2f}{s['gain']:<7}{s['echo']}")


if __name__ == "__main__":
    main()