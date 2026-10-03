# -*- coding: utf-8 -*-
"""
editor/preview.py —— 应用内播放器（画面 + 音频）v4

画面：ffmpeg rawvideo 帧流 → Pillow → tkinter Canvas（后台读帧线程）
音频：ffmpeg 解码临时 WAV → sounddevice + soundfile 流式播放（缺库自动降级纯画面）

v4 优化（预览流畅度）：
  - 帧带"代次(generation)"标记：seek 时生成新代次并立即打开新进程，
    旧进程在第一帧到达后由后台线程收尾，避免 seek 期间黑洞
  - 播放位置按墙钟推进（音频为准），画面尽力跟上
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import tempfile
import threading
import time as _time

from PIL import Image, ImageTk

RAW_FORMAT = "rgb24"

log = __import__("logging").getLogger("vc.preview")


# ================================================================ 音频引擎
class AudioEngine:
    """WAV 流式播放：sf 读块 → sounddevice 回调，支持暂停/seek/音量。"""

    def __init__(self, ffmpeg: str):
        self.ffmpeg = ffmpeg
        try:
            import sounddevice as sd  # noqa: F401
            import soundfile as sf   # noqa: F401
            self.available = True
        except Exception as e:
            self.available = False
            log.warning("音频预览库不可用（sounddevice/soundfile）: %s", e)
        self._stream = None
        self._thread = None
        self._q: "queue.Queue" = queue.Queue(maxsize=128)
        self._stop_evt = threading.Event()
        self._playing = False
        self._pos = 0.0
        self._wav = None
        self._sf = None
        self._vol = 1.0
        self._cache = {}      # (src,in,out,spd,vol) -> wav 路径（同参数不重解）

    def prepare(self, src: str, in_pt: float, out_len: float,
                speed: float, volume: float) -> str | None:
        key = (src, round(in_pt, 3), round(out_len, 3),
               round(speed, 3), round(volume, 3))
        cached = self._cache.get(key)
        if cached and os.path.isfile(cached):
            return cached
        out_len = min(out_len, 1200.0)   # 预览音频最长准备 20 分钟
        try:
            fd, wav = tempfile.mkstemp(suffix=".wav", prefix="vcp_aud_")
            os.close(fd)
            af = []
            if abs(speed - 1.0) > 1e-3:
                s = speed
                while s > 2.0:
                    af.append("atempo=2.0")
                    s /= 2.0
                while s < 0.5:
                    af.append("atempo=0.5")
                    s /= 0.5
                af.append(f"atempo={s:.4f}")
            af.append(f"volume={max(volume, 0.0):.3f}")
            cmd = [self.ffmpeg, "-v", "error", "-nostdin",
                   "-ss", f"{in_pt:.3f}", "-i", src,
                   "-t", f"{out_len:.3f}",
                   "-af", ",".join(af),
                   "-ar", "44100", "-ac", "2", "-f", "wav", wav]
            subprocess.run(cmd, capture_output=True, timeout=600,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if os.path.getsize(wav) < 1024:
                os.remove(wav)
                return None
            if len(self._cache) >= 3:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = wav
            return wav
        except Exception as e:
            log.error("音频解码失败 %s: %s", src, e)
            return None

    def play(self, wav_path: str, start_sec: float = 0.0,
             volume: float = 1.0):
        self.stop()
        try:
            import sounddevice as sd
            import soundfile as sf
        except Exception as e:
            log.warning("无法播放音频（缺库）: %s", e)
            return
        try:
            self._stop_evt.clear()
            self._sf = sf.SoundFile(wav_path)
            self._sf.seek(int(start_sec * self._sf.samplerate))
            self._pos = start_sec
            self._vol = volume
            self._wav = wav_path

            def cb(outdata, frames, _t, status):
                if self._stop_evt.is_set():
                    outdata.fill(0)
                    return
                try:
                    data = self._q.get_nowait()
                except queue.Empty:
                    outdata.fill(0)
                    return
                n = min(len(data), frames)
                outdata[:n] = data[:n] * self._vol
                outdata[n:] = 0

            self._stream = sd.OutputStream(
                samplerate=self._sf.samplerate, channels=self._sf.channels,
                dtype="float32", callback=cb, blocksize=2048)
            self._stream.start()
            self._thread = threading.Thread(target=self._producer, daemon=True)
            self._thread.start()
            self._playing = True
        except Exception as e:
            log.error("音频播放启动失败: %s", e)
            self._playing = False

    def _producer(self):
        try:
            for block in self._sf.blocks(blocksize=2048, dtype="float32"):
                if self._stop_evt.is_set():
                    break
                if self._q.full():
                    try:
                        self._q.get_nowait()
                    except queue.Empty:
                        pass
                self._q.put(block)
        except Exception as e:
            log.debug("音频读块结束: %s", e)

    def pause(self):
        self._playing = False
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception:
                pass

    def resume(self):
        if self._playing or self._wav is None:
            return
        self._playing = True
        if self._stream is not None:
            try:
                self._stream.start()
            except Exception as e:
                log.warning("音频恢复失败: %s", e)

    def seek(self, sec: float):
        if self._wav and os.path.isfile(self._wav):
            was = self._playing
            self.play(self._wav, start_sec=max(0.0, sec), volume=self._vol)
            if not was:
                self.pause()

    def stop(self):
        self._playing = False
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._sf is not None:
            try:
                self._sf.close()
            except Exception:
                pass
            self._sf = None

    def cleanup(self):
        self.stop()
        if self._wav and os.path.isfile(self._wav):
            try:
                os.remove(self._wav)
            except Exception:
                pass
            self._wav = None


# ================================================================ 播放器
class PreviewPlayer:
    def __init__(self, canvas: "tk.Canvas", ffmpeg: str = "ffmpeg",
                 ffprobe: str = ""):
        self.canvas = canvas
        self.ffmpeg = ffmpeg
        self.audio = AudioEngine(ffmpeg)
        self._q: "queue.Queue" = queue.Queue(maxsize=4)
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._gen = 0              # 帧代次（seek 时 +1）
        self._next_proc = None     # seek 预热的下一进程
        self._next_gen = -1

        self._playing = False
        self._pos = 0.0
        self._speed = 1.0
        self._fps = 30.0
        self._last_tick = 0.0
        self.w = 320
        self.h = 180
        self._src_in = 0.0
        self._src_len = 0.0
        self._path = None
        self._audio_spec = None
        self._aud_wav = None
        self.on_tick = None
        self.on_state = None
        self._photo = None
        self._frame_img = None
        self._ended = False
        self._overlays = {}          # key -> [proc, thread, queue, last_img]

    # ------------------------------------------------------------ 控制
    def load(self, path: str, src_in: float, src_len: float,
             speed: float = 1.0, target_w: int = 0, target_h: int = 0,
             audio_src: str | None = None,
             audio_in: float = 0.0, audio_len: float = 0.0,
             audio_vol: float = 1.0):
        self._stop_all()
        self.audio.stop()
        if self._aud_wav:
            self.audio.cleanup()
            self._aud_wav = None
        self._path = path
        self._src_in = src_in
        self._src_len = max(src_len, 0.1)
        self._speed = speed if speed > 0 else 1.0
        self._pos = 0.0
        self._ended = False
        self._fps = self._probe_fps(path) or 30.0
        self._interlaced = getattr(self, "_interlaced", False)
        self._last_tick = _time.monotonic()

        _sz, self._interlaced = self._probe_video(path)
        w, h = self._fit_keep_aspect(path, target_w, target_h)
        self.w, self.h = w, h
        self._gen += 1
        self._open_stream(self._gen)
        self.draw_text_center("加载中…")

        if audio_src is not None:
            if not audio_len:
                audio_len = src_len
            self._aud_wav = self.audio.prepare(
                audio_src, audio_in, audio_len, speed, audio_vol)
            self._audio_spec = (self._aud_wav, 0.0, audio_vol)
        else:
            self._audio_spec = None
        if self.on_state:
            self.on_state("paused", "")

    def play(self):
        if self._ended:
            self.seek(0.0)
            return
        self._playing = True
        self._last_tick = _time.monotonic()
        if self._audio_spec and self._audio_spec[0]:
            self.audio.resume()
            if not self.audio._playing and self._pos > 0:
                self.audio.play(self._audio_spec[0], self._pos,
                                self._audio_spec[2])
        if self.on_state:
            self.on_state("playing", "")

    def pause(self):
        self._playing = False
        self.audio.pause()
        if self.on_state:
            self.on_state("paused", "")

    def stop(self):
        self._playing = False
        self.audio.stop()
        self._stop_all()
        if self.on_state:
            self.on_state("paused", "")

    def seek(self, timeline_sec: float):
        """快速 seek：新开进程预热，旧进程等第一帧后由后台收尾。"""
        if self._path is None:
            return
        self._pos = max(0.0, min(timeline_sec, self.total()))
        self._last_tick = _time.monotonic()
        was = self._playing
        self._playing = False
        self._gen += 1
        self._open_stream(self._gen)
        if self._audio_spec and self._audio_spec[0]:
            self.audio.seek(self._pos)
        self._playing = was
        if was:
            self._last_tick = _time.monotonic()
        if self.on_tick:
            self.on_tick(self._pos)

    def total(self) -> float:
        return self._src_len / self._speed

    def _has_video(self) -> bool:
        return (self._path is not None and
                os.path.splitext(self._path)[1].lower() not in (
                    ".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg", ".opus"))

    # ------------------------------------------------------------ 内部
    def _open_stream(self, gen: int):
        """开一个新的解码管线（代次 gen）。旧管线延迟收尾。"""
        if self._path is None or not self._has_video():
            return
        src_sec = self._src_in + self._pos * self._speed
        remain = self._src_len - self._pos * self._speed
        if remain <= 0:
            self._ended = True
            self._playing = False
            if self.on_state:
                self.on_state("ended", "")
            return
        vf = []
        if getattr(self, "_interlaced", False):
            vf.append("yadif=1")
        vf.append(f"scale={self.w}:{self.h}:force_original_aspect_ratio=decrease:flags=lanczos")
        vf.append("setsar=1")
        if abs(self._speed - 1.0) > 1e-3:
            vf.append(f"setpts=PTS/{self._speed:.4f}")
        cmd = [self.ffmpeg, "-v", "error", "-nostdin", "-threads", "2",
               "-ss", f"{src_sec:.3f}", "-i", self._path,
               "-t", f"{remain:.3f}", "-an", "-sn",
               "-vf", ",".join(vf),
               "-f", "rawvideo", "-pix_fmt", RAW_FORMAT, "-"]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            log.error("预览解码启动失败: %s", e)
            return
        th = threading.Thread(target=self._reader, args=(proc, gen), daemon=True)
        old = self._proc
        self._proc = proc
        self._thread = th
        th.start()
        if old is not None and old is not proc:
            threading.Thread(target=self._reap, args=(old,), daemon=True).start()
        # 叠加层随 gen 失效，由下一次 set_overlays 重建
        for k in list(self._overlays.keys()):
            if not k.endswith(f"|{gen}"):
                self._stop_overlay(k)

    def _reap(self, proc):
        """后台收尾旧进程。"""
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            pass

    def _reader(self, proc, gen: int):
        frame_bytes = self.w * self.h * 3
        buf = b""
        try:
            while True:
                # 攒满一帧字节再拼图，避免管道分片导致错位乱码
                while len(buf) < frame_bytes:
                    chunk = proc.stdout.read(frame_bytes - len(buf))
                    if not chunk:
                        return
                    buf += chunk
                img = Image.frombytes("RGB", (self.w, self.h), buf)
                buf = b""
                if self._q.full():
                    try:
                        self._q.get_nowait()
                    except queue.Empty:
                        pass
                self._q.put((gen, img))
        except Exception as e:
            log.debug("预览读帧线程退出: %s", e)
        finally:
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass

    def tick(self):
        """UI 每帧调用；播放位置由墙钟推进（音频为准）。"""
        if not self._playing:
            return False
        now = _time.monotonic()
        self._pos += now - self._last_tick
        self._last_tick = now
        if self._pos >= self.total():
            self._pos = self.total()
            self._playing = False
            self.audio.pause()
            self._ended = True
            if self.on_state:
                self.on_state("ended", "")
        if self.on_tick:
            self.on_tick(self._pos)
        try:
            gen, img = self._q.get_nowait()
            if gen == self._gen:
                self._show(img)
        except queue.Empty:
            return False
        return True

    def _show(self, img):
        img = self._composite(img)
        self._frame_img = img
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("frame")
        self.canvas.create_image(
            self.canvas.winfo_width() // 2 or self.w // 2,
            self.canvas.winfo_height() // 2 or self.h // 2,
            image=self._photo, tags="frame")

    def draw_text_center(self, text: str, color="#888"):
        self.canvas.delete("frame", "hint")
        w = self.canvas.winfo_width() or 400
        h = self.canvas.winfo_height() or 260
        self.canvas.create_text(w // 2, h // 2, text=text, fill=color,
                                font=("Microsoft YaHei UI", 12), tags="hint")

    def _fit_size(self, target_w, target_h):
        if target_w <= 0 or target_h <= 0:
            target_w, target_h = 960, 540
        return target_w, target_h

    def _fit_keep_aspect(self, path, target_w, target_h):
        """按源视频宽高比适配预览尺寸（竖屏/横屏都不变形）。"""
        tw, th = self._fit_size(target_w, target_h)
        sw, sh = self._probe_size(path)
        if sw > 0 and sh > 0:
            scale = min(tw / sw, th / sh)
            nw = int(sw * scale)
            nh = int(sh * scale)
            nw -= nw % 2
            nh -= nh % 2
            if nw >= 4 and nh >= 4:
                return nw, nh
        return tw, th

    def set_overlays(self, specs):
        """specs: [{id, src, in_pt, len, speed, x_frac, y_frac, w_frac, h_frac}]"""
        want = {f"{s['id']}|{self._gen}": s for s in specs}
        self._ov_spec = dict(want)
        for k in list(self._overlays.keys()):
            if k not in want:
                self._stop_overlay(k)
        for k, s in want.items():
            if k not in self._overlays:
                self._start_overlay(k, s)

    def _start_overlay(self, key, s):
        try:
            tw = max(int(self.w * s["w_frac"] * 2), 120)   # 2x 超采样解码
            th = max(int(self.h * s["h_frac"] * 2), 80)
            is_img = os.path.splitext(s["src"])[1].lower() in (
                ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
            vf = (f"scale={tw}:{th}:force_original_aspect_ratio=decrease"
                  f":flags=lanczos,setsar=1")
            if is_img:
                # 图片源：-loop 1 循环出帧（-ss 对静态图无效）
                cmd = [self.ffmpeg, "-v", "error", "-nostdin", "-threads", "2",
                       "-loop", "1", "-framerate", "30", "-i", s["src"],
                       "-t", f"{max(s['len'], 0.05):.3f}",
                       "-vf", vf,
                       "-f", "rawvideo", "-pix_fmt", RAW_FORMAT, "-"]
            else:
                cmd = [self.ffmpeg, "-v", "error", "-nostdin", "-threads", "2",
                       "-ss", f"{s['in_pt']:.3f}", "-i", s["src"],
                       "-t", f"{max(s['len'], 0.05):.3f}", "-an", "-sn",
                       "-vf", vf,
                       "-f", "rawvideo", "-pix_fmt", RAW_FORMAT, "-"]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            log.warning("叠加流启动失败: %s", e)
            return
        q: "queue.Queue" = queue.Queue(maxsize=2)
        th = threading.Thread(target=self._overlay_reader,
                              args=(proc, q, tw, th), daemon=True)
        th.start()
        self._overlays[key] = [proc, th, q, None]

    def _overlay_reader(self, proc, q, tw, th):
        fb = tw * th * 3
        buf = b""
        try:
            while True:
                while len(buf) < fb:
                    ch = proc.stdout.read(fb - len(buf))
                    if not ch:
                        return
                    buf += ch
                img = Image.frombytes("RGB", (tw, th), buf)
                buf = b""
                if q.full():
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                q.put(img)
        except Exception:
            pass
        finally:
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass

    def _stop_overlay(self, key):
        entry = self._overlays.pop(key, None)
        if entry:
            try:
                entry[0].kill()
            except Exception:
                pass
            if entry[1] is not None:
                entry[1].join(timeout=0.6)

    def _composite(self, img):
        if not self._overlays:
            return img
        base = img.convert("RGBA")
        for k, entry in self._overlays.items():
            last = entry[3]
            try:
                got = entry[2].get_nowait()
                entry[3] = got
                last = got
            except queue.Empty:
                pass
            if last is None:
                continue
            spec = getattr(self, "_ov_spec", {}).get(k)
            if spec is None:
                continue
            # 2x 超采样帧 → LANCZOS 缩到目标尺寸再贴，边缘不锯齿
            tw = max(int(self.w * spec.get("w_frac", 0.2)), 4)
            th = max(int(self.h * spec.get("h_frac", 0.2)), 4)
            ov = last
            if ov.size != (tw, th):
                ov = ov.resize((tw, th), Image.LANCZOS)
            ov = ov.convert("RGBA")
            x = int(spec["x_frac"] * self.w)
            y = int(spec["y_frac"] * self.h)
            base.alpha_composite(ov, (x, y))
        return base.convert("RGB")

    def has_overlays(self) -> bool:
        return bool(self._overlays)

    def reframe(self):
        if self._frame_img is not None:
            try:
                self._show(self._frame_img)
            except Exception as e:
                log.debug("reframe 失败: %s", e)

    def stop_overlays(self):
        for k in list(self._overlays.keys()):
            self._stop_overlay(k)

    def _stop_all(self):
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def _probe_size(self, path: str):
        """从 ffmpeg -i 解析源视频尺寸（宽,高，失败返回 0,0）。"""
        s, _i = self._probe_video(path)
        return s

    def _probe_video(self, path: str):
        """解析 源尺寸(宽,高) 与 是否隔行(interlaced)。"""
        try:
            r = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-nostdin", "-i", path],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60)
            err = r.stderr or ""
            m = re.search(r"Stream #\d+:\d+.*Video:.*?(\d{2,5})x(\d{2,5})",
                          err)
            interlaced = bool(re.search(r"Stream #\d+:\d+.*Video:.*(tff|bff)",
                                        err))
            if m:
                return (int(m.group(1)), int(m.group(2))), interlaced
        except Exception:
            pass
        return (0, 0), False

    def _probe_fps(self, path: str) -> float:
        """从 ffmpeg -i 输出解析 fps（不依赖 ffprobe）。"""
        try:
            r = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-nostdin", "-i", path],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60)
            m = re.search(r"Stream #\d+:\d+.*Video:.*?([\d.]+)\s*fps",
                          r.stderr or "")
            if m:
                return float(m.group(1))
        except Exception:
            pass
        return 30.0

    def clear_cache(self):
        for w in self._cache.values():
            try:
                os.remove(w)
            except Exception:
                pass
        self._cache.clear()

    def cleanup(self):
        self.stop()
        self.stop_overlays()
        self.audio.cleanup()