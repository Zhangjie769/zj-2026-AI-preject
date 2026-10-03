# -*- coding: utf-8 -*-
"""
editor/wave.py —— 音频波形峰值缓存

ffmpeg 把音频解成 8000Hz 单声道 f32le，按 0.05s 窗口算 RMS 峰值，
得到数组 peaks[]（0~1）。磁盘缓存 + 进程内缓存；异步生成回调。
时间轴绘制时按"窗口数/像素宽"把峰值压到像素行画出来。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import struct
import subprocess
import threading

from . import logger as _logmod

log = _logmod.get_logger("wave")

SAMPLE_RATE = 8000
WINDOW_SEC = 0.05   # 每窗口 400 个采样


class WaveCache:
    def __init__(self, cache_dir: str, ffmpeg: str = "ffmpeg"):
        self.cache_dir = cache_dir
        self.ffmpeg = ffmpeg or "ffmpeg"
        os.makedirs(self.cache_dir, exist_ok=True)
        self._mem: dict = {}
        self._q: "queue.Queue" = queue.Queue()
        self._pending: set = set()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()
        self.on_ready = None   # cb(path, peaks:list)

    def _key(self, path: str) -> str:
        try:
            st = os.stat(path)
            sig = f"{os.path.basename(path)}|{st.st_size}|{int(st.st_mtime)}"
        except OSError:
            sig = path
        return hashlib.md5(sig.encode("utf-8", "replace")).hexdigest()[:16]

    def cache_path(self, path: str) -> str:
        return os.path.join(self.cache_dir, self._key(path) + ".peaks.json")

    # ---------------- 同步计算 ----------------
    def compute(self, path: str, max_sec: float = 7200) -> list:
        mem = self._mem.get(path)
        if mem is not None:
            return mem
        cpath = self.cache_path(path)
        if os.path.isfile(cpath):
            try:
                with open(cpath, "r", encoding="utf-8") as f:
                    mem = json.load(f)
                self._mem[path] = mem
                return mem
            except Exception:
                pass
        try:
            mem = self._compute_fresh(path, max_sec)
        except Exception as e:
            log.warning("波形计算失败 %s: %s", path, e)
            mem = []
        self._mem[path] = mem
        if mem:
            try:
                with open(cpath, "w", encoding="utf-8") as f:
                    json.dump(mem, f)
            except Exception as e:
                log.debug("波形缓存写盘失败: %s", e)
        return mem

    def _compute_fresh(self, path: str, max_sec: float) -> list:
        """解出 f32le 单声道，按窗口算 RMS。"""
        n_win = int(min(max_sec, 7200) / WINDOW_SEC)
        cmd = [self.ffmpeg, "-v", "error", "-nostdin", "-i", path,
               "-ac", "1", "-ar", str(SAMPLE_RATE),
               "-t", f"{min(max_sec, 7200):.0f}",
               "-f", "f32le", "-"]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        block = WINDOW_SEC * SAMPLE_RATE
        steps = max(block, int(SAMPLE_RATE * 0.05))
        peaks = []
        buf = b""
        try:
            while proc.poll() is None:
                chunk = proc.stdout.read(4096 * 4)
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= int(block) * 4:
                    wins = buf[: int(block) * 4]
                    buf = buf[int(block) * 4:]
                    samples = struct.unpack(f"<{len(wins)//4}f", wins)
                    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
                    peaks.append(min(1.0, rms * 4.0))
                    if len(peaks) >= n_win:
                        proc.kill()
                        break
        finally:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        return peaks

    # ---------------- 异步 ----------------
    def request(self, path: str) -> None:
        if path in self._mem or path in self._pending:
            return
        self._pending.add(path)
        self._q.put(path)

    def _loop(self):
        while True:
            try:
                path = self._q.get(timeout=2)
            except queue.Empty:
                continue
            try:
                peaks = self.compute(path)
            finally:
                self._pending.discard(path)
            if peaks and self.on_ready:
                try:
                    self.on_ready(path, peaks)
                except Exception as e:
                    log.warning("波形回调失败: %s", e)