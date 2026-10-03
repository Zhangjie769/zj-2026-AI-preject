# -*- coding: utf-8 -*-
import numpy as np
from PIL import Image
P = r"D:\my_AI_practice\shape_search\pic"
a = np.asarray(Image.open(f"{P}\\img_0.jpg").convert("RGB")).astype(int)
R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
xs = [126, 212, 298, 384, 470, 556, 642, 728]
ys = [292, 380, 468, 556, 644, 732, 820, 908]

grass = (G > 90) & (B < 78) & (G > R - 32)
bright = a.mean(axis=2)
sat = a.max(axis=2) - a.min(axis=2)

def stats(r, c):
    xa, xb, ya, yb = xs[c], xs[c+1], ys[r], ys[r+1]
    mx = int((xb-xa)*0.20); my = int((yb-ya)*0.20)
    cell = np.s_[ya+my:yb-my, xa+mx:xb-mx]
    g = grass[cell].mean()
    dark = (bright[cell] < 95).mean()
    col = ((sat[cell] > 60) & (~grass[cell])).mean()
    return g, dark, col

print("grass fraction per cell:")
for r in range(7):
    print("  " + " ".join(f"{stats(r,c)[0]:4.2f}" for c in range(7)))

revealed = np.zeros((7,7), bool)
kind = {}
print("\nkind: . grass  E empty  A animal")
for r in range(7):
    row = []
    for c in range(7):
        g, dark, col = stats(r, c)
        if g > 0.40:
            t = "."
        else:
            revealed[r,c] = True
            if dark + col < 0.10:
                t = "E"
            else:
                t = "A"
        kind[(r,c)] = t
        row.append(t)
    print("  " + " ".join(row))

# components of revealed incl. animal+empty
seen = np.zeros((7,7), bool)
print("\nrevealed components:")
for r in range(7):
    for c in range(7):
        if revealed[r,c] and not seen[r,c]:
            st=[(r,c)]; seen[r,c]=True; comp=[]
            while st:
                x,y=st.pop(); comp.append((x,y))
                for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                    nx,ny=x+dx,y+dy
                    if 0<=nx<7 and 0<=ny<7 and revealed[nx,ny] and not seen[nx,ny]:
                        seen[nx,ny]=True; st.append((nx,ny))
            comp=sorted(comp)
            kinds=[kind[k] for k in comp]
            print(f"  size={len(comp)} cells={comp} kinds={kinds}")
