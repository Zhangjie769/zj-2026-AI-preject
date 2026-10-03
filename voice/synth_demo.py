# -*- coding: utf-8 -*-
"""
声音合成 demo 工厂
==================
把《人声合成与播放全流程》第一/六部分的配方变成能听的声音。

用法：
    py synth_demo.py                 全部合成到 demo_wavs/ 目录
    py synth_demo.py kick wind       只合成指定的几个
    py synth_demo.py --play kick    合成并直接播放（需要 pip install sounddevice）

每个函数 = 一行配方台词 + 一句业界出处。
"""
import os
import sys
import numpy as np
import soundfile as sf

# Windows 控制台默认 GBK，打印含 τₖ 等 Unicode 下标会崩；容错转 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SR = 22050  # 本工厂统一采样率（谐波上限 11kHz，够全部 demo 用）

try:
    import sounddevice as sd
except ImportError:
    sd = None


# ----------------------------------------------------------------------
# 基础工具：教科书公式的直接翻译（详见教程 1.6.2 / 6.1）
# ----------------------------------------------------------------------

def onepole_lowpass(x, cutoff, sr=SR):
    """一阶低通（−6dB/oct）"""
    a = np.exp(-2 * np.pi * cutoff / sr)
    y = np.zeros_like(x)
    for i in range(1, len(x)):
        y[i] = (1 - a) * x[i] + a * y[i - 1]
    return y


def resonator(x, F, Bw, sr=SR):
    """二阶谐振器 = 一个共振峰：r=e^(−πB/fs), θ=2πF/fs"""
    r = np.exp(-np.pi * Bw / sr)
    th = 2 * np.pi * F / sr
    y = np.zeros_like(x)
    for n in range(2, len(x)):
        y[n] = x[n] + 2 * r * np.cos(th) * y[n - 1] - r * r * y[n - 2]
    return y


def resonator_glide(x, F_curve, Bw, sr=SR):
    """共振峰随时间滑动（每个采样点一个 θ）"""
    y = np.zeros_like(x)
    for n in range(2, len(x)):
        r = np.exp(-np.pi * Bw / sr)
        th = 2 * np.pi * F_curve[n] / sr
        y[n] = x[n] + 2 * r * np.cos(th) * y[n - 1] - r * r * y[n - 2]
    return y


def glottal_source(dur, f0_curve, sr=SR):
    """声门脉冲串（按 F0 曲线）+ 两级低通 ≈ −12dB/oct 滚降"""
    n = int(dur * sr)
    phase = np.cumsum(f0_curve[:n]) / sr
    imp = np.zeros(n)
    imp[1:] = np.floor(phase[1:]) > np.floor(phase[:-1])
    src = onepole_lowpass(onepole_lowpass(imp, 4 * np.mean(f0_curve), sr),
                          4 * np.mean(f0_curve), sr)
    return src / np.max(np.abs(src) + 1e-9)


def adsr(n, a, d, s_level, r, sr=SR):
    """ADSR 包络（第 7 章主教程）"""
    na, nd, nr = int(a * sr), int(d * sr), int(r * sr)
    ns = max(n - na - nd - nr, 0)
    return np.concatenate([np.linspace(0, 1, na), np.linspace(1, s_level, nd),
                           np.full(ns, s_level), np.linspace(s_level, 0, nr)])[:n]


def exp_env(n, tau, sr=SR):
    """指数衰减包络 e^(−t/τ)"""
    return np.exp(-np.arange(n) / sr / tau)


def t_axis(dur, sr=SR):
    return np.arange(int(dur * sr)) / sr


def fade(x, edge=0.05, sr=SR):
    nf = int(edge * sr)
    if len(x) > 2 * nf:
        x[:nf] *= np.linspace(0, 1, nf)
        x[-nf:] *= np.linspace(1, 0, nf)
    return x


def normalize(x, peak=0.9):
    m = np.max(np.abs(x))
    return x * peak / m if m > 0 else x


# ----------------------------------------------------------------------
# 人声家族（第一部分配方）
# ----------------------------------------------------------------------

VOWELS = {'a': (730, 1090, 2440), 'i': (270, 2290, 3010), 'u': (300, 870, 2240),
          'e': (530, 1840, 2480), 'o': (570, 840, 2410)}


def vowel(name, dur=0.7, f0=120, sr=SR):
    """人声元音：声门源 × 共振峰配方（1.6.3 配方表）"""
    fs = VOWELS[name]
    src = glottal_source(dur, np.full(int(dur * sr), float(f0)), sr)
    y = src
    for F, Bw in zip(fs, (60, 90, 120)):
        y = resonator(y, F, Bw, sr)
    y *= adsr(len(y), 0.03, 0.1, 0.8, 0.2, sr)
    return y


def baby_a(dur=0.8, sr=SR):
    """婴儿'啊'：κ=1.8（F×1.8）、F0=360、带宽×1.5、气声 β=0.15（1.12 配方表）"""
    fs = np.array(VOWELS['a']) * 1.8          # 1314 / 1962 / 4392
    B = np.array((60, 90, 120)) * 1.5
    n = int(dur * sr)
    t = t_axis(dur, sr)
    src = glottal_source(dur, np.full(n, 360.0), sr)
    y = src
    for F, b in zip(fs, B):
        y = resonator(y, F, b, sr)
    y = y + 0.15 * np.random.randn(n) * (0.5 + 0.5 * np.sin(2 * np.pi * 180 * t))  # 气声
    y *= adsr(len(y), 0.02, 0.1, 0.8, 0.15, sr)
    return y


def robot_a(dur=0.8, sr=SR):
    """机器人：方波源 + 人声/a/共振峰 + jitter=0、vibrato=0、F0 平直（6.5）"""
    t = t_axis(dur, sr)
    src = np.sign(np.sin(2 * np.pi * 120 * t))   # 方波：奇次谐波 1/n
    y = src
    for F, Bw in zip(VOWELS['a'], (60, 90, 120)):
        y = resonator(y, F, Bw, sr)
    y *= adsr(len(y), 0.03, 0.05, 0.9, 0.15, sr)
    return y


# ----------------------------------------------------------------------
# 打击乐（6.3：瞬态 + 下滑 + 急衰）
# ----------------------------------------------------------------------

def kick(dur=0.4, sr=SR):
    """底鼓：正弦 100→50Hz 指数下滑，τ=0.2s"""
    t = t_axis(dur, sr)
    f = 100 * (50 / 100) ** (t / dur)
    return np.sin(2 * np.pi * np.cumsum(f) / sr) * exp_env(len(t), 0.2, sr)


def snare(dur=0.25, sr=SR):
    """军鼓：白噪声高通1.5k + 200Hz 谐振，τ=0.07s"""
    t = t_axis(dur, sr)
    n = len(t)
    noise = np.random.randn(n)
    hp = noise - onepole_lowpass(noise, 1500, sr)
    body = resonator(noise, 200, 150, sr)
    return (hp * 0.8 + body * 0.3) * exp_env(n, 0.07, sr)


def cymbal(dur=1.8, sr=SR):
    """镲：白噪声高通6k + τ=1.5s 金属衰减"""
    t = t_axis(dur, sr)
    noise = np.random.randn(len(t))
    hp = noise - onepole_lowpass(noise, 6000, sr)
    return hp * exp_env(len(t), 1.5, sr)


def woodblock(dur=0.12, sr=SR):
    """木鱼：宽带敲击激发 + 谐振器 900→300Hz 急滑，τ=30ms"""
    n = int(dur * sr)
    t = t_axis(dur, sr)
    x = np.random.randn(n)
    F = np.linspace(900, 300, n)
    return resonator_glide(x, F, 90, sr) * exp_env(n, 0.03, sr)


def water_drop(dur=0.15, sr=SR):
    """水滴：谐振急滑 800→100Hz + τ=50ms（Q 高才'滴'）"""
    t = t_axis(dur, sr)
    f = 800 * (100 / 800) ** (t / dur)
    return np.sin(2 * np.pi * np.cumsum(f) / sr) * exp_env(len(t), 0.05, sr)


# ----------------------------------------------------------------------
# 乐器（6.2）
# ----------------------------------------------------------------------

def piano(f0=261.63, dur=3.0, sr=SR):
    """钢琴 C4：谐波独立衰减 s=ΣAₖe^(−t/τₖ)sin(2πkF₀t)，τₖ=τ₁/k"""
    t = t_axis(dur, sr)
    y = np.zeros(len(t))
    for k in range(1, 6):
        y += (1.0 / k ** 1.5) * np.sin(2 * np.pi * k * f0 * t) * np.exp(-t / (2.0 / k))
    y *= np.minimum(1, t / 0.005)   # 琴槌：5ms 起音
    return y


def karplus(freq, dur=1.5, sr=SR, decay=0.996):
    """Karplus–Strong 拨弦（6.2 业界名场面）：N=sr/F₀ 的延迟环 + 低通"""
    N = max(int(sr / freq), 2)
    buf = np.random.uniform(-1, 1, N)
    out = np.zeros(int(dur * sr))
    idx = 0
    for i in range(len(out)):
        out[i] = buf[idx]
        buf[idx] = decay * 0.5 * (buf[idx] + buf[(idx + 1) % N])
        idx = (idx + 1) % N
    return out


def guitar(sr=SR):
    """拨弦双音：E2(82.4Hz) + A2(110Hz)——N≈267 的延迟环"""
    return karplus(82.4, 1.2, sr) * 0.8 + karplus(110.0, 1.2, sr) * 0.6


def violin(dur=2.0, f0=440, sr=SR):
    """锯音'小提琴底料'：锯齿波(全谐波1/n) + vibrato 6Hz（6.2：F₀(t)=F₀+5·sin(2π·6t)）"""
    t = t_axis(dur, sr)
    f = f0 + 5 * np.sin(2 * np.pi * 6 * t)          # 揉弦
    phase = 2 * np.pi * np.cumsum(f) / sr
    saw = 2 * (phase % 1) - 1
    y = resonator_glide(saw, np.full(len(t), 2600.0), 400, sr)   # 一个共振峰塑形
    y *= adsr(len(y), 0.15, 0.3, 0.85, 0.4, sr)
    return y


# ----------------------------------------------------------------------
# 自然界（6.4：噪声 + 滤波 + 慢调制）
# ----------------------------------------------------------------------

def wind(dur=3.5, sr=SR):
    """风声：白噪→低通800Hz + 0.15Hz 幅度 LFO（'呼——呼——'）"""
    t = t_axis(dur, sr)
    noise = np.random.randn(len(t))
    lp = onepole_lowpass(noise, 800, sr)
    return fade(lp * (0.6 + 0.4 * np.sin(2 * np.pi * 0.15 * t)), 0.8, sr)


def rain(dur=2.5, sr=SR):
    """雨声：白噪高通4k + 随机雨点微脉冲"""
    t = t_axis(dur, sr)
    n = len(t)
    noise = np.random.randn(n)
    hp = noise - onepole_lowpass(noise, 4000, sr)
    ticks = (np.random.rand(n) < 0.015) * np.random.randn(n) * 3
    return hp * 0.7 + ticks


def thunder(dur=3.0, sr=SR):
    """雷声：棕噪（积分）=低频重  + 低通200Hz + 初爆指数衰减"""
    t = t_axis(dur, sr)
    brown = np.cumsum(np.random.randn(len(t)))
    brown /= np.max(np.abs(brown))
    return onepole_lowpass(brown, 200, sr) * np.exp(-t / 0.7)


def heartbeat(dur=3.2, sr=SR):
    """心跳 75bpm：'咚—哒'（60Hz 与 45Hz 低通脉冲，间隔0.12s）"""
    def thump(f, tau):
        t = t_axis(0.35, sr)
        return np.sin(2 * np.pi * f * t) * np.exp(-t / tau)
    beat = np.concatenate([thump(60, 0.07), np.zeros(int(0.12 * sr)), thump(45, 0.1)])
    reps = int(np.ceil(dur / (len(beat) / sr)))
    return np.tile(beat, reps)[: int(dur * sr)]


def bird(dur=0.9, sr=SR):
    """鸟鸣：鸣管≈双声源-滤模型！F0 快速滑音 + 两个高频共振峰（6.4）"""
    n = int(dur * sr)
    t = t_axis(dur, sr)
    f0 = 2500 + 1200 * np.sin(2 * np.pi * 5 * t)       # 婉转滑音
    src = glottal_source(dur, f0, sr)
    y = resonator(resonator(src, 3600, 500, sr), 4800, 700, sr)
    y *= adsr(len(y), 0.02, 0.05, 0.8, 0.12, sr)
    return y


def mosquito(dur=1.2, sr=SR):
    """蚊子：480Hz 正弦 + 38Hz 幅度调制（翅膀拍打）"""
    t = t_axis(dur, sr)
    y = np.sin(2 * np.pi * 480 * t) * (0.55 + 0.45 * np.sin(2 * np.pi * 38 * t))
    return fade(y, 0.05, sr)


# ----------------------------------------------------------------------
# 机械与科幻（6.5）
# ----------------------------------------------------------------------

def engine(dur=2.5, sr=SR):
    """引擎怠速：20Hz 脉冲串 + 低通500Hz = '突突'轰鸣"""
    f0 = np.full(int(dur * sr), 20.0)
    src = glottal_source(dur, f0, sr)
    return onepole_lowpass(src, 500, sr)


def siren_eu(dur=3.0, sr=SR):
    """欧式警报：正弦 650±150Hz 扫频，周期1s"""
    t = t_axis(dur, sr)
    f = 650 + 150 * np.sin(2 * np.pi * 1.0 * t)
    return np.sin(2 * np.pi * np.cumsum(f) / sr)


def siren_us(sr=SR):
    """美式警笛：600Hz 0.5s ↔ 720Hz 0.5s 交替"""
    segs = []
    for _ in range(3):
        t1, t2 = t_axis(0.5, sr), t_axis(0.5, sr)
        segs.append(np.sin(2 * np.pi * 600 * t1))
        segs.append(np.sin(2 * np.pi * 720 * t2))
    return np.concatenate(segs)


def busy_tone(sr=SR):
    """电话忙音：480+620Hz 双音，响0.5s/停0.5s（全世界同款参数）"""
    segs = []
    for i in range(4):
        if i % 2 == 0:
            t = t_axis(0.5, sr)
            segs.append(np.sin(2 * np.pi * 480 * t) + np.sin(2 * np.pi * 620 * t))
        else:
            segs.append(np.zeros(int(0.5 * sr)))
    return np.concatenate(segs)


def laser(dur=0.35, sr=SR):
    """激光枪：锯齿波 1200→150Hz 指数急滑（t=0.15s 时 ≈424Hz）"""
    t = t_axis(dur, sr)
    f = 1200 * (150 / 1200) ** (t / dur)
    phase = 2 * np.pi * np.cumsum(f) / sr
    return (2 * (phase % 1) - 1) * exp_env(len(t), 0.12, sr)


def lightsaber(dur=2.5, sr=SR):
    """光剑：两个失谐锯齿(300+304Hz) + 27Hz 震音 + 淡入淡出"""
    t = t_axis(dur, sr)
    saw = (2 * ((2 * np.pi * 300 * t) % 1) - 1) + (2 * ((2 * np.pi * 304 * t) % 1) - 1)
    return fade(saw * (0.7 + 0.3 * np.sin(2 * np.pi * 27 * t)), 0.15, sr)


def magic_drop(sr=SR):
    """电影'倒放+混响'魔法（6.7：reverse + echos）"""
    y = water_drop(0.18)[::-1]
    dl = int(0.3 * sr)
    y2 = y.copy()
    y2[dl:] += 0.5 * y[:-dl]
    y2[2 * dl:] += 0.25 * y[:-2 * dl]
    return y2


# ----------------------------------------------------------------------
# 注册表：名字 -> (合成函数, 一句话配方说明)
# ----------------------------------------------------------------------

DEMOS = {
    'vowel_a':  (lambda: vowel('a'),    "人声'啊'：声门120Hz × 共振峰 730/1090/2440"),
    'vowel_i':  (lambda: vowel('i'),    "人声'衣'：270/2290/3010（元音四边形另一角）"),
    'vowel_u':  (lambda: vowel('u'),    "人声'呜'：300/870/2240（圆唇）"),
    'baby':     (baby_a,                "婴儿'啊'：F0=360、κ=1.8（F×1.8）、带宽×1.5、气声β=0.15"),
    'robot':    (robot_a,               "机器人'啊'：方波源+人声共振峰，jitter=0（没人味）"),
    'kick':     (kick,                  "底鼓：正弦100→50Hz下滑，τ=0.2s"),
    'snare':    (snare,                 "军鼓：噪声高通1.5k+200Hz谐振，τ=0.07s"),
    'cymbal':   (cymbal,                "镲：噪声高通6k，τ=1.5s金属余韵"),
    'woodblock':(woodblock,             "木鱼：谐振器900→300Hz急滑，τ=30ms"),
    'drop':     (water_drop,            "水滴：谐振800→100Hz急滑，τ=50ms"),
    'piano':    (piano,                 "钢琴C4：谐波独立衰减 τₖ=τ₁/k（越弹越闷的数学）"),
    'guitar':   (guitar,                "拨弦E2+A2：Karplus-Strong 延迟环 N≈267"),
    'violin':   (violin,                "提琴底料：锯齿+6Hz揉弦 vibrato"),
    'wind':     (wind,                  "风声：白噪→低通800Hz + 0.15Hz 幅度LFO"),
    'rain':     (rain,                  "雨声：噪声高通4k + 随机雨点"),
    'thunder':  (thunder,               "雷声：棕噪（低频重）+ 低通200Hz + 初爆衰减"),
    'heartbeat':(heartbeat,             "心跳：60/45Hz 双脉冲，75bpm"),
    'bird':     (bird,                  "鸟鸣：鸣管源-滤模型！F0滑音+双共振峰"),
    'mosquito': (mosquito,              "蚊子：480Hz + 38Hz 幅度调制"),
    'engine':   (engine,                "引擎怠速：20Hz脉冲 + 低通500Hz 突突"),
    'siren_eu': (siren_eu,              "欧式警报：650±150Hz 扫频 1Hz"),
    'siren_us': (siren_us,              "美式警笛：600↔720Hz 交替双音"),
    'busy':     (busy_tone,             "电话忙音：480+620Hz 响0.5停0.5"),
    'laser':    (laser,                 "激光枪：锯齿1200→150Hz 急滑0.3s"),
    'saber':    (lightsaber,            "光剑：双失谐锯齿300+304Hz + 27Hz震音"),
    'magic':    (magic_drop,            "魔法音效：水滴倒放+回声（电影reverse+reverb）"),
}


def main():
    args = sys.argv[1:]
    play = '--play' in args
    names = [a for a in args if a != '--play']
    targets = names if names else list(DEMOS)
    os.makedirs('demo_wavs', exist_ok=True)

    for name in targets:
        if name not in DEMOS:
            print(f"[跳过] 未知 demo: {name}（可选: {', '.join(DEMOS)}）")
            continue
        fn, desc = DEMOS[name]
        audio = normalize(np.asarray(fn(), dtype=np.float64))
        path = os.path.join('demo_wavs', f'{name}.wav')
        sf.write(path, audio, SR)
        print(f"[OK] {path}  ←  {desc}")
        if play:
            if sd is None:
                print("      （播放需要 pip install sounddevice）")
            else:
                sd.play(audio, SR)
                sd.wait()

    print(f"\n完成：{len(targets)} 个声音已生成到 demo_wavs/ 目录")
    print("用任意播放器打开 wav 听；或: py synth_demo.py --play kick wind ...")


if __name__ == '__main__':
    main()