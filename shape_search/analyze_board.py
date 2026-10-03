# -*- coding: utf-8 -*-
import numpy as np
from PIL import Image

P = r"D:\my_AI_practice\shape_search\pic"
BBOX = (130, 300, 760, 918)   # x0,y0,x1,y1 board region

def green_mask(a):
    R = a[:, :, 0].astype(int); G = a[:, :, 1].astype(int); B = a[:, :, 2].astype(int)
    return (G > R + 15) & (G > B + 40) & (G > 90)

def lines_in(a, x0, y0, x1, y1):
    sub = a[y0:y1 + 1, x0:x1 + 1]
    gm = green_mask(sub)
    colf = gm.mean(axis=0); rowf = gm.mean(axis=1)
    def mins(f, n=7):
        out = []
        L = len(f)
        for i in range(n + 1):
            e = (L - 1) * i / n
            lo = max(0, int(e) - L // (2 * n)); hi = min(L, int(e) + L // (2 * n) + 1)
            j = lo + int(np.argmin(f[lo:hi]))
            out.append(j)
        return out
    xs = [x0 + j for j in mins(colf)]
    ys = [y0 + j for j in mins(rowf)]
    return xs, ys

def cell_stats(a, xs, ys, r, c):
    xa, xb = xs[c], xs[c + 1]; ya, yb = ys[r], ys[r + 1]
    mx = int((xb - xa) * 0.22); my = int((yb - ya) * 0.22)
    cell = a[ya + my:yb - my, xa + mx:xb - mx]
    R = cell[:, :, 0].astype(int); G = cell[:, :, 1].astype(int); B = cell[:, :, 2].astype(int)
    gm = green_mask(cell).mean()
    beige = ((R > 175) & (G > 165) & (B > 130) & (R - B > 15) & (abs(R - G) < 45)).mean()
    sat = (cell.max(axis=2).astype(int) - cell.min(axis=2).astype(int))
    art = ((sat > 55) & (~green_mask(cell))).mean()
    dark = (cell.mean(axis=2) < 110).mean()
    return gm, beige, art, dark

if __name__ == "__main__":
    for name in ("img_1.jpg", "img_0.jpg"):
        a = np.asarray(Image.open(f"{P}\\{name}").convert("RGB"))
        xs, ys = lines_in(a, *BBOX)
        print(name, "xs", xs, "ys", ys)
        print("   cells ~", np.diff(xs).mean().round(1), np.diff(ys).mean().round(1))
        for r in range(7):
            line = []
            for c in range(7):
                gm, be, art, dk = cell_stats(a, xs, ys, r, c)
                if gm > 0.4:
                    t = " . "
                elif be > 0.45 and art < 0.18:
                    t = " E "
                else:
                    t = " A "
                line.append(t)
            print("   " + "".join(line))
        print()
