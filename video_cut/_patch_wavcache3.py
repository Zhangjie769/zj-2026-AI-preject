# -*- coding: utf-8 -*-
"""探针版补丁"""
import io, sys

p = r"D:\my_AI_practice\video_cut\editor\preview.py"
src = io.open(p, encoding="utf-8").read()
print("len before:", len(src), file=sys.stderr)

def rep(old, new, anchor):
    global src
    if old not in src:
        print("REP FAIL:", anchor, file=sys.stderr)
        return False
    src = src.replace(old, new, 1)
    print("REP OK:", anchor, file=sys.stderr)
    return True

rep("        self._wav = None\n        self._sf = None\n        self._vol = 1.0",
    "        self._wav = None\n        self._sf = None\n        self._vol = 1.0\n"
    "        self._cache = {}      # (src,in,out,spd,vol) -> wav 路径（同参数不重解）",
    "attr")

rep('''    def prepare(self, src: str, in_pt: float, out_len: float,
                speed: float, volume: float) -> str | None:
        try:
            fd, wav = tempfile.mkstemp(suffix=".wav", prefix="vcp_aud_")
            os.close(fd)''',
    '''    def prepare(self, src: str, in_pt: float, out_len: float,
                speed: float, volume: float) -> str | None:
        key = (src, round(in_pt, 3), round(out_len, 3),
               round(speed, 3), round(volume, 3))
        cached = self._cache.get(key)
        if cached and os.path.isfile(cached):
            return cached
        out_len = min(out_len, 1200.0)   # 预览音频最长准备 20 分钟
        try:
            fd, wav = tempfile.mkstemp(suffix=".wav", prefix="vcp_aud_")
            os.close(fd)''',
    "prepare")

rep('''            if os.path.getsize(wav) < 1024:
                os.remove(wav)
                return None
            return wav
        except Exception as e:
            log.error("音频解码失败 %s: %s", src, e)
            return None''',
    '''            if os.path.getsize(wav) < 1024:
                os.remove(wav)
                return None
            if len(self._cache) >= 3:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = wav
            return wav
        except Exception as e:
            log.error("音频解码失败 %s: %s", src, e)
            return None''',
    "store")

rep("    def cleanup(self):\n        self.stop()\n        self.stop_overlays()\n        self.audio.cleanup()",
    "    def clear_cache(self):\n        for w in self._cache.values():\n            try:\n                os.remove(w)\n            except Exception:\n                pass\n        self._cache.clear()\n\n"
    "    def cleanup(self):\n        self.stop()\n        self.stop_overlays()\n        self.audio.cleanup()",
    "cleanup")

io.open(p, "w", encoding="utf-8", newline="\n").write(src)
check = io.open(p, encoding="utf-8").read()
print("clear_cache in file:", "clear_cache" in check, file=sys.stderr)
print("min(out_len in file:", "min(out_len, 1200.0)" in check, file=sys.stderr)
print("len after:", len(check), file=sys.stderr)