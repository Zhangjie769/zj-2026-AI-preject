# -*- coding: utf-8 -*-
"""preview: WAV 缓存（修正 cleanup 锚点）"""
import io

p = r"D:\my_AI_practice\video_cut\editor\preview.py"
src = io.open(p, encoding="utf-8").read()

def rep(old, new, anchor):
    assert old in src, f"missing: {anchor}"
    return src.replace(old, new, 1)

rep(
    "        self._wav = None\n        self._sf = None\n        self._vol = 1.0",
    "        self._wav = None\n        self._sf = None\n        self._vol = 1.0\n"
    "        self._cache = {}      # (src,in,out,spd,vol) -> wav 路径（同参数不重解）",
    "cache attr")

rep(
    '''    def prepare(self, src: str, in_pt: float, out_len: float,
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
    "prepare cache")

rep(
    '''            if os.path.getsize(wav) < 1024:
                os.remove(wav)
                return None
            return wav
        except Exception as e:
            log.error("音频解码失败 %s: %s", src, e)
            return None''',
    '''            if os.path.getsize(wav) < 1024:
                os.remove(wav)
                return None
            if len(self._cache) >= 3:    # LRU 上限 3 份
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = wav
            return wav
        except Exception as e:
            log.error("音频解码失败 %s: %s", src, e)
            return None''',
    "cache store")

rep(
    "    def cleanup(self):\n        self.stop()\n        self.stop_overlays()\n        self.audio.cleanup()",
    "    def clear_cache(self):\n        for w in self._cache.values():\n            try:\n                os.remove(w)\n            except Exception:\n                pass\n        self._cache.clear()\n\n"
    "    def cleanup(self):\n        self.stop()\n        self.stop_overlays()\n        self.audio.cleanup()",
    "cleanup")

io.open(p, "w", encoding="utf-8", newline="\n").write(src)
check = io.open(p, encoding="utf-8").read()
assert "clear_cache" in check and "min(out_len, 1200.0)" in check
print("WAV CACHE OK")