# -*- coding: utf-8 -*-
"""MC: greedy policy vs lookahead policy on real games."""
import numpy as np, time, random
import engine_new as E

N = E.N
ADV = E.Advisor()

def play(Ti, use_lookahead):
    T = int(E.OCC[Ti])
    sm = [int(E.PSM[s][int(E.PS[Ti, s])]) for s in range(5)]
    occ, emp = set(), set()
    found_ids, found, empties = [], 0, 0
    while found < 5:
        if use_lookahead:
            mv, _ = ADV.lookahead_next_move(occ, emp, found_ids, K=900)
        else:
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
    return empties

if __name__ == "__main__":
    rng = np.random.default_rng(11)
    G = int(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 15
    idx = rng.choice(E.CNT, G, replace=False)
    gv, lv = [], []
    t0 = time.time()
    for g in range(G):
        for use in (False, True):
            E._RNG = np.random.default_rng(100 + g + (7 if use else 0))
            v = play(int(idx[g]), use)
            if use: lv.append(v)
            else: gv.append(v)
        if (g + 1) % 3 == 0:
            print(f"{g+1}/{G}  greedy {np.mean(gv):.2f}  lookahead {np.mean(lv):.2f}  "
                  f"({time.time()-t0:.0f}s)", flush=True)
    print("FINAL greedy mean", np.mean(gv), "lookahead mean", np.mean(lv),
          "| greedy total", 5+np.mean(gv), "lookahead total", 5+np.mean(lv))