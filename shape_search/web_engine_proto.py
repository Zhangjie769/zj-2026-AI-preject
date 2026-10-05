# -*- coding: utf-8 -*-
"""Prototype of the JS engine (for the single-file web version):
   - exact backtracking enumeration with a node cap (small beliefs)
   - uniform rejection sampling (big beliefs)
   Validate that its recommended cell matches the desktop exact engine.
"""
import random
import numpy as np
import engine_new as E

N = 7
SHAPES = {
    "H2":   [(0, 0), (0, 1)],
    "V2":   [(0, 0), (1, 0)],
    "L3":   [(0, 0), (1, 0), (1, 1)],
    "SQ4":  [(0, 0), (0, 1), (1, 0), (1, 1)],
    "DEER5":[(0, 1), (1, 0), (1, 1), (2, 0), (2, 1)],
}
ORDER = ["DEER5", "SQ4", "L3", "H2", "V2"]

def placements(off):
    mr = max(r for r, c in off); mc = max(c for r, c in off)
    out = []
    for r0 in range(N - mr):
        for c0 in range(N - mc):
            m = 0
            for dr, dc in off:
                m |= 1 << ((r0 + dr) * N + (c0 + dc))
            out.append(m)
    return out

PL = [placements(SHAPES[n]) for n in ORDER]     # per shape index (ORDER)
CELLS = [[i for i in range(49) if (m >> i) & 1] for s in range(5) for m in PL[s]]

def bits(m):
    out = []
    i = 0
    while m:
        if m & 1: out.append(i)
        m >>= 1; i += 1
    return out

def recommend(occ, empty, found, cap=800000, K=40000, max_attempts=2000000, rng=None):
    occ = set(occ); empty = set(empty)
    found_shapes = set(s for s, _ in found)
    base = 0
    for s, cp in found:
        base |= PL[s][cp]
    remaining = [s for s in range(5) if s not in found_shapes]
    remaining.sort(key=lambda s: -len(SHAPES[ORDER[s]]))
    occ_m = 0
    for c in occ: occ_m |= 1 << c
    emp_m = 0
    for c in empty: emp_m |= 1 << c

    # ---- exact enumeration with node cap ----
    counts = [0] * 49
    total = [0]
    nodes = [0]
    aborted = [False]
    def rec(i, used):
        nodes[0] += 1
        if nodes[0] > cap:
            aborted[0] = True; return
        if i == len(remaining):
            if (used & emp_m) or ((used & occ_m) != occ_m):
                return
            total[0] += 1
            for c in bits(used): counts[c] += 1
            return
        s = remaining[i]
        for p in PL[s]:
            if p & used: continue
            rec(i + 1, used | p)
            if aborted[0]: return
    rec(0, base)

    if not aborted[0] and total[0] > 0:
        method = "exact"
        tot = total[0]; cnt = counts
    else:
        method = "sample"
        rng = rng or random.Random(12345)
        cnt = [0] * 49; tot = 0; att = 0
        while tot < K and att < max_attempts:
            att += 1
            used = base; ok = True
            for s in remaining:
                p = PL[s][rng.randrange(len(PL[s]))]
                if p & used: ok = False; break
                used |= p
            if not ok: continue
            if (used & emp_m) or ((used & occ_m) != occ_m): continue
            tot += 1
            for c in bits(used): cnt[c] += 1
    cand = [c for c in range(49) if c not in occ and c not in empty]
    best = max(cand, key=lambda c: cnt[c])
    return best, method, tot, nodes[0]

if __name__ == "__main__":
    ADV = E.Advisor()
    def place(s, r, c):
        tpl = E.SHAPES[E.ORDER[s]]
        minr = min(dr for dr, dc in tpl); minc = min(dc for dr, dc in tpl if dr == minr)
        m = 0
        for dr, dc in tpl:
            m |= 1 << ((r + dr - minr) * N + (c + dc - minc))
        return (s, E.PSM[s].index(m), m)
    rng = np.random.default_rng(4)
    match = 0; trials = 200
    methods = {}
    for t in range(trials):
        h = int(rng.integers(E.CNT))
        k = int(rng.integers(1, 5))
        chosen = list(rng.permutation(5)[:k])
        # build a consistent state from the true layout h: reveal k animals of h
        found = []; occ = set()
        for s in chosen:
            cp = int(E.PS[h, s]); m = E.PSM[s][cp]
            found.append((int(s), cp))
            occ |= {i for i in range(49) if (m >> i) & 1}
        empty = set()
        while len(empty) < int(rng.integers(0, 4)):
            c = int(rng.integers(49))
            if c not in occ: empty.add(c)
        b, method, tot, nodes = recommend(occ, empty, found, rng=random.Random(t))
        adv, _ = ADV.next_move(occ, empty, found)
        advc = adv[0] * N + adv[1]
        methods[method] = methods.get(method, 0) + 1
        if b == advc:
            match += 1
    print(f"[有已找到动物] recommendation match: {match}/{trials}")
    print("methods used:", methods)

    # ---- early game: no animal found yet (uses sampling) ----
    match2 = 0; trials2 = 60; methods2 = {}
    for t in range(trials2):
        empty = set()
        while len(empty) < int(rng.integers(0, 7)):
            empty.add(int(rng.integers(49)))
        b, method, tot, nodes = recommend(set(), empty, [], rng=random.Random(1000 + t))
        adv, _ = ADV.next_move(set(), empty, [])
        advc = adv[0] * N + adv[1]
        methods2[method] = methods2.get(method, 0) + 1
        if b == advc:
            match2 += 1
    print(f"[空空盘/早期] recommendation match: {match2}/{trials2}")
    print("methods used:", methods2)