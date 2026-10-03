# -*- coding: utf-8 -*-
"""
test_engine.py —— 引擎冒烟测试（无 GUI，验证模型+渲染管线）

用例（模拟用户场景，画布缩小为 640x360）：
  - 主轨：v1 满屏 10s
  - overlay1：v2 右上角 160x90，加速 2x（源 8s → 占 4s）
  - overlay1：v3 右下角 160x90，只取前 5s（源 6s 只剪 5s）
  - overlay2：logo.png 右下角常驻（duration=项目总长）
渲染后验证：时长 ≈ 10s、分辨率 640x360、文件存在。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from editor.model import AudioClip, ImageClip, Project, TextClip, VideoClip
from editor.engine import Engine

FFMPEG = os.path.join("tools", "ffmpeg", "bin", "ffmpeg.exe")
FFPROBE = os.path.join("tools", "ffmpeg", "bin", "ffprobe.exe")


def run(cmd):
    import subprocess
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        raise RuntimeError("command failed: " + " ".join(cmd) + "\n" + r.stderr[-800:])


def make_samples(dirpath):
    """生成测试媒体：v1/v2/v3 视频 + logo.png。"""
    v1 = os.path.join(dirpath, "v1.mp4")
    v2 = os.path.join(dirpath, "v2.mp4")
    v3 = os.path.join(dirpath, "v3.mp4")
    img = os.path.join(dirpath, "logo.png")

    run([FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-t", "10", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", v1])
    run([FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=8",
         "-f", "lavfi", "-i", "sine=frequency=550:sample_rate=44100",
         "-t", "8", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", v2])
    run([FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=44100",
         "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", v3])

    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 199, 99], fill=(255, 0, 0, 255))
    d.text((10, 30), "LOGO", fill=(255, 255, 255, 255))
    im.save(img)

    return v1, v2, v3, img


def run_make_audio(path):
    """生成背景音乐 wav（6 秒正弦波）。"""
    run([FFMPEG, "-y", "-f", "lavfi",
         "-i", "sine=frequency=330:sample_rate=44100",
         "-t", "6", "-c:a", "pcm_s16le", path])
    return path


def main():
    tmp = tempfile.mkdtemp(prefix="vcp_test_")
    print("[1/5] 生成样例媒体...")
    v1, v2, v3, img = make_samples(tmp)

    print("[2/5] 搭建项目：主轨v1+v1b(转场fade) + 右上v2(渐变速度) + 右下v3 + 常驻logo + 音乐")
    proj = Project(canvas_w=640, canvas_h=360, fps=30)
    c1 = VideoClip(src=v1, in_point=0, out_point=10, ts=0, duration=10,
                   transition={"name": "fade", "dur": 0.5})
    proj.track("main", create=True).add(c1)
    # 第二主轨片段：紧接 c1（无缝），c1→c1b 用 fade 转场
    c1b = VideoClip(src=v3, in_point=0, out_point=5, ts=10, duration=5)
    proj.track("main", create=True).add(c1b)

    # 用户场景：三个视频同时显示，各占一条叠加轨（并行层）
    c2 = VideoClip(src=v2, in_point=0, out_point=8, ts=0, duration=4,
                   speed=2.0, volume=0.6, x=480, y=0, w=160, h=90,
                   ramp_start=1.0, ramp_end=3.0, ramp_dur=4.0)
    t2 = proj.new_overlay_track()
    t2.add(c2)

    c3 = VideoClip(src=v3, in_point=0, out_point=5, ts=0, duration=5,
                   volume=0.5, x=480, y=270, w=160, h=90)
    t3 = proj.new_overlay_track()
    t3.add(c3)

    total = proj.total_duration()
    c4 = ImageClip(src=img, ts=0, duration=total, x=480, y=270,
                   w=160, h=90, opacity=0.8)
    t4 = proj.new_overlay_track()
    t4.add(c4)

    # 音频轨：背景音乐（音量 0.3，淡入淡出），从 0 到全片
    music = run_make_audio(os.path.join(tmp, "music.wav"))
    c5 = AudioClip(src=music, ts=0, duration=total,
                   in_point=0, out_point=6, volume=0.3,
                   fade_in=0.5, fade_out=1.0)
    ta = proj.new_audio_track()
    ta.add(c5)

    # 文字轨：字幕（drawtext）
    c6 = TextClip(text="测试字幕 Hello", ts=2, duration=3,
                  align="bottom", font_size=36, color="#FFD700")
    ts_ = proj.new_text_track()
    ts_.add(c6)

    # 记录素材快照（验证渲染不修改源文件）
    import os as _os
    src_snapshot = {p: (_os.path.getmtime(p), _os.path.getsize(p))
                    for p in (v1, v2, v3, img, music) if _os.path.isfile(p)}

    print(f"      项目总时长 = {total:.2f}s，轨道数 = {len(proj.tracks)}")

    print("[3/5] 模型 JSON 往返...")
    proj2 = Project.from_json(proj.to_json())
    assert len(proj2.all_clips()) == 7, "序列化丢片段"
    assert any(isinstance(c, AudioClip) for c in proj2.all_clips()), "音频片段丢失"
    assert any(isinstance(c, TextClip) for c in proj2.all_clips()), "文字片段丢失"
    print("      总时长(含转场重叠扣除) =", round(proj2.total_duration(), 2))
    print("      OK")

    print("[4/5] 渲染...")
    eng = Engine(ffmpeg=FFMPEG, ffprobe=FFPROBE)
    out = os.path.join(tmp, "out.mp4")
    logs = []
    try:
        eng.render(proj, out, on_progress=lambda p: None,
                   on_log=lambda s: logs.append(s))
    except Exception:
        print("---- ffmpeg 出错日志（最近5条）----")
        for s in logs[-5:]:
            print("   ", s[:500])
        raise

    print("[5/5] 验证输出（用 ffmpeg -i 解析，不依赖 ffprobe）...")
    import subprocess
    import re as _re
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-i", out],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    err = r.stderr or ""
    m = _re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    assert m, "无法解析输出时长"
    d = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    info = []
    for line in err.splitlines():
        if line.strip():
            info.append(line.strip())
    expect = 10 + 5 - 0.5  # 主轨 v1(10)+v1b(5) - fade(0.5)
    assert abs(d - expect) < 1.0, f"时长不符: {d} != {expect}"
    assert any("640x360" in l for l in info), "分辨率不符"
    assert _re.search(r"Audio:", err), "输出缺少音频流"
    assert "640x360" in err, "分辨率不符"
    print(f"      时长 OK ({d:.2f}s ≈ {expect}s)，分辨率 OK，音频流 OK")
    # 素材不被破坏：渲染后源文件 mtime/大小 必须不变
    unchanged = all(
        (os.path.getmtime(p), os.path.getsize(p)) == sig
        for p, sig in src_snapshot.items())
    assert unchanged, "渲染修改了源素材文件！"
    print("      素材完整性 OK（源文件未被修改）")
    # 图层可见性：隐藏 logo 轨后重渲，右下角不应再出现红色 logo
    for t in proj.tracks:
        if t.kind == 'overlay' and any(isinstance(c, ImageClip) for c in t.clips):
            t.visible = False
    eng2 = Engine(ffmpeg=FFMPEG, ffprobe=FFPROBE)
    out2 = os.path.join(tmp, 'out_hidden.mp4')
    eng2.render(proj, out2, on_progress=lambda p: None)
    subprocess.run([FFMPEG, '-y', '-v', 'error', '-ss', '3', '-i', out2,
                    '-frames:v', '1', os.path.join(tmp, 'h.png')],
                   capture_output=True)
    # 对比含logo渲染与隐藏logo渲染在同一右下角区域：像素必须明显不同
    from PIL import Image as _Im, ImageChops as _Ch
    subprocess.run([FFMPEG, '-y', '-v', 'error', '-ss', '3', '-i', out,
                    '-frames:v', '1', os.path.join(tmp, 'v.png')],
                   capture_output=True)
    a = _Im.open(os.path.join(tmp, 'v.png')).convert('RGB')
    b = _Im.open(os.path.join(tmp, 'h.png')).convert('RGB')
    w, hh = a.size
    box = (int(w*0.55), int(hh*0.7), w, hh)
    diff = _Ch.difference(a.crop(box), b.crop(box))
    changed = sum(1 for p in diff.getdata() if sum(p) > 40)
    assert changed > 500, f'隐藏图层仍被渲染(差异过小): {changed}'
    print('      隐藏图层不进渲染 OK（对比差异 %d px）' % changed)

    print(f"\n全部通过！输出示例: {out}")


if __name__ == "__main__":
    main()

