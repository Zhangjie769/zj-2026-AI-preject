# -*- coding: utf-8 -*-
"""Measure belief sizes met in real games (how often could exact solving apply)."""
import numpy as np
import engine_new as E

N = E.N
ADV = E.Advisor()

def one_game(Ti):
    T = int(E.OCC[Ti])
    sm = [int(E.PSM[s][int(E.PS[Ti, s])]) for s in range(5)]
    occ, emp = set(), set()
    found_ids, found, empties = [], 0, 0
    sizes = []
    while found < 5:
        sel = ADV._sel(occ, emp, found_ids)
        sizes.append(int(sel.sum()))
        mv, _ = ADV.next_move(occ, emp, found_ids)
        if mv is None:
            break
        i = mv[0] * N + mv[1]
        if (T >> i) & 1:
            s = next(s for s in range(5) if (sm[s] >> i) & 1)
            found += 1
            m = sm[s]
            occ |= {k for k in range(49) if (m >> k) & 1}
            found_ids.append((s, int(E.PS[Ti, s])))
        else:
            empties += 1
            emp.add(i)
    return sizes

if __name__ == "__main__":
    rng = np.random.default_rng(55)
    all_sizes = []
    for g in range(40):
        all_sizes.append(one_game(int(rng.integers(E.CNT))))
    flat = [s for lst in all_sizes for s in lst]
    flat.sort()
    n = len(flat)
    print("总决策步数:", n)
    for thr in (100, 500, 700, 2000, 5000, 20000, 100000, 500000):
        cnt = sum(1 for s in flat if s <= thr)
        print(f"  剩余布局 <= {thr:>7}: {cnt:4d} 步 ({100*cnt/n:.1f}%)")
    print("中位数剩余布局:", flat[n // 2], " 第75分位:", flat[int(n*0.75)])