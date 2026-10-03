# -*- coding: utf-8 -*-
"""
生成《人声合成与播放全流程》配套教学插图（figs/ 目录，共 9 张）
运行：py make_figures.py
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

SR = 22050
os.makedirs("figs", exist_ok=True)


def box(ax, x, y, w, h, text, fc="#eef4f9", ec="#0e3a5d", fs=11):
    b = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02",
                       fc=fc, ec=ec, lw=1.4)
    ax.add_patch(b)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, color="#1a1a1a")


def arrow(ax, x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color="#d35400", lw=2))


# ──────────────────────────────────────────────────────────────────────
# 图1：Source–Filter 信号链框图
# ──────────────────────────────────────────────────────────────────────
def fig_source_filter():
    fig, ax = plt.subplots(figsize=(11, 3.4), dpi=150)
    ax.set_xlim(0, 11); ax.set_ylim(0, 3.4); ax.axis("off")
    box(ax, 0.2, 1.2, 1.5, 1.1, "肺\n(气流动力)")
    box(ax, 2.2, 1.2, 1.9, 1.1, "声门源 E(f)\n(声带/湍流)", fc="#fdebd0")
    box(ax, 4.6, 1.2, 1.9, 1.1, "声道 V(f)\n(共振峰)")
    box(ax, 7.0, 1.2, 1.9, 1.1, "唇辐射 R(f)\n(+6 dB/oct)", fc="#fdebd0")
    box(ax, 9.4, 1.2, 1.4, 1.1, "耳朵")
    for p in (1.7, 4.1, 6.5, 8.9):
        arrow(ax, p, 1.75, p + 0.5, 1.75)
    ax.text(5.5, 0.35, "频域：S(f) = E(f) × V(f) × R(f)     时域：s(t) = g * v * r (卷积)",
            ha="center", fontsize=12, color="#0e3a5d")
    ax.text(5.5, 0.02, "源管'音高与清浊'，声道管'音色与元音'，辐射管'高频亮度'——三者独立可调",
            ha="center", fontsize=9, color="#7f8c8d")
    fig.savefig("figs/fig_source_filter.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ──────────────────────────────────────────────────────────────────────
# 图2：谐波梳 × 声道包络 = 语音频谱（灵魂图）
# ──────────────────────────────────────────────────────────────────────
def fig_multiply():
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6), dpi=150)
    F0 = 120.0
    k = np.arange(1, 31)
    freqs = k * F0
    comb = 1.0 / k ** 2                     # 声门 -12dB/oct 包络的谱线幅度
    comb /= comb.max()
    f = np.linspace(0, 4000, 4000)

    def env(f, forms, bw):
        v = np.zeros_like(f)
        for F, b in zip(forms, bw):
            v += np.exp(-((f - F) / b) ** 2)
        return v

    V = env(f, (730, 1090, 2440), (130, 160, 200))
    S = comb * np.interp(freqs, f, V)

    for ax, title in zip(axes, ("E(f)  声源：谐波梳", "V(f)  声道：共振峰包络", "S(f)  语音 = 梳 × 包络")):
        ax.spines["top"].set_visible(False)
        ax.set_xlim(0, 4000); ax.set_ylim(0, 1.12)
        ax.set_xlabel("频率 (Hz)", fontsize=9)
        ax.set_title(title, fontsize=11, color="#0e3a5d")
        ax.tick_params(labelsize=8)
        ax.grid(alpha=0.25, lw=0.5)

    axes[0].vlines(freqs, 0, comb, color="#c0392b", lw=1.1)
    axes[0].text(300, 1.05, "间隔 F0=120Hz", fontsize=9, color="#7f8c8d")

    axes[1].plot(f, V, color="#1f618d", lw=2)
    for F, lb in ((730, "F1=730"), (1090, "F2=1090"), (2440, "F3=2440")):
        axes[1].axvline(F, color="#5b9bd5", ls="--", lw=0.9)
        axes[1].text(F, 1.05, lb, ha="center", fontsize=8, color="#5b9bd5")

    axes[2].vlines(freqs, 0, S, color="#27ae60", lw=1.1)
    axes[2].plot(f, np.interp(np.arange(0, 4000), freqs, S) * 0 + 0, color="#27ae60")
    axes[2].text(300, 1.05, "峰处的谱线被'点亮'", fontsize=9, color="#7f8c8d")

    axes[0].set_ylabel("相对幅度", fontsize=9)
    fig.suptitle("一次完整的'乘法'：谐波落在共振峰上就被点亮（F0=120 男声 /a/）",
                 fontsize=12, color="#0e3a5d")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig("figs/fig_multiply.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ──────────────────────────────────────────────────────────────────────
# 图3：谐振器频率响应：带宽 B 的含义
# ──────────────────────────────────────────────────────────────────────
def fig_bandwidth():
    f = np.linspace(100, 1600, 2000)

    def resp(F, B, freqs, sr=SR):
        r = np.exp(-np.pi * B / sr)
        th = 2 * np.pi * F / sr
        z = np.exp(1j * 2 * np.pi * freqs / sr)
        return 1 / np.abs(1 - 2 * r * np.cos(th) * z ** -1 + r * r * z ** -2)

    fig, ax = plt.subplots(figsize=(9, 3.6), dpi=150)
    for B, c, lb in ((60, "#1f618d", "B=60Hz（峰尖：元音纯净）"),
                     (200, "#c0392b", "B=200Hz（峰平：含混）")):
        h = resp(730, B, f)
        ax.plot(f, h / h.max(), color=c, lw=2, label=lb)
    ax.axhline(0.707, color="#7f8c8d", ls=":", lw=1)
    ax.text(1300, 0.73, "−3dB 参考线", fontsize=8, color="#7f8c8d")
    ax.annotate("带宽越窄 = 峰越尖\n= 元音特征越强", xy=(730, 1.0),
                xytext=(1000, 0.9), fontsize=9, color="#1f618d",
                arrowprops=dict(arrowstyle="->", color="#1f618d"))
    ax.set_xlabel("频率 (Hz)", fontsize=10)
    ax.set_ylabel("归一化增益", fontsize=10)
    ax.set_title("同一个谐振器（F=730Hz，/a/ 的 F1），不同带宽 B 的形状",
                 fontsize=11, color="#0e3a5d")
    ax.grid(alpha=0.25, lw=0.5)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig("figs/fig_bandwidth.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ──────────────────────────────────────────────────────────────────────
# 图4：元音四边形（F1–F2 平面）
# ──────────────────────────────────────────────────────────────────────
def fig_vowel_quad():
    vowels = {"/i/ 衣": (270, 2290), "/e/ 诶": (530, 1840), "/a/ 啊": (730, 1090),
              "/o/ 哦": (570, 840), "/u/ 呜": (300, 870)}
    fig, ax = plt.subplots(figsize=(7, 6), dpi=150)
    for name, (f1, f2) in vowels.items():
        ax.scatter(f1, f2, s=160, color="#c0392b", zorder=3)
        ax.annotate(name, (f1, f2), textcoords="offset points",
                    xytext=(14, 6), fontsize=12, color="#1a1a1a")
    ax.set_xlabel("F1 (Hz) —— 嘴张得越开，F1 越高", fontsize=11)
    ax.set_ylabel("F2 (Hz) —— 舌头越靠前，F2 越高", fontsize=11)
    ax.set_title("元音四边形：元音 = F1/F2 坐标", fontsize=13, color="#0e3a5d")
    ax.set_xlim(150, 950); ax.set_ylim(500, 2700)
    ax.invert_yaxis()
    ax.grid(alpha=0.3, lw=0.6)
    ax.text(820, 2600, "舌头在口腔里滑动，\n就是在这张图上移动", fontsize=9,
            color="#7f8c8d")
    fig.tight_layout()
    fig.savefig("figs/fig_vowel_quad.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ──────────────────────────────────────────────────────────────────────
# 图5：z 平面极点（/a/ 的三对极点）
# ──────────────────────────────────────────────────────────────────────
def fig_poles():
    specs = ((0.9915, 0.2080, "F1=730Hz"), (0.9873, 0.3106, "F2=1090Hz"),
             (0.9831, 0.6953, "F3=2440Hz"))
    fig, ax = plt.subplots(figsize=(6.2, 6.2), dpi=150)
    ax.add_patch(Circle((0, 0), 1, fill=False, ec="#7f8c8d", lw=1.5))
    ax.text(1.05, -0.08, "单位圆 |z|=1", fontsize=9, color="#7f8c8d")
    for r, th, lb in specs:
        for s in (1, -1):
            z = r * np.exp(1j * s * th)
            ax.scatter(z.real, z.imag, color="#1f618d", s=70, zorder=3)
        ax.annotate(lb, (r * np.cos(th), r * np.sin(th) + 0.13),
                    fontsize=10, color="#1f618d",
                    arrowprops=dict(arrowstyle="-", color="#1f618d", lw=0.8))
    ax.axhline(0, color="#999", lw=0.8)
    ax.axvline(0, color="#999", lw=0.8)
    ax.set_xlim(-1.35, 1.35); ax.set_ylim(-1.35, 1.35)
    ax.set_aspect("equal")
    ax.set_title("/a/ 的三对极点（fs=22050）\n角度→频率，半径→带宽",
                 fontsize=12, color="#0e3a5d")
    ax.text(-1.3, -1.28, "F = θ·fs/2π     B = −(fs/π)·ln r", fontsize=9,
            color="#7f8c8d")
    fig.tight_layout()
    fig.savefig("figs/fig_poles.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ──────────────────────────────────────────────────────────────────────
# 图6：合成"啊"的声谱图（共振峰亮带）
# ──────────────────────────────────────────────────────────────────────
def fig_spectrogram_a():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from synth_demo import vowel
    from scipy.signal import stft

    audio = vowel('a', 0.7, 120)          # 第二部分 2.3 的合成函数
    f, t, Z = stft(audio, fs=SR, nperseg=1024, noverlap=768)
    S = 20 * np.log10(np.abs(Z) + 1e-9)

    fig, ax = plt.subplots(figsize=(11, 4.2), dpi=150)
    im = ax.imshow(S, origin="lower", aspect="auto", cmap="magma",
                   extent=[t[0], t[-1], f[0], f[-1]], vmin=-100, vmax=0)
    for F, lb in ((730, "F1"), (1090, "F2"), (2440, "F3")):
        ax.axhline(F, color="#55ffd5", ls="--", lw=0.9)
        ax.text(0.63, F + 90, lb, color="#55ffd5", fontsize=9)
    ax.set_xlabel("时间 (s)", fontsize=10)
    ax.set_ylabel("频率 (Hz)", fontsize=10)
    ax.set_ylim(0, 5000)
    ax.set_title("用代码合成的'啊'——三条横向亮带就是共振峰 F1/F2/F3",
                 fontsize=12, color="#0e3a5d")
    fig.colorbar(im, ax=ax, label="dB", shrink=0.9)
    fig.tight_layout()
    fig.savefig("figs/fig_spectrogram_a.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ──────────────────────────────────────────────────────────────────────
# 图7：同一个"啊"：男/女/婴儿（κ 缩放共振峰）
# ──────────────────────────────────────────────────────────────────────
def fig_voice_compare():
    f = np.linspace(0, 5200, 5200)

    def env(f, kappa):
        v = np.zeros_like(f)
        for F, b in zip((730, 1090, 2440), (130, 160, 200)):
            Fk, bk = F * kappa, b * kappa
            v += np.exp(-((f - Fk) / bk) ** 2)
        return v

    fig, ax = plt.subplots(figsize=(10, 4), dpi=150)
    styles = ((1.00, "#1f618d", "成年男性 κ=1.0：F=730/1090/2440"),
              (1.15, "#d35400", "成年女性 κ=1.15：F=840/1254/2806"),
              (1.80, "#c0392b", "婴儿 κ=1.8：F=1314/1962/4392"))
    for k, c, lb in styles:
        ax.plot(f, env(f, k), color=c, lw=2, label=lb)
    ax.set_xlim(0, 5200)
    ax.set_xlabel("频率 (Hz)", fontsize=10)
    ax.set_ylabel("声道频率响应（示意）", fontsize=10)
    ax.set_title("同一个'啊'，不同体型：κ 把所有共振峰整体平移",
                 fontsize=12, color="#0e3a5d")
    ax.grid(alpha=0.25, lw=0.5)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig("figs/fig_voice_compare.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ──────────────────────────────────────────────────────────────────────
# 图8：播放链路框图（+ DAC 阶梯电压示意）
# ──────────────────────────────────────────────────────────────────────
def fig_playback():
    fig = plt.figure(figsize=(12, 4.2), dpi=150)
    ax = fig.add_axes([0.0, 0.35, 1.0, 0.6])
    ax.set_xlim(0, 12); ax.set_ylim(0, 2.6); ax.axis("off")
    items = [("wav/mp3\n文件", "#eef4f9"), ("解码器\n→PCM数组", "#fdebd0"),
             ("DAC\n数字→电压", "#fdebd0"), ("重建低通\n(抹镜像)", "#eef4f9"),
             ("功放", "#eef4f9"), ("扬声器\n推空气", "#d5f5e3"), ("耳朵", "#eef4f9")]
    x = 0.15
    for text, fc in items:
        box(ax, x, 0.8, 1.55, 1.1, text, fc=fc)
        if x < 9.6:
            arrow(ax, x + 1.55, 1.35, x + 1.9, 1.35)
        x += 1.7
    ax.text(6, 0.32, "软件侧（文件 → 数字数组）", fontsize=10, color="#1f618d", ha="center")
    ax.text(6, 0.05, "硬件侧（数组 → 电压 → 振动 → 声波）", fontsize=10, color="#d35400", ha="center")

    ax2 = fig.add_axes([0.0, -0.02, 1.0, 0.45])
    ax2.axis("off")
    n = 16
    t = np.arange(n) / 16 * 2 * np.pi
    tt = np.linspace(0, 2 * np.pi, 400)
    ax2.plot(tt, np.sin(tt), color="#27ae60", lw=1.6, label="重建后的平滑波形")
    ax2.step(t, np.sin(t), where="post", color="#c0392b", lw=1.3, label="DAC 输出的阶梯电压（零阶保持）")
    ax2.set_title("DAC 的'零阶保持'阶梯 + 重建滤波（截止 sr/2）→ 平滑波形",
                  fontsize=10, color="#0e3a5d", pad=8)
    ax2.legend(fontsize=8, loc="upper right")
    fig.savefig("figs/fig_playback.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ──────────────────────────────────────────────────────────────────────
# 图9：现代 TTS 流水线（第七部分）
# ──────────────────────────────────────────────────────────────────────
def fig_tts_pipeline():
    fig, ax = plt.subplots(figsize=(12.5, 3.8), dpi=150)
    ax.set_xlim(0, 12.5); ax.set_ylim(-1.6, 3.4); ax.axis("off")
    row1 = [("文本\n'我喜欢你'", "#eef4f9"), ("归一化\n(数字/符号)", "#eef4f9"),
            ("G2P 拼音\n+多音字消歧", "#fdebd0"), ("韵律预测\n(停顿/时长)", "#fdebd0"),
            ("声学模型\nmel谱+F0", "#d5f5e3"), ("声码器\nHiFi-GAN", "#d5f5e3"),
            ("波形→文件", "#eef4f9")]
    x = 0.2
    for text, fc in row1:
        box(ax, x, 1.0, 1.6, 1.25, text, fc=fc)
        if x < 10.7:
            arrow(ax, x + 1.6, 1.62, x + 1.95, 1.62)
        x += 1.75
    ax.text(6.25, 0.15, "③ 声码器 = 第一部分'脉冲→谐振器'的神经网络版",
            ha="center", fontsize=9.5, color="#7f8c8d")

    # 撒娇路线（参考音频）
    box(ax, 0.3, -1.5, 2.7, 1.0, "参考音频 5s\n(撒娇语气)", fc="#fdebd0", fs=9.5)
    ax.annotate("", xy=(5.9, 1.0), xytext=(3.0, -1.0),
                arrowprops=dict(arrowstyle="-|>", color="#d35400", lw=1.6,
                                connectionstyle="arc3,rad=-0.25"))
    ax.text(3.1, 0.55, "风格向量 + 音色向量\n（style embedding）", fontsize=8.5,
            color="#d35400")
    ax.text(4.7, -0.2, "想要撒娇：录一段撒娇的参考音频就行", fontsize=10,
            color="#0e3a5d")
    ax.text(0.3, 2.95, "现代 TTS：'我喜欢你' → 声音（第七部分）", fontsize=13,
            color="#0e3a5d")
    fig.savefig("figs/fig_tts_pipeline.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    fig_source_filter()
    fig_multiply()
    fig_bandwidth()
    fig_vowel_quad()
    fig_poles()
    fig_spectrogram_a()
    fig_voice_compare()
    fig_playback()
    fig_tts_pipeline()
    print("9 张插图已生成到 figs/ 目录")