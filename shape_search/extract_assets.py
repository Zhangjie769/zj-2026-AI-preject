# -*- coding: utf-8 -*-
"""Extract: clean board background + 5 animal sprites, into assets/."""
import os, numpy as np
from PIL import Image
P = r"D:\my_AI_practice\shape_search\pic"
OUT = r"D:\my_AI_practice\shape_search\assets"
os.makedirs(OUT, exist_ok=True)

img1 = Image.open(f"{P}\\img_1.jpg").convert("RGB")
img0 = Image.open(f"{P}\\img_0.jpg").convert("RGB")

# 1) board background (clean grass board) from img_1
board = img1.crop((126, 292, 728, 908))
board.save(os.path.join(OUT, "board.png"))

# 2) codex sprites from img_0 (5 cards). Estimated boxes.
boxes = {
    "duck":    (788, 600, 932, 812),
    "chicken": (930, 600, 1074, 812),
    "unknown": (1072, 600, 1216, 812),
    "boar":    (1214, 600, 1358, 812),
    "deer":    (1356, 600, 1500, 812),
}
for k, b in boxes.items():
    img0.crop(b).save(os.path.join(OUT, f"codex_{k}.png"))

# montage of codex boxes to verify
mw, mh = 144, 212
mont = Image.new("RGB", (mw*5, mh), (30, 30, 30))
for i, (k, b) in enumerate(boxes.items()):
    mont.paste(img0.crop(b), (i*mw, 0))
mont.save(os.path.join(OUT, "_verify_codex.png"))

# 3) white animal from board (mask grass -> transparent)
wcrop = img0.crop((288, 596, 412, 760)).convert("RGBA")
a = np.array(wcrop).astype(int)
R, G, B = a[:,:,0], a[:,:,1], a[:,:,2]
grass = (G > 85) & (B < 85) & (G > R - 40)
a[..., 3] = np.where(grass, 0, 255)
Image.fromarray(a.astype(np.uint8)).save(os.path.join(OUT, "fox.png"))
wcrop.crop((0,0,wcrop.width,wcrop.height)).save(os.path.join(OUT, "_verify_fox.png"))
print("assets saved to", OUT)
print(os.listdir(OUT))
