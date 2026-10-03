# -*- coding: utf-8 -*-
import numpy as np
from PIL import Image
P = r"D:\my_AI_practice\shape_search\pic"
a = np.asarray(Image.open(f"{P}\\img_1.jpg").convert("RGB")).astype(int)
G = a[:, :, 1]
X0, X1, Y0, Y1 = 140, 745, 310, 890
line = (G < 88)
colfrac = line[Y0:Y1, X0:X1].mean(axis=0)
rowfrac = line[Y0:Y1, X0:X1].mean(axis=1)

def peaks(f, off, thresh=0.35):
    idx = np.where(f > thresh)[0]
    groups = []
    if len(idx):
        s = idx[0]; p = idx[0]
        for v in idx[1:]:
            if v - p <= 4:
                p = v
            else:
                groups.append((s, p)); s = v; p = v
        groups.append((s, p))
    return [(int((s + p) / 2 + off), round(float(f[s:p + 1].max()), 2)) for s, p in groups]

print("vertical x:", peaks(colfrac, X0))
print("horizontal y:", peaks(rowfrac, Y0))
# also print min-G positions (grid lines have low G): find local minima
def minima(f, off):
    out = []
    for i in range(2, len(f) - 2):
        if f[i] <= f[i-1] and f[i] <= f[i+1] and f[i] < 0.5:
            out.append((i + off, round(float(f[i]), 2)))
    return out
print("col low-G mins (x,frac):", minima(colfrac, X0)[:60])
