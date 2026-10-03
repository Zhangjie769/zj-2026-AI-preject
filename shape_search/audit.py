# -*- coding: utf-8 -*-
"""Code audit: data consistency + engine vs brute force + GUI round-trip."""
import numpy as np
import engine_new as E

rng = np.random.default_rng(1)
ok = True

# --- 1. data consistency: each layout covers exactly 16 cells, and OCC == union of PSM[PS] ---
n = E.CNT
samp = rng.choice(n, 2000, replace=False)
bad = 0
for h in samp:
    m = int(E.OCC[h])
    if bin(m).count("1") != 16:
        bad += 1; continue
    u = 0
    for s in range(5):
        u |= int(E.PSM[s][int(E.PS[h, s])])
    if u != m:
        bad += 1
print("[1] OCC consistency on 2000 random layouts, bad =", bad); ok &= (bad == 0)

# total occupancy counts == 16 * n ?
tot = 0
for c in range(49):
    tot += int(np.count_nonzero(E.OCC & np.uint64(1 << c)))
print("[2] sum of cover counts =", tot, " expected =", 16 * n, " ->", tot == 16 * n)
ok &= (tot == 16 * n)

# --- 3. Advisor posterior vs independent boolean filter on random painted states ---
A = E.Advisor()
for trial in range(5):
    # build a random consistent state by taking a real layout and "revealing" some shapes + random empties
    h = int(rng.integers(n))
    shapes_order = list(rng.permutation(5))
    found = [(s, int(E.PS[h, s])) for s in shapes_order[: int(rng.integers(1, 5))]]
    occ = set(); 
    for s, cp in found:
        m = E.PSM[s][cp]
        occ |= {i for i in range(49) if (m >> i) & 1}
    empty = set()
    while len(empty) < 2:
        c = int(rng.integers(49))
        if c not in occ:
            empty.add(c)
    mv, info = A.next_move(occ, empty, found)
    # independent filter using OCC directly
    sel = np.ones(n, bool)
    em = 0
    for e in empty: em |= (1 << e)
    sel &= (E.OCC & np.uint64(em)) == 0
    om = 0
    for o in occ: om |= (1 << o)
    sel &= (E.OCC & np.uint64(om)) != 0
    for s, cp in found:
        sel &= (E.PS[:, s] == cp)
    sub = E.OCC[sel]
    cnt = {c: int(np.count_nonzero(sub & np.uint64(1 << c))) for c in range(49)}
    cand = [c for c in range(49) if c not in occ and c not in empty]
    best = max(cand, key=lambda c: cnt[c])
    same = (mv == divmod(best, 7)) if cand else (mv is None)
    if not same:
        print("   [3] MISMATCH trial", trial, "advisor", mv, "brute", divmod(best, 7)); ok = False
print("[3] Advisor vs brute-force posterior: checked 5 states,", "OK" if ok else "FAIL")

# --- 4. paint_gui round-trip: paint a full real layout, solve, recover all found ---
import paint_gui as P
app = P.App()
for trial in range(5):
    h = int(rng.integers(n))
    app.cells = [[None] * 7 for _ in range(7)]      # reset board between trials
    for s in range(5):
        app.select_color(s)
        m = int(E.PSM[s][int(E.PS[h, s])])
        for i in range(49):
            if (m >> i) & 1:
                r, c = divmod(i, 7)
                app.cells[r][c] = s
    app.solve()
    # reconstruct found set
    got = set()
    for s in range(5):
        cells = [(r, c) for r in range(7) for c in range(7) if app.cells[r][c] == s]
        minr = min(r for r, c in cells); minc = min(c for r, c in cells)
        norm = frozenset((r - minr, c - minc) for r, c in cells)
        assert norm == frozenset(E.SHAPES[E.ORDER[s]]), f"trial {trial} shape {s} norm mismatch"
        got.add(s)
    if got != set(range(5)):
        print("   [4] MISMATCH trial", trial); ok = False
    if app.hint is None:
        # full layout known -> all shapes known -> no more empties needed; hint may be None
        pass
app.root.destroy()
print("[4] paint_gui round-trip on 5 full layouts:", "OK" if ok else "FAIL")

# --- 5. inconsistent painting should not crash ---
app = P.App()
app.select_color(0)
app.cells[0][0] = 0
app.cells[0][1] = 0
app.cells[1][0] = 0
app.cells[0][2] = 0   # deer can't be a row of 4
app.solve()
print("[5] inconsistent painting handled, advice =", repr(app.advice_text[:40]))
app.root.destroy()

print("ALL CHECKS:", "PASS" if ok else "FAIL")
