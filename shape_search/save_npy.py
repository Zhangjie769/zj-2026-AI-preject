import time
import numpy as np

N = 7

def bit(r, c):
    return 1 << (r * N + c)

SHAPES = {
    "H2":  [(0,0),(0,1)],
    "V2":  [(0,0),(1,0)],
    "L3":  [(0,0),(0,1),(1,0)],
    "SQ4": [(0,0),(0,1),(1,0),(1,1)],
    "DEER5":[(0,0),(0,1),(1,0),(1,1),(1,2)],
}

def placements(offsets):
    maxr = max(r for r,c in offsets)
    maxc = max(c for r,c in offsets)
    out = []
    for r0 in range(N - maxr):
        for c0 in range(N - maxc):
            m = 0
            for dr,dc in offsets:
                m |= bit(r0+dr, c0+dc)
            out.append(m)
    return out

order = ["DEER5", "SQ4", "L3", "H2", "V2"]
place_lists = [placements(SHAPES[n]) for n in order]

configs = []
def rec(i, occ):
    if i == len(order):
        configs.append(occ)
        return
    for m in place_lists[i]:
        if not (m & occ):
            rec(i+1, occ | m)
t0=time.time()
rec(0,0)
arr = np.array(configs, dtype=np.uint64)
print("configs", len(arr), "time", time.time()-t0)
np.save(r"D:\my_AI_practice\shape_search\configs.npy", arr)
print("saved npy")
