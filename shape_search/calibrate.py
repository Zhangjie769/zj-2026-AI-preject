# -*- coding: utf-8 -*-
import numpy as np
from PIL import Image
P = r"D:\my_AI_practice\shape_search\pic"
a = np.asarray(Image.open(f"{P}\\img_1.jpg").convert("RGB")).astype(int)
R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
green = (G > 90) & (B < 75) & (G > R - 30)
beige = (R > 165) & (G > 155) & (B > 120) & (R - B > 10) & (np.abs(R - G) < 60)
ok = green | beige
H, W = ok.shape

best = None
for x0 in range(126, 146):
    for cw in np.arange(86, 93, 0.5):
        xs = [x0 + (c + 0.5) * cw for c in range(7)]
        if xs[-1] > W - 10:
            continue
        for y0 in range(292, 324):
            for ch in np.arange(82, 94, 0.5):
                ys = [y0 + (r + 0.5) * ch for r in range(7)]
                if ys[-1] > H - 10:
                    continue
                cnt = 0; tot = 0
                for yy in ys:
                    iy = int(round(yy))
                    for xx in xs:
                        ix = int(round(xx))
                        cnt += int(ok[iy, ix])
                        tot += 1
                score = cnt / tot
                if best is None or score > best[0]:
                    best = (score, x0, cw, y0, ch)
print("best:", best)
score, x0, cw, y0, ch = best
xs = [round(x0 + i * cw, 1) for i in range(8)]
ys = [round(y0 + i * ch, 1) for i in range(8)]
print("grid x lines:", xs)
print("grid y lines:", ys)
