# -*- coding: utf-8 -*-
from PIL import Image, ImageDraw
P = r"D:\my_AI_practice\shape_search\pic"
im = Image.open(f"{P}\\img_0.jpg").convert("RGB")
d = ImageDraw.Draw(im)
xs = [126, 212, 298, 384, 470, 556, 642, 728]
ys = [292, 380, 468, 556, 644, 732, 820, 908]
for x in xs:
    d.line([(x, ys[0]), (x, ys[-1])], fill=(0, 255, 255), width=2)
for y in ys:
    d.line([(xs[0], y), (xs[-1], y)], fill=(0, 255, 255), width=2)
for ci in range(7):
    for rj in range(7):
        d.text((xs[ci] + 6, ys[rj] + 6), f"{rj},{ci}", fill=(255, 255, 0))
im.crop((212, 556, 470, 908)).resize((258 * 4, 352 * 4)).save(f"{P}\\zoom_w2.png")
print("ok")
