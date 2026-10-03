# -*- coding: utf-8 -*-
import numpy as np
from PIL import Image
P = r"D:\my_AI_practice\shape_search\pic"
imgs = {n: np.asarray(Image.open(f"{P}\\{n}.jpg").convert("RGB")) for n in ("img_1", "img_0")}

# candidate grid (from visual estimate)
xs = [134, 222, 309, 397, 484, 572, 659, 747]
ys = [304, 389, 473, 558, 642, 726, 811, 895]
cx = [int((xs[i] + xs[i + 1]) / 2) for i in range(7)]
cy = [int((ys[i] + ys[i + 1]) / 2) for i in range(7)]
print("centers x", cx); print("centers y", cy)
for name, a in imgs.items():
    print("==", name)
    for r in range(7):
        row = []
        for c in range(7):
            y, x = cy[r], cx[c]
            patch = a[y - 8:y + 8, x - 8:x + 8].reshape(-1, 3).mean(axis=0)
            row.append("{:3.0f},{:3.0f},{:3.0f}".format(*patch))
        print("  ", " | ".join(row))
