# -*- coding: utf-8 -*-
"""Monte Carlo: greedy policy under the NEW model, with and without using the
revealed shape identity/placement to tighten the posterior."""
import numpy as np, time, random, collections, sys
import engine_new as E

N = E.N

def play(Ti, use_identity):
    T = int(E.OCC[Ti])
    sm = [int(E.PSM[s][int(E.PS[Ti, s])]) for s in range(5)]
    learned_occ = set()
    learned_empty = set()
    found_ids = []          # (shape, codepoint)
    found = 0
    empties = 0
    ad = E.Advisor()
    while found < 5:
        if use_identity == "detect":
            found_ids = E.detect_shapes(learned_occ)
        sel = ad._sel(learned_occ, learned_empty, found_ids if use_identity in ("identity", "detect") else None)
        total = int(sel.sum())
        if total == 0:
            return -1
        cs = ad.counts(sel)
        cand = [c for c in range(N * N) if c not in learned_occ and c not in learned_empty]
        c = max(cand, key=lambda x: cs[x])
        if (T >> c) & 1:
            s = next(s for s in range(5) if (sm[s] >> c) & 1)
            found += 1
            m = sm[s]
            learned_occ |= {i for i in range(N * N) if (m >> i) & 1}
            found_ids.append((s, int(E.PS[Ti, s])))
        else:
            empties += 1
            learned_empty.add(c)
    return empties

if __name__ == "__main__":
    G = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    for use_id in (False, "detect"):
        random.seed(2025)
        vals = []
        t0 = time.time()
        for _ in range(G):
            v = play(random.randrange(E.CNT), use_id)
            vals.append(v)
        vals = np.array(vals)
        tag = "detect-identity" if use_id else "occupancy-only"
        print(f"[{tag}] G={G} mean empties {vals.mean():.4f} std {vals.std():.3f} "
              f"min {vals.min()} max {vals.max()} total {5+vals.mean():.4f} "
              f"time {time.time()-t0:.1f}s", flush=True)