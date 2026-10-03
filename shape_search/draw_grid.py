# -*- coding: utf-8 -*-
import numpy as np
from PIL import Image, ImageDraw
P = r"D:\my_AI_practice\shape_search\pic"
im = Image.open(f"{P}\\img_0.jpg").convert("RGB")
d = ImageDraw.Draw(im)
xs = [126, 212, 298, 384, 470, 556, 642, 728]
ys = [292, 380, 468, 556, 644, 732, 820, 908]
for x in xs:
    d.line([(x, ys[0]), (x, ys[-1])], fill=(255, 0, 255), width=2)
for y in ys:
    d.line([(xs[0], y), (xs[-1], y)], fill=(255, 0, 255), width=2)
for ci in range(7):
    for rj in range(7):
        d.text((xs[ci] + 4, ys[rj] + 3), f"{rj},{ci}", fill=(255, 255, 0))
im.crop((110, 280, 745, 920)).resize((635 * 2, 640 * 2)).save(f"{P}\\overlay1.png")
# lower-left zoom
im.crop((120, 540, 500, 915)).resize((380 * 3, 375 * 3)).save(f"{P}\\overlay_ll.png")
# right zoom (deer)
im.crop((540, 540, 745, 915)).resize((205 * 3, 375 * 3)).save(f"{P}\\overlay_deer.png")
print("saved")
