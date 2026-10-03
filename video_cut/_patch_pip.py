# -*- coding: utf-8 -*-
"""preview: 画中画(PiP)实时叠加合成（bbox装毛，来真画面）"""
import io

p = r"D:\my_AI_practice\video_cut\editor\preview.py"
src = io.open(p, encoding="utf-8").read()

# 1) init: 叠加层容器
old = '''        self._photo = None
        self._frame_img = None
        self._ended = False'''
new = '''        self._photo = None
        self._frame_img = None
        self._ended = False
        self._overlays = {}          # key -> [proc, thread, queue, last_img]'''
assert old in src, "init anchor"
src = src.replace(old, new)

# 2) set_overlays：按 (clip_id, gen) 差分启停
old = '''    def _stop_all(self):
        if self._proc is not None:'''
new = '''    def set_overlays(self, specs):
        """specs: [{id, src, in_pt, len, speed, x_frac, y_frac, w_frac, h_frac}]"""
        want = {f"{s['id']}|{self._gen}": s for s in specs}
        for k in list(self._overlays.keys()):
            if k not in want:
                self._stop_overlay(k)
        for k, s in want.items():
            if k not in self._overlays:
                self._start_overlay(k, s)

    def _start_overlay(self, key, s):
        try:
            tw = max(int(self.w * s["w_frac"]), 60)
            th = max(int(self.h * s["h_frac"]), 40)
            cmd = [self.ffmpeg, "-v", "error", "-nostdin", "-threads", "2",
                   "-ss", f"{s['in_pt']:.3f}", "-i", s["src"],
                   "-t", f"{max(s['len'], 0.05):.3f}", "-an", "-sn",
                   "-vf", (f"scale={tw}:{th}:force_original_aspect_ratio=decrease"
                           f":flags=lanczos,setsar=1"),
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
        """把叠加流画面合成到主帧上（RGBA 粘贴）。"""
        if not self._overlays:
            return img
        base = img.convert("RGBA")
        for k, entry in self._overlays.items():
            q = entry[2]
            last = entry[3]
            try:
                got = q.get_nowait()
                entry[3] = got
                last = got
            except queue.Empty:
                pass
            if last is None:
                continue
            parts = k.split("|")
            if len(parts) == 2:
                _cid = parts[0]
            # 位置从 spec 恢复：利用已存 spec
            spec = getattr(self, "_ov_spec", {}).get(k)
            if spec is None:
                continue
            ov = last.convert("RGBA")
            x = int(spec["x_frac"] * self.w)
            y = int(spec["y_frac"] * self.h)
            base.alpha_composite(ov, (x, y))
        return base.convert("RGB")

    def _stop_all(self):
        if self._proc is not None:'''
assert old in src, "overlay anchor"
src = src.replace(old, new)

# 3) spec 记录 + _show 合成
old = '''    def _show(self, img):
        self._frame_img = img
        self._photo = ImageTk.PhotoImage(img)'''
new = '''    def _show(self, img):
        img = self._composite(img)
        self._frame_img = img
        self._photo = ImageTk.PhotoImage(img)'''
assert old in src, "show anchor"
src = src.replace(old, new)

# 4) set_overlays 记得 spec 缓存
old = '''        want = {f"{s['id']}|{self._gen}": s for s in specs}
        for k in list(self._overlays.keys()):'''
new = '''        want = {f"{s['id']}|{self._gen}": s for s in specs}
        self._ov_spec = dict(want)
        for k in list(self._overlays.keys()):'''
assert old in src, "spec anchor"
src = src.replace(old, new)

# 5) 换主流(seek)时叠加层自动随 gen 重启；stop/cleanup 收尾叠加层
old = '''        if old is not None and old is not proc:
            threading.Thread(target=self._reap, args=(old,), daemon=True).start()'''
new = '''        if old is not None and old is not proc:
            threading.Thread(target=self._reap, args=(old,), daemon=True).start()
        # 叠加层随 gen 失效，由下一次 set_overlays 重建
        for k in list(self._overlays.keys()):
            if not k.endswith(f"|{gen}"):
                self._stop_overlay(k)'''
assert old in src, "reap anchor"
src = src.replace(old, new)

old = '''    def cleanup(self):
        self.stop()
        self.audio.cleanup()'''
new = '''    def cleanup(self):
        self.stop()
        for k in list(self._overlays.keys()):
            self._stop_overlay(k)
        self.audio.cleanup()

    def stop_overlays(self):
        for k in list(self._overlays.keys()):
            self._stop_overlay(k)'''
assert old in src, "cleanup anchor"
src = src.replace(old, new)

io.open(p, "w", encoding="utf-8", newline="\n").write(src)
print("PIP COMPOSITE PATCHED OK")