# -*- coding: utf-8 -*-
"""
editor/thumbs.py —— 素材缩略图缓存

- 视频：ffmpeg 抽取 0.5s 处一帧，缩到 96px 宽（PNG）
- 图片：PIL 直接缩略
- 音频：生成带音符的渐变占位图
磁盘缓存：thumbs_cache/ 下按 路径+大小+修改时间 的哈希命名，避免反复抓帧。
异步：request() 入队，后台线程生成，完成后回调（UI 线程）。
"""
from __future__ import annotations

import hashlib
import os
import queue
import subprocess
import tempfile
import threading

from PIL import Image, ImageDraw

from . import logger as _logmod

log = _logmod.get_logger("thumbs")

THUMB_W = 96
THUMB_H = 54


class ThumbCache:
    def __init__(self, cache_dir: str, ffmpeg: str = "ffmpeg"):
        self.cache_dir = cache_dir
        self.ffmpeg = ffmpeg or "ffmpeg"
        os.makedirs(self.cache_dir, exist_ok=True)
        self._q: "queue.Queue" = queue.Queue()
        self._pending: set = set()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()
        self.on_ready = None   # cb(path, pil_image)

    # ---------------- 缓存键 ----------------
    def _key(self, path: str) -> str:
        try:
            st = os.stat(path)
            sig = f"{os.path.basename(path)}|{st.st_size}|{int(st.st_mtime)}"
        except OSError:
            sig = path
        return hashlib.md5(sig.encode("utf-8", "replace")).hexdigest()[:16]

    def cache_path(self, path: str) -> str:
        return os.path.join(self.cache_dir, self._key(path) + ".png")

    # ---------------- 同步生成 ----------------
    def generate(self, path: str, kind: str = "video") -> Image.Image | None:
        """同步生成缩略图（失败返回 None）。"""
        out = self.cache_path(path)
        if os.path.isfile(out):
            try:
                return Image.open(out).copy()
            except Exception:
                pass
        try:
            if kind == "image":
                im = Image.open(path).convert("RGBA")
                im.thumbnail((THUMB_W, THUMB_H))
            elif kind == "audio":
                im = self._audio_placeholder(path)
            else:
                im = self._extract_frame(path)
            if im is None:
                return None
            im.save(out, "PNG")
            return im
        except Exception as e:
            log.warning("缩略图生成失败 %s: %s", path, e)
            return None

    def _extract_frame(self, path: str) -> Image.Image | None:
        """ffmpeg 抓一帧（0.5s 处，避免黑场开头）。"""
        fd, tmp = tempfile.mkstemp(suffix=".png", prefix="vcp_th_")
        os.close(fd)
        try:
            cmd = [self.ffmpeg, "-v", "error", "-nostdin",
                   "-ss", "0.5", "-i", path,
                   "-frames:v", "1",
                   "-vf", f"scale={THUMB_W}:-2:force_original_aspect_ratio=decrease",
                   "-y", tmp]
            subprocess.run(cmd, capture_output=True, timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if os.path.getsize(tmp) < 200:
                return None
            im = Image.open(tmp).convert("RGB")
        except Exception:
            im = None
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return im

    def _audio_placeholder(self, path: str) -> Image.Image:
        im = Image.new("RGB", (THUMB_W, THUMB_H), (46, 74, 96))
        d = ImageDraw.Draw(im)
        try:
            from PIL import ImageFont
            f = ImageFont.load_default()
            d.text((10, 14), "♪", fill=(200, 220, 240), font=f)
        except Exception:
            d.rectangle((10, 10, 30, 40), fill=(180, 200, 220))
        return im

    # ---------------- 异步 ----------------
    def request(self, path: str, kind: str) -> None:
        if path in self._pending:
            return
        self._pending.add(path)
        self._q.put((path, kind))

    def _loop(self):
        while True:
            try:
                path, kind = self._q.get(timeout=2)
            except queue.Empty:
                continue
            try:
                im = self.generate(path, kind)
            finally:
                self._pending.discard(path)
            if im is not None and self.on_ready:
                try:
                    self.on_ready(path, im)
                except Exception as e:
                    log.warning("缩略图回调失败: %s", e)