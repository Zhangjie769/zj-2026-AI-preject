import time
from collections import Counter

N = 7

def bit(r, c):
    return 1 << (r * N + c)

# Shapes in fixed orientation (offsets)
SHAPES = {
    "H2":  [(0,0),(0,1)],
    "V2":  [(0,0),(1,0)],
    "L3":  [(0,0),(0,1),(1,0)],          # L-tromino
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

names = list(SHAPES.keys())
PL = {name: placements(SHAPES[name]) for name in names}
for name in names:
    print(name, "placements:", len(PL[name]))

# order: place biggest first
order = ["DEER5", "SQ4", "L3", "H2", "V2"]
place_lists = [PL[n] for n in order]

configs = []
t0 = time.time()

def rec(i, occ):
    if i == len(order):
        configs.append(occ)
        return
    for m in place_lists[i]:
        if not (m & occ):
            rec(i+1, occ | m)

rec(0, 0)
t1 = time.time()
print("total configs:", len(configs), "time:", round(t1-t0,2), "s")

# distinct unions
uni = set(configs)
print("distinct union masks:", len(uni))

# occupancy frequency
freq = [0]* (N*N)
for m in configs:
    mm = m
    while mm:
        b = mm & (-mm)
        idx = b.bit_length()-1
        freq[idx]+=1
        mm ^= b

print("occupancy probability map (percent):")
tot = len(configs)
for r in range(N):
    row = []
    for c in range(N):
        p = 100.0*freq[r*N+c]/tot
        row.append(f"{p:5.1f}")
    print(" ".join(row))

# save configs
with open(r"D:\my_AI_practice\shape_search\configs.txt","w") as f:
    for m in configs:
        f.write(str(m)+"\n")
print("saved")
