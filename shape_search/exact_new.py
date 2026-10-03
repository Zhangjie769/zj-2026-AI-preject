# -*- coding: utf-8 -*-
"""New-model exact expectimax vs greedy, on small random samples of layouts."""
import numpy as np
import engine_new as E

def popcount(x): return bin(x).count("1")

def build_masks(idx):
    return [[int(E.PSM[s][int(E.PS[h, s])]) for s in range(5)] for h in idx]

def keys_table(masks):
    S = len(masks)
    keys = [[None] * S for _ in range(49)]
    for c in range(49):
        for h in range(S):
            k = None
            for s, m in enumerate(masks[h]):
                if (m >> c) & 1:
                    k = (s, m); break
            keys[c][h] = k
    return keys

def subsets_for(groups_keys, state, S):
    out = {}
    for h in range(S):
        if (state >> h) & 1:
            k = groups_keys[h]
            out.setdefault(k, 0)
            out[k] |= 1 << h
    return out

def exact_value(masks, keys):
    S = len(masks); memo = {}
    def V(state):
        if popcount(state) <= 1:
            return 0.0
        if state in memo:
            return memo[state]
        tot = popcount(state)
        best = 1e18
        for c in range(49):
            subs = subsets_for([keys[c][h] for h in range(S)], state, S)
            if len(subs) <= 1:
                continue
            val = 0.0
            for k, sub in subs.items():
                cnt = popcount(sub)
                val += (cnt / tot) * ((1.0 if k is None else 0.0) + V(sub))
            if val < best:
                best = val
        memo[state] = best
        return best
    return V((1 << S) - 1)

def greedy_value(masks, keys):
    S = len(masks); memo = {}
    def G(state):
        if popcount(state) <= 1:
            return 0.0
        if state in memo:
            return memo[state]
        tot = popcount(state)
        best_p = -1.0; best_subs = None
        for c in range(49):
            subs = subsets_for([keys[c][h] for h in range(S)], state, S)
            if len(subs) <= 1:
                continue
            none_cnt = sum(popcount(sub) for k, sub in subs.items() if k is None)
            p = 1.0 - none_cnt / tot
            if p > best_p:
                best_p = p; best_subs = subs
        val = 0.0
        for k, sub in best_subs.items():
            cnt = popcount(sub)
            val += (cnt / tot) * ((1.0 if k is None else 0.0) + G(sub))
        memo[state] = val
        return val
    return G((1 << S) - 1)

if __name__ == "__main__":
    import sys, time
    Slist = [5, 6, 7, 8, 9, 10, 11]
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    rng = np.random.default_rng(777)
    for S in Slist:
        gs, os_ = [], []
        t0 = time.time()
        for t in range(trials):
            idx = rng.choice(E.CNT, S, replace=False)
            masks = build_masks(idx)
            keys = keys_table(masks)
            gs.append(greedy_value(masks, keys))
            os_.append(exact_value(masks, keys))
        gs = np.array(gs); os_ = np.array(os_)
        gap = (gs.mean() - os_.mean()) / max(os_.mean(), 1e-9) * 100
        print(f"S={S:2d}  greedy {gs.mean():.4f}  exact {os_.mean():.4f}  gap {gap:5.2f}%  "
              f"maxgap {max(gs-os_):.3f}  time {time.time()-t0:.1f}s", flush=True)
