# -*- coding: utf-8 -*-
"""
editor/model.py —— 时间轴数据模型（唯一的"事实来源"）

设计原则（扩展点）：
- Clip 基类带 `effects` 列表：未来转场/滤镜/字幕等所有效果都进这里，
  例如 {"type":"transition","name":"fade","dur":0.5}，渲染引擎按 type 分发。
- Track 用 `kind` 区分用途（main/overlay/audio），未来可加 "subtitle" 等新轨型。
- 所有对象支持 to_dict()/from_dict()，供 JSON 项目文件（.vcp）与自动保存使用。

时间语义：
- ts / duration 均为【时间轴秒】，与播放速度无关。
- 源裁剪：VideoClip 的 in_point/out_point 是【源文件秒】。
- 时间轴上占用的时长 duration = (out_point - in_point) / speed。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- 位置预设
# PiP 布局预设：满屏用 None 表示（渲染时铺满画布）
LAYOUT_PRESETS = {
    "full":   None,            # 满屏（主轨默认）
    "topleft":     (0, 0),
    "topright":    None,        # 占位（画布宽高运行时算）
    "bottomleft":  None,
    "bottomright": None,
}


# ------------------------------------------------------------------ 片段
@dataclass
class Clip:
    """片段基类。id 全局唯一；src 为媒体绝对路径（文字片段可留空）。"""
    src: str = ""
    ts: float = 0.0                    # 时间轴起点（秒）
    duration: float = 10.0             # 时间轴上占用的时长（秒）
    speed: float = 1.0                 # 播放速度倍率
    volume: float = 1.0                # 音量倍率（1.0 原声）
    effects: List[Dict[str, Any]] = field(default_factory=list)
    id: str = field(default_factory=new_id)
    track_id: str = "main"
    name: str = ""

    kind = "clip"                      # 子类覆写

    def __post_init__(self):
        if not self.name:
            self.name = self.src.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]

    # ---------------- 序列化 ----------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "src": self.src,
            "ts": self.ts,
            "duration": self.duration,
            "speed": self.speed,
            "volume": self.volume,
            "effects": self.effects,
            "track_id": self.track_id,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Clip":
        return cls(**{k: v for k, v in d.items() if k != "kind"})


@dataclass
class VideoClip(Clip):
    in_point: float = 0.0              # 源起始秒
    out_point: float = 0.0             # 源结束秒（0 表示直到文件末尾，渲染时用 ffprobe 补全）
    x: float = -1                      # PiP 位置（画布坐标，-1 = 满屏）
    y: float = -1
    w: float = -1                      # PiP 尺寸（-1 = 按画布宽高）
    h: float = -1
    opacity: float = 1.0               # 不透明度 0~1
    transition: Optional[dict] = None  # 到【下一相邻片段】的转场 {"name","dur"}，None=无
    ramp_start: float = 0.0            # 渐变速度起始倍率（0=关闭渐变，用固定 speed）
    ramp_end: float = 0.0              # 渐变速度结束倍率
    ramp_dur: float = 0.0              # 渐变输出时长（秒）

    kind = "video"

    def timeline_duration(self) -> float:
        """时间轴上占用的长度。渐变速度时用 ramp_dur。"""
        if self.ramp_start > 0 and self.ramp_dur > 0:
            return self.ramp_dur
        if self.duration > 0:
            return self.duration
        src_len = max(self.out_point - self.in_point, 0)
        return src_len / self.speed if self.speed > 0 else src_len

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "in_point": self.in_point,
            "out_point": self.out_point,
            "x": self.x, "y": self.y, "w": self.w, "h": self.h,
            "opacity": self.opacity,
            "transition": self.transition,
            "ramp_start": self.ramp_start,
            "ramp_end": self.ramp_end,
            "ramp_dur": self.ramp_dur,
        })
        return d


@dataclass
class ImageClip(Clip):
    """静态图片片段（png/jpg 等）。无音频，duration 表示停留时长。"""
    x: float = 0.0
    y: float = 0.0
    w: float = 320.0
    h: float = 180.0
    opacity: float = 1.0
    in_point: float = 0.0
    out_point: float = 0.0

    kind = "image"

    def timeline_duration(self) -> float:
        return self.duration

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "x": self.x, "y": self.y, "w": self.w, "h": self.h,
            "opacity": self.opacity,
        })
        return d


@dataclass
class AudioClip(Clip):
    """音频片段（mp3/wav/aac 等）。无画面，只进音频轨。"""
    in_point: float = 0.0              # 源起始秒
    out_point: float = 0.0             # 源结束秒（0 = 到文件末尾）
    fade_in: float = 0.0               # 淡入秒（人性化）
    fade_out: float = 0.0              # 淡出秒（人性化）

    kind = "audio"

    def timeline_duration(self) -> float:
        if self.duration > 0:
            return self.duration
        src_len = max(self.out_point - self.in_point, 0)
        return src_len / self.speed if self.speed > 0 else src_len

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "in_point": self.in_point,
            "out_point": self.out_point,
            "fade_in": self.fade_in,
            "fade_out": self.fade_out,
        })
        return d


# 文字对齐预设
TEXT_ALIGNS = ["top", "center", "bottom"]


@dataclass
class TextClip(Clip):
    """文字/字幕片段：叠加在画面上的文本。无素材（src 可为空字符串）。"""
    text: str = ""
    align: str = "bottom"              # top | center | bottom
    x: float = 0.0                     # 自定义 X（align=custom 时用）
    y: float = 0.0                     # 自定义 Y
    font_size: float = 48.0
    color: str = "#FFFFFF"             # 十六进制颜色
    fade_in: float = 0.0
    fade_out: float = 0.0

    kind = "text"

    def timeline_duration(self) -> float:
        return self.duration

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "text": self.text,
            "align": self.align,
            "x": self.x, "y": self.y,
            "font_size": self.font_size,
            "color": self.color,
            "fade_in": self.fade_in,
            "fade_out": self.fade_out,
        })
        return d


# ------------------------------------------------------------------ 轨道
@dataclass
class Track:
    kind: str = "main"                 # main | overlay | audio | subtitle
    clips: List[Clip] = field(default_factory=list)
    id: str = field(default_factory=new_id)
    visible: bool = True               # 图层可见性（隐藏=不渲染/不显示/不计时长）

    def add(self, clip: Clip) -> Clip:
        """加片段并绑定轨道 id（必须用这个方法，直接 append 会丢 track_id）。"""
        clip.track_id = self.id
        self.clips.append(clip)
        return clip

    def sorted_clips(self) -> List[Clip]:
        return sorted(self.clips, key=lambda c: c.ts)

    def next_adjacent(self, clip: Clip) -> Optional[Clip]:
        """同轨中紧挨着 clip 的下一片段（ts 相邻，无空隙）。"""
        s = self.sorted_clips()
        for i, c in enumerate(s):
            if c.id == clip.id and i + 1 < len(s):
                nxt = s[i + 1]
                if abs(nxt.ts - (c.ts + c.timeline_duration())) < 0.05:
                    return nxt
        return None

    def transition_overlap(self) -> float:
        """本轨所有转场造成的重叠秒数之和（总时长要扣除）。"""
        total = 0.0
        s = self.sorted_clips()
        for i, c in enumerate(s):
            tr = getattr(c, "transition", None)
            if tr and i + 1 < len(s):
                nxt = s[i + 1]
                if abs(nxt.ts - (c.ts + c.timeline_duration())) < 0.05:
                    total += min(float(tr.get("dur", 0)), c.timeline_duration(),
                                 nxt.timeline_duration())
        return total

    def close_gaps(self) -> int:
        """波纹闭合：从第一段起把同轨片段依次紧接（消除空隙），返回移动数。"""
        s = self.sorted_clips()
        cursor = 0.0
        moved = 0
        for c in s:
            if c.ts > cursor + 1e-4:
                c.ts = round(cursor, 3)
                moved += 1
            cursor = max(cursor, c.ts + c.timeline_duration())
        return moved

    def end_time(self) -> float:
        if not self.clips:
            return 0.0
        return max(c.ts + c.timeline_duration() for c in self.clips) \
            - self.transition_overlap()

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "id": self.id,
                "visible": self.visible,
                "clips": [c.to_dict() for c in self.clips]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Track":
        t = cls(kind=d["kind"], id=d.get("id", new_id()),
                visible=d.get("visible", True))
        t.clips = [clip_from_dict(c) for c in d.get("clips", [])]
        return t

    def move(self, delta: int, project: "Project") -> bool:
        """在项目轨道列表中上移/下移（影响画中画堆叠顺序：列表靠后=越上层）。"""
        idx = project.tracks.index(self)
        j = idx + delta
        if j < 0 or j >= len(project.tracks):
            return False
        project.tracks[idx], project.tracks[j] = project.tracks[j], project.tracks[idx]
        return True


# ------------------------------------------------------------------ 时间轴/项目
@dataclass
class Project:
    canvas_w: int = 1920
    canvas_h: int = 1080
    fps: float = 30.0
    tracks: List[Track] = field(default_factory=list)
    name: str = "未命名项目"

    def track(self, kind: str = "main", create: bool = True) -> Optional[Track]:
        for t in self.tracks:
            if t.kind == kind:
                return t
        if create:
            t = Track(kind=kind)
            self.tracks.append(t)
            return t
        return None

    def new_overlay_track(self) -> Track:
        """新建一条叠加轨（PiP 每层一条，互不干扰）。"""
        t = Track(kind="overlay")
        self.tracks.append(t)
        return t

    def new_audio_track(self) -> Track:
        """新建一条音频轨（背景乐/配音层）。"""
        t = Track(kind="audio")
        self.tracks.append(t)
        return t

    def overlay_tracks(self) -> List[Track]:
        return [t for t in self.tracks if t.kind == "overlay"]

    def audio_tracks(self) -> List[Track]:
        return [t for t in self.tracks if t.kind == "audio"]

    def text_tracks(self) -> List[Track]:
        return [t for t in self.tracks if t.kind == "subtitle"]

    def new_text_track(self) -> Track:
        """新建一条文字/字幕轨。"""
        t = Track(kind="subtitle")
        self.tracks.append(t)
        return t

    def all_clips(self) -> List[Clip]:
        return [c for t in self.tracks for c in t.clips]

    def total_duration(self) -> float:
        vis = [t for t in self.tracks if t.visible]
        if not vis:
            return 0.0
        return max((t.end_time() for t in vis), default=0.0)

    # ---------------- 便捷增删 ----------------
    def add_clip(self, clip: Clip, kind: str = "main") -> Clip:
        """把片段加到某类轨道的末尾（按时间顺序）。"""
        track = self.track(kind, create=True)
        clip.track_id = track.id
        clip.ts = track.end_time()
        track.clips.append(clip)
        return clip

    def remove_clip(self, clip_id: str) -> bool:
        for t in self.tracks:
            for c in t.clips:
                if c.id == clip_id:
                    t.clips.remove(c)
                    return True
        return False

    def find_clip(self, clip_id: str) -> Optional[Clip]:
        for t in self.tracks:
            for c in t.clips:
                if c.id == clip_id:
                    return c
        return None

    # ---------------- 序列化 ----------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "name": self.name,
            "canvas_w": self.canvas_w,
            "canvas_h": self.canvas_h,
            "fps": self.fps,
            "tracks": [t.to_dict() for t in self.tracks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Project":
        p = cls(
            canvas_w=d.get("canvas_w", 1920),
            canvas_h=d.get("canvas_h", 1080),
            fps=d.get("fps", 30.0),
            name=d.get("name", "未命名项目"),
        )
        p.tracks = [Track.from_dict(t) for t in d.get("tracks", [])]
        return p

    @classmethod
    def from_json(cls, s: str) -> "Project":
        return cls.from_dict(json.loads(s))


def clip_from_dict(d: Dict[str, Any]) -> Clip:
    kind = d.get("kind", "clip")
    if kind == "video":
        return VideoClip.from_dict(d)
    if kind == "image":
        return ImageClip.from_dict(d)
    if kind == "audio":
        return AudioClip.from_dict(d)
    if kind == "text":
        return TextClip.from_dict(d)
    return Clip.from_dict(d)


# ---------------------------------------------------------------- 滤镜工具
# Clip.effects 里存放 {"type":"filter","brightness":1.0,"contrast":1.0,
#                     "saturation":1.0,"grayscale":false}
DEFAULT_FILTER = {"brightness": 1.0, "contrast": 1.0, "saturation": 1.0,
                  "grayscale": False}


def get_filter(clip: Clip) -> dict:
    """取片段的滤镜参数（无则返回默认值）。"""
    for e in clip.effects or []:
        if isinstance(e, dict) and e.get("type") == "filter":
            return DEFAULT_FILTER | {k: e.get(k) for k in DEFAULT_FILTER}
    return dict(DEFAULT_FILTER)


def set_filter(clip: Clip, brightness=1.0, contrast=1.0, saturation=1.0,
               grayscale=False) -> None:
    """写入/合并滤镜参数（保留其他 effects）。"""
    new = {"type": "filter", "brightness": float(brightness),
           "contrast": float(contrast), "saturation": float(saturation),
           "grayscale": bool(grayscale)}
    clip.effects = [e for e in (clip.effects or [])
                    if not (isinstance(e, dict) and e.get("type") == "filter")]
    # 全默认则不记录（保持干净）
    if abs(brightness - 1.0) > 1e-6 or abs(contrast - 1.0) > 1e-6 or \
            abs(saturation - 1.0) > 1e-6 or grayscale:
        clip.effects.append(new)


def get_filter_from(effects) -> Optional[dict]:
    for e in effects or []:
        if isinstance(e, dict) and e.get("type") == "filter":
            return DEFAULT_FILTER | {k: e.get(k) for k in DEFAULT_FILTER}
    return None


def filter_chain(effects) -> List[str]:
    """把滤镜 effects 变成 ffmpeg 过滤器串（附加到视频链）。"""
    f = get_filter_from(effects)
    if f is None:
        return []
    parts = []
    if abs(f["brightness"] - 1.0) > 1e-6 or abs(f["contrast"] - 1.0) > 1e-6 \
            or abs(f["saturation"] - 1.0) > 1e-6:
        parts.append(
            f"eq=brightness={f['brightness']:.3f}:contrast={f['contrast']:.3f}:"
            f"saturation={f['saturation']:.3f}")
    if f["grayscale"]:
        parts.append("hue=s=0")
    return parts