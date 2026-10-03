# -*- coding: utf-8 -*-
"""
editor/engine.py —— 合成渲染引擎（v4：转场 / 渐变速度 / 音频轨）

分轨中间文件两段式：
  第一阶段：每条轨道独立渲染成无损中间文件（matroska）
    - 主轨   ：ffv1 yuv420p + pcm（满屏视频）
    - overlay：ffv1 rgba + pcm（透明画布上的 PiP）
    - audio  ：纯音频 pcm（无视频流）→ 参与最终混音
  第二阶段：小图合成（overlay 逐轨叠加 + amix 音频 + atrim 总长）
转场：同轨相邻真片段（无缝）且前一片段配了 transition 时，
      视频用 xfade 链、音频用 acrossfade 链；否则 concat 拼接。
渐变速度：视频用 setpts 二次公式（线性变速）；音频按平均速度 atempo。
扩展点：Clip.effects 按 "type" 分发（滤镜/字幕）；新轨型加 kind 分支。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Callable, Dict, List, Optional, Tuple

from . import logger as _logmod
from .model import (AudioClip, Clip, ImageClip, Project, TextClip, VideoClip,
                    filter_chain)

log = _logmod.get_logger("engine")


def fmt(x: float) -> str:
    return f"{x:.3f}"


def atempo_chain(speed: float) -> List[str]:
    """atempo 只能处理 0.5~2.0，超出则链式拆分。"""
    parts = []
    s = float(speed)
    if s <= 0:
        return ["atempo=1.0"]
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return parts


# 支持的转场类型（白名单，防 ffmpeg 报错）
TRANSITIONS = ["fade", "fadeblack", "fadewhite", "dissolve", "wipeleft",
               "wiperight", "wipeup", "wipedown", "slideleft", "slideright",
               "slideup", "slidedown", "circleopen", "circleclose",
               "pixelize", "radial"]


def safe_transition(tr) -> Optional[dict]:
    """校验转场字典；非法返回 None。"""
    if not isinstance(tr, dict):
        return None
    name = str(tr.get("name", ""))
    if name not in TRANSITIONS:
        return None
    try:
        dur = float(tr.get("dur", 0))
    except (TypeError, ValueError):
        return None
    if dur <= 0:
        return None
    return {"name": name, "dur": min(dur, 10.0)}


class RenderError(Exception):
    pass


FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",    # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",  # 黑体
    r"C:\Windows\Fonts\simsun.ttc",  # 宋体
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Arial.ttf",
]


def find_font() -> str:
    for p in FONT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return ""


def _run_ffmpeg(cmd: List[str], total_dur: float,
                on_log: Optional[Callable[[str], None]] = None,
                cwd: Optional[str] = None) -> None:
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", cwd=cwd,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    tail: List[str] = []
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            tail.append(line)
            if len(tail) > 8:
                tail.pop(0)
            if on_log and ("error" in line.lower() or "warning" in line.lower()):
                on_log(line)
    finally:
        proc.wait()
    if proc.returncode != 0:
        log.error("ffmpeg 失败 code=%s: %s", proc.returncode, "\n".join(tail))
        raise RenderError(f"ffmpeg 失败（退出码 {proc.returncode}）\n" + "\n".join(tail))


class Engine:
    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = ""):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe or ""
        self._info_cache: Dict[str, dict] = {}

    # ---------------- 元数据探测（无需 ffprobe：用 ffmpeg -i 解析） ----------------
    def _probe_info(self, path: str) -> dict:
        """运行 ffmpeg -i 解析 stderr：时长/音频流/fps。带缓存。"""
        if path not in self._info_cache:
            info = {"duration": 0.0, "has_audio": False, "fps": 30.0}
            try:
                r = subprocess.run(
                    [self.ffmpeg, "-hide_banner", "-nostdin", "-i", path],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=120)
                out = r.stderr or ""
                m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
                if m:
                    info["duration"] = (int(m.group(1)) * 3600 +
                                        int(m.group(2)) * 60 +
                                        float(m.group(3)))
                info["has_audio"] = bool(
                    re.search(r"Stream #\d+:\d+.*Audio:", out))
                mf = re.search(r"Stream #\d+:\d+.*Video:.*?([\d.]+)\s*fps", out)
                if mf:
                    info["fps"] = float(mf.group(1))
            except Exception as e:
                log.warning("ffmpeg -i 探测失败 %s: %s", path, e)
            self._info_cache[path] = info
        return self._info_cache[path]

    def source_length(self, path: str) -> float:
        return self._probe_info(path)["duration"]

    def has_audio(self, path: str) -> bool:
        return self._probe_info(path)["has_audio"]

    # ---------------- 主入口 ----------------
    def render(self, project: Project, out_path: str,
               on_progress: Optional[Callable[[float], None]] = None,
               on_log: Optional[Callable[[str], None]] = None,
               keep_intermediates: bool = False,
               container: str = "mp4", crf: int = 20,
               intermediates_dir: Optional[str] = None) -> str:
        total = project.total_duration()
        if total <= 0:
            raise RenderError("时间轴为空，没有可渲染的内容。")

        log.info("渲染开始: 总时长 %.2fs, 画布 %dx%d, 输出 %s (%s, crf=%d)",
                 total, project.canvas_w, project.canvas_h, out_path,
                 container, crf)
        # 中间产物目录：给了则暂存（调试/复用），否则临时目录用完即删
        if intermediates_dir:
            tmp_root = intermediates_dir
            os.makedirs(tmp_root, exist_ok=True)
            remove_tmp = False
        else:
            tmp_root = tempfile.mkdtemp(prefix="vcp_render_")
            remove_tmp = True
        W, H, fps = project.canvas_w, project.canvas_h, project.fps

        tracks = []
        mt = project.track("main", create=False)
        if mt is not None and mt.clips and mt.visible:
            tracks.append(("main", mt))
        for t in project.tracks:
            if t.kind == "overlay" and t.clips and t.visible:
                tracks.append(("overlay", t))
        for t in project.tracks:
            if t.kind == "audio" and t.clips and t.visible:
                tracks.append(("audio", t))

        track_files: List[Tuple[str, str]] = []
        try:
            # 文字轨需要字体：复制到中间目录用相对路径引用（避免盘符冒号解析问题）
            font_src = find_font()
            if font_src and any(t.kind == "subtitle" and t.clips
                                for t in project.tracks):
                try:
                    shutil.copy(font_src, os.path.join(tmp_root, "font.ttc"))
                except OSError as e:
                    log.warning("字体复制失败，文字将跳过: %s", e)
            units = max(len(tracks), 1)
            done = 0.0
            for kind, track in tracks:
                inter = os.path.join(tmp_root, f"track_{len(track_files)}.mkv")
                log.info("渲染轨道 [%s] 片段数=%d -> %s",
                         kind, len(track.clips), inter)
                self._render_track(project, track, kind, inter, on_log=on_log)
                track_files.append((kind, inter))
                done += 1.0
                if on_progress:
                    on_progress(done / units)

            self._compose(track_files, project, out_path, total,
                          on_log=on_log, container=container, crf=crf,
                          text_dir=tmp_root)
            log.info("渲染完成: %s", out_path)
            if on_progress:
                on_progress(1.0)
        finally:
            if remove_tmp and not keep_intermediates:
                shutil.rmtree(tmp_root, ignore_errors=True)
        return out_path

    # ---------------- 单轨中间文件 ----------------
    def _render_track(self, project: Project, track, kind: str,
                      out_path: str, on_log=None) -> float:
        W, H, fps = project.canvas_w, project.canvas_h, project.fps
        total = project.total_duration()
        is_main = kind == "main"
        is_audio = kind == "audio"

        inputs, graph = self._track_graph(project, track, W, H, fps, total,
                                          is_main, is_audio)

        cmd = [self.ffmpeg, "-y", "-hide_banner", "-nostdin"]
        cmd += inputs
        cmd += ["-filter_complex", graph]
        if is_audio:
            cmd += ["-map", "[aout]", "-vn", "-c:a", "pcm_s16le"]
        else:
            cmd += ["-map", "[vout]", "-map", "[aout]",
                    "-c:v", "ffv1", "-level", "3",
                    "-c:a", "pcm_s16le"]
            if not is_main:
                cmd += ["-pix_fmt", "rgba"]
        cmd.append(out_path)

        if on_log:
            on_log(f"TRACK[{kind}]: " + " ".join(cmd[:200]) + " ...")
        _run_ffmpeg(cmd, total, on_log)
        return total

    # ---------------- 轨道图构建 ----------------
    def _track_graph(self, project, track, W, H, fps, total,
                     is_main, is_audio):
        """生成单轨的 (inputs, filtergraph)。
        片段流（含空隙流）串成链：相邻真片段配了转场时用 xfade/acrossfade，
        否则 concat。渐变速度用 setpts 二次公式。"""
        inputs: List[str] = []
        clip_meta: Dict[str, dict] = {}

        in_count = 0
        for clip in sorted(track.clips, key=lambda c: c.ts):
            if isinstance(clip, ImageClip):
                inputs += ["-loop", "1", "-framerate", f"{fps:g}",
                           "-t", fmt(clip.timeline_duration()), "-i", clip.src]
            else:
                inputs += ["-i", clip.src]
            idx = in_count
            in_count += 1
            clip_meta[clip.id] = {
                "idx": idx,
                "src_len": clip.out_point or self.source_length(clip.src),
            }

        lines: List[str] = []
        n = 0
        v_segs: List[dict] = []  # {"label","dur","clip_id","transition"}
        a_segs: List[dict] = []
        cursor = 0.0

        def blank_video_seg(dur):
            nonlocal n
            alpha = not is_main
            base = "color=c=0x00000000" if alpha else "color=c=black"
            vl = f"[bk{n}]"
            lines.append(f"{base}:s={W}x{H}:d={fmt(dur)},fps={fps:g},"
                         f"format={'rgba' if alpha else 'yuv420p'},"
                         f"setpts=PTS-STARTPTS{vl}")
            n += 1
            return vl

        def blank_audio_seg(dur):
            nonlocal n
            al = f"[ska{n}]"
            lines.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{fmt(dur)},"
                         f"asetpts=PTS-STARTPTS{al}")
            n += 1
            return al

        def chain_streams(segs, is_audio_chain):
            """串流链：相邻真片段配转场→xfade/acrossfade，否则 concat。"""
            if not segs:
                return None
            if len(segs) == 1:
                return segs[0]["label"]
            cur = segs[0]["label"]
            acc = segs[0]["dur"]
            for k in range(1, len(segs)):
                tr = None
                if segs[k - 1].get("clip_id") and segs[k].get("clip_id"):
                    tr = safe_transition(segs[k - 1].get("transition"))
                if tr:
                    out = f"[{('a' if is_audio_chain else 'v')}xf{k}]"
                    if is_audio_chain:
                        lines.append(
                            f"{cur}{segs[k]['label']}acrossfade=d={fmt(tr['dur'])}:"
                            f"c1=tri:c2=tri{out}")
                    else:
                        offset = max(acc - tr["dur"], 0.0)
                        lines.append(
                            f"{cur}{segs[k]['label']}xfade=transition={tr['name']}:"
                            f"duration={fmt(tr['dur'])}:offset={fmt(offset)}{out}")
                    acc = acc + segs[k]["dur"] - tr["dur"]
                else:
                    out = f"[{('a' if is_audio_chain else 'v')}cn{k}]"
                    lines.append(
                        f"{cur}{segs[k]['label']}concat=n=2:"
                        f"v={0 if is_audio_chain else 1}:"
                        f"a={1 if is_audio_chain else 0}{out}")
                    acc += segs[k]["dur"]
                cur = out
            return cur

        for clip in sorted(track.clips, key=lambda c: c.ts):
            seg_dur = clip.timeline_duration()
            meta = clip_meta[clip.id]
            idx = meta["idx"]
            is_img = isinstance(clip, ImageClip)
            is_aud = isinstance(clip, AudioClip)

            eff_ts = max(clip.ts, cursor)
            if eff_ts > cursor + 1e-6:
                if not is_audio:
                    v_segs.append({"label": blank_video_seg(eff_ts - cursor),
                                   "dur": eff_ts - cursor})
                a_segs.append({"label": blank_audio_seg(eff_ts - cursor),
                               "dur": eff_ts - cursor})

            # ---- 视频链（audio 轨跳过）----
            scv = None
            if not is_audio:
                if is_img:
                    vc = [f"scale={fmt(clip.w)}:{fmt(clip.h)}:force_original_aspect_ratio=decrease:flags=lanczos:force_divisible_by=2:flags=lanczos",
                          "setsar=1", f"fps={fps:g}", "format=rgba"]
                else:
                    out_end = clip.out_point or meta["src_len"]
                    ramp = (getattr(clip, "ramp_start", 0.0) > 0 and
                            getattr(clip, "ramp_end", 0.0) > 0 and
                            getattr(clip, "ramp_dur", 0.0) > 0)
                    vc = [f"trim=start={fmt(clip.in_point)}:end={fmt(out_end)}",
                          "setpts=PTS-STARTPTS"]
                    if ramp:
                        s0, s1, D = clip.ramp_start, clip.ramp_end, clip.ramp_dur
                        if abs(s1 - s0) < 1e-4:
                            vc.append(f"setpts=PTS/{fmt(s0)}")
                        else:
                            vc.append(
                                f"setpts='(-{fmt(s0)}+sqrt({fmt(s0)}*{fmt(s0)}+"
                                f"2*({fmt(s1)}-{fmt(s0)})*T/{fmt(D)}))/"
                                f"(({fmt(s1)}-{fmt(s0)})/{fmt(D)})'")
                        log.info("渐变速度片段 %s: %.2fx→%.2fx over %.2fs",
                                 clip.name, s0, s1, D)
                    else:
                        vc.append(
                            f"setpts=PTS/{fmt(clip.speed if clip.speed > 0 else 1.0)}")
                    if is_main:
                        vc += [f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos:force_divisible_by=2:flags=lanczos",
                               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black",
                               f"fps={fps:g}", "format=yuv420p"]
                    else:
                        vc += [f"scale={fmt(clip.w)}:{fmt(clip.h)}:force_original_aspect_ratio=decrease:flags=lanczos:force_divisible_by=2:flags=lanczos",
                               "setsar=1", f"fps={fps:g}", "format=rgba"]
                if getattr(clip, "opacity", 1.0) < 1.0 and not is_main:
                    vc.append(f"colorchannelmixer=aa={fmt(clip.opacity)}")
                # 滤镜（亮度/对比/饱和度/黑白）
                vc += filter_chain(clip.effects)
                scv = f"[scv{n}]"
                # 新版 ffmpeg 不允许 “[标签],过滤器” 写法
                lines.append(f"[{idx}:v]" + ",".join(vc) + scv)

                if not is_main:
                    cv = f"[cov{n}]"
                    lines.append(
                        f"color=c=0x00000000:s={W}x{H}:d={fmt(seg_dur)},fps={fps:g},format=rgba,"
                        f"setpts=PTS-STARTPTS{cv}")
                    pv = f"[pov{n}]"
                    lines.append(
                        f"{cv}{scv}overlay={fmt(clip.x)}:{fmt(clip.y)}:format=auto{pv}")
                    scv = pv
                v_segs.append({"label": scv, "dur": seg_dur, "clip_id": clip.id,
                               "transition": getattr(clip, "transition", None)})

            # ---- 音频链 ----
            if is_aud:
                out_end = clip.out_point or meta["src_len"]
                achain = [f"atrim=start={fmt(clip.in_point)}:end={fmt(out_end)}",
                          "asetpts=PTS-STARTPTS",
                          *atempo_chain(clip.speed if clip.speed > 0 else 1.0),
                          "aresample=44100",
                          "aformat=sample_fmts=fltp:channel_layouts=stereo",
                          f"volume={fmt(max(clip.volume, 0.0))}"]
                if clip.fade_in > 0:
                    achain.append(f"afade=t=in:st=0:d={fmt(clip.fade_in)}")
                if clip.fade_out > 0:
                    achain.append(
                        f"afade=t=out:st={fmt(max(seg_dur - clip.fade_out, 0))}:"
                        f"d={fmt(clip.fade_out)}")
                al = f"[sa{n}]"
                lines.append(f"[{idx}:a]" + ",".join(achain) + al)
            elif is_img or not self.has_audio(clip.src):
                al = f"[sa{n}]"
                lines.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{fmt(seg_dur)},"
                             f"asetpts=PTS-STARTPTS{al}")
            else:
                out_end = clip.out_point or meta["src_len"]
                ramp_avg = None
                if getattr(clip, "ramp_start", 0.0) > 0 and \
                        getattr(clip, "ramp_end", 0.0) > 0:
                    ramp_avg = (clip.ramp_start + clip.ramp_end) / 2.0
                    log.info("渐变速度片段音频按平均速度 %.2fx（画面为渐变）",
                             ramp_avg)
                spd = ramp_avg if ramp_avg else \
                    (clip.speed if clip.speed > 0 else 1.0)
                achain = [f"atrim=start={fmt(clip.in_point)}:end={fmt(out_end)}",
                          "asetpts=PTS-STARTPTS",
                          *atempo_chain(spd),
                          "aresample=44100",
                          "aformat=sample_fmts=fltp:channel_layouts=stereo",
                          f"volume={fmt(max(clip.volume, 0.0))}"]
                al = f"[sa{n}]"
                lines.append(f"[{idx}:a]" + ",".join(achain) + al)
            a_segs.append({"label": al, "dur": seg_dur, "clip_id": clip.id,
                           "transition": (getattr(clip, "transition", None)
                                          if not is_aud else None)})

            n += 1
            cursor = eff_ts + seg_dur

        # 尾部补齐到项目总时长
        if total > cursor + 1e-6:
            if not is_audio:
                v_segs.append({"label": blank_video_seg(total - cursor),
                               "dur": total - cursor})
            a_segs.append({"label": blank_audio_seg(total - cursor),
                           "dur": total - cursor})

        v_out = "[vout]"
        a_out = "[aout]"
        if not is_audio:
            cur = chain_streams(v_segs, False)
            if cur is None:
                lines.append(
                    f"color=c=black:s={W}x{H}:d={fmt(total)},fps={fps:g},"
                    f"format=yuv420p[empty_v]")
                cur = "[empty_v]"
            # 用 null 滤镜把链输出重命名为 [vout]
            lines.append(f"{cur}null{v_out}")
        cur = chain_streams(a_segs, True)
        if cur is None:
            lines.append(
                f"anullsrc=r=44100:cl=stereo,atrim=0:{fmt(total)},"
                f"asetpts=PTS-STARTPTS{a_out}")
        else:
            # 用 anull 滤镜把链输出重命名为 [aout]
            lines.append(f"{cur}anull{a_out}")
        return inputs, ";\n".join(lines)

    # ---------------- 文字/字幕 ----------------
    def _append_text_filters(self, cur: str, text_clips, W, H, lines,
                             text_dir: str | None) -> str:
        """把文字片段变成一串 drawtext 滤镜。
        关键：字体/文本都用相对路径（text_dir 作为子进程 cwd），去掉盘符冒号，
        避免 ffmpeg filtergraph 对 'C:...' 的解析问题。"""
        if not text_dir:
            return cur
        font = os.path.join(text_dir, "font.ttc")
        if not os.path.isfile(font):
            log.warning("未找到可用字体，文字片段将跳过（%d 条）", len(text_clips))
            return cur
        for i, tc in enumerate(text_clips):
            if not tc.text.strip():
                continue
            # 文本内容写中间目录（UTF-8，相对名引用）
            txtname = f"vcp_text_{i}.txt"
            with open(os.path.join(text_dir, txtname), "w",
                      encoding="utf-8") as f:
                f.write(tc.text)
            out_l = f"[txt{i}]"
            expr = "between(t,{:.3f},{:.3f})".format(
                tc.ts, tc.ts + tc.timeline_duration())
            fcolor = (tc.color or "#FFFFFF").lstrip("#")
            if len(fcolor) == 3:
                fcolor = "".join(c * 2 for c in fcolor)
            if tc.align == "top":
                pos = "x=(w-tw)/2:y=40"
            elif tc.align == "center":
                pos = "x=(w-tw)/2:y=(h-th)/2"
            else:
                pos = "x=(w-tw)/2:y=h-th-60"
            chain = (f"drawtext=fontfile=font.ttc:textfile={txtname}:"
                     f"fontsize={fmt(tc.font_size)}:fontcolor=0x{fcolor}:"
                     f"{pos}:enable='{expr}'")
            if tc.fade_in > 0:
                chain += f":alpha='if(lt(t,{tc.ts + tc.fade_in:.3f}),"
                chain += f"(t-{tc.ts:.3f})/{tc.fade_in:.3f},1)'"
            lines.append(f"{cur}{chain}{out_l}")
            cur = out_l
        return cur
    def _compose(self, track_files, project: Project, out_path: str,
                 total: float, on_log=None, container: str = "mp4",
                 crf: int = 20, text_dir: str | None = None) -> None:
        W, H, fps = project.canvas_w, project.canvas_h, project.fps

        video_files = [(k, p) for k, p in track_files if k != "audio"]
        audio_files = [(k, p) for k, p in track_files if k == "audio"]

        inputs: List[str] = []
        lines: List[str] = []
        main_file = next((p for k, p in video_files if k == "main"), None)
        ov_files = [p for k, p in video_files if k != "main"]

        for _, p in video_files:
            inputs += ["-i", p]
        for _, p in audio_files:
            inputs += ["-i", p]

        if main_file:
            cur = "[0:v]"
        else:
            cur = "[bkg]"
            lines.append(
                f"color=c=black:s={W}x{H}:d={fmt(total)},fps={fps:g},format=yuv420p,"
                f"setpts=PTS-STARTPTS[bkg]")
        for i, _ in enumerate(ov_files):
            out_l = f"[z{i}]"
            lines.append(
                f"{cur}[{i + (1 if main_file else 0)}:v]overlay=0:0:format=auto{out_l}")
            cur = out_l
        # 文字/字幕轨（drawtext，画在合成画面最顶层）
        text_clips = []
        for t in project.tracks:
            if t.kind == "subtitle" and t.visible:
                text_clips.extend(t.clips)
        if text_clips:
            cur = self._append_text_filters(cur, sorted(text_clips, key=lambda c: c.ts),
                                            W, H, lines, text_dir)
        lines.append(f"{cur}trim=start=0:end={fmt(total)},"
                     f"setpts=PTS-STARTPTS,format=yuv420p[vout]")

        n_all = len(video_files) + len(audio_files)
        audio_lbls = [f"[{i}:a]" for i in range(n_all)]
        if not audio_lbls:
            lines.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{fmt(total)},"
                         f"asetpts=PTS-STARTPTS[aout]")
        elif len(audio_lbls) == 1:
            lines.append(f"{audio_lbls[0]}atrim=0:{fmt(total)},asetpts=PTS-STARTPTS[aout]")
        else:
            lines.append(
                f"{''.join(audio_lbls)}amix=inputs={len(audio_lbls)}:"
                f"duration=longest:normalize=0,atrim=0:{fmt(total)},asetpts=PTS-STARTPTS[aout]")

        cmd = [self.ffmpeg, "-y", "-hide_banner", "-nostdin"]
        cmd += inputs
        cmd += ["-filter_complex", ";\n".join(lines),
                "-map", "[vout]", "-map", "[aout]"]
        # 容器/编码预设（扩展点：后续可加 gif/ts 等）
        container = (container or "mp4").lower()
        if container == "webm":
            cmd += ["-c:v", "libvpx-vp9", "-crf", f"{max(crf - 6, 0)}",
                    "-b:v", "0", "-c:a", "libopus", "-b:a", "192k"]
        elif container == "mov":
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", f"{crf}",
                    "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", f"{crf}",
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart"]
        cmd.append(out_path)
        if on_log:
            on_log("COMPOSE: " + " ".join(cmd[:200]) + " ...")
        _run_ffmpeg(cmd, total, on_log, cwd=text_dir)