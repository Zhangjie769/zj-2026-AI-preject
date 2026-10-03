# -*- coding: utf-8 -*-
"""Enumerate all valid layouts, storing occupancy mask + per-shape placement.
Shapes are treated as labelled (one each); placements are recorded as codepoints.
"""
import os, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
N = 7

SHAPES = {
    "H2":   [(0, 0), (0, 1)],
    "V2":   [(0, 0), (1, 0)],
    "L3":   [(0, 0), (1, 0), (1, 1)],
    "SQ4":  [(0, 0), (0, 1), (1, 0), (1, 1)],
    "DEER5":[(0, 1), (1, 0), (1, 1), (2, 0), (2, 1)],
}
ORDER = ["DEER5", "SQ4", "L3", "H2", "V2"]   # index 0..4

def bit(r, c):
    return 1 << (r * N + c)

def placements(offsets):
    maxr = max(r for r, c in offsets)
    maxc = max(c for r, c in offsets)
    out = []
    for r0 in range(N - maxr):
        for c0 in range(N - maxc):
            m = 0
            for dr, dc in offsets:
                m |= bit(r0 + dr, c0 + dc)
            out.append(m)
    return out

MASKS = {name: placements(SHAPES[name]) for name in ORDER}
place_masks = [MASKS[name] for name in ORDER]
counts = [len(m) for m in place_masks]

occ = []
ps = [[], [], [], [], []]

def rec(i, o, chosen):
    if i == len(ORDER):
        occ.append(o)
        for k in range(len(ORDER)):
            ps[k].append(chosen[k])
        return
    for codep in range(counts[i]):
        m = place_masks[i][codep]
        if not (m & o):
            chosen.append(codep)
            rec(i + 1, o | m, chosen)
            chosen.pop()

t0 = time.time()
rec(0, 0, [])
t1 = time.time()
occ_arr = np.array(occ, dtype=np.uint64)
ps_arr = np.array(ps, dtype=np.int16).T.reshape(-1, len(ORDER))  # (n,5) contiguous
print("layouts:", len(occ_arr), "time:", round(t1 - t0, 2))

# save
out = {
    "occ": occ_arr,
    "ps": ps_arr,
}
np.savez_compressed(os.path.join(HERE, "data_new.npz"), **out)
print("saved data_new.npz", os.path.getsize(os.path.join(HERE, "data_new.npz")) // (1024 * 1024), "MB")