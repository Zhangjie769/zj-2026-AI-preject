# -*- coding: utf-8 -*-
"""Compare policies on small samples: greedy / info / blends / one-step-lookahead."""
import numpy as np, math
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

def subsets(state, keys_c, S):
    out = {}
    for h in range(S):
        if (state >> h) & 1:
            k = keys_c[h]
            out.setdefault(k, 0)
            out[k] |= 1 << h
    return out

def evaluate(keys, policy, lam=1.0):
    S = len(keys[0]); memo = {}
    def val(state):
        if popcount(state) <= 1:
            return 0.0
        if state in memo:
            return memo[state]
        tot = popcount(state)
        best_score = -1e18; best_subs = None
        for c in range(49):
            subs = subsets(state, keys[c], S)
            if len(subs) <= 1:
                continue
            none_cnt = sum(popcount(sub) for k, sub in subs.items() if k is None)
            p = 1.0 - none_cnt / tot
            if policy == "greedy":
                score = p
            elif policy == "info":
                score = math.log(tot) - sum((popcount(sub)/tot)*math.log(popcount(sub)) for sub in subs.values())
            elif policy == "blend":
                info = math.log(tot) - sum((popcount(sub)/tot)*math.log(popcount(sub)) for sub in subs.values())
                score = info + lam*p
            elif policy == "lookahead":
                # use greedy value for the future
                score = -((1-p)*(1.0 + gval(subs.get(None, 0)) +
                            sum(gval(sub)*(popcount(sub)/tot) for k, sub in subs.items() if k is not None) / 1)) 
            best = score
            if best > best_score:
                best_score = best; best_subs = subs
        v = 0.0
        for k, sub in best_subs.items():
            cnt = popcount(sub)
            v += (cnt/tot)*((1.0 if k is None else 0.0) + val(sub))
        memo[state] = v
        return v

    gmemo = {}
    def gval(state):
        if popcount(state) <= 1:
            return 0.0
        if state in gmemo:
            return gmemo[state]
        tot = popcount(state)
        best_p = -1.0; best_subs = None
        for c in range(49):
            subs = subsets(state, keys[c], S)
            if len(subs) <= 1:
                continue
            none_cnt = sum(popcount(sub) for k, sub in subs.items() if k is None)
            p = 1.0 - none_cnt/tot
            if p > best_p:
                best_p = p; best_subs = subs
        v = 0.0
        for k, sub in best_subs.items():
            cnt = popcount(sub)
            v += (cnt/tot)*((1.0 if k is None else 0.0) + gval(sub))
        gmemo[state] = v
        return v

    # fix lookahead scoring using gval (defined lazily)
    if policy == "lookahead":
        memo2 = {}
        def val2(state):
            if popcount(state) <= 1:
                return 0.0
            if state in memo2:
                return memo2[state]
            tot = popcount(state)
            best_q = 1e18; best_subs = None
            for c in range(49):
                subs = subsets(state, keys[c], S)
                if len(subs) <= 1:
                    continue
                q = 0.0
                for k, sub in subs.items():
                    cnt = popcount(sub)
                    q += (cnt/tot)*((1.0 if k is None else 0.0) + gval(sub))
                if q < best_q:
                    best_q = q; best_subs = subs
            v = 0.0
            for k, sub in best_subs.items():
                cnt = popcount(sub)
                v += (cnt/tot)*((1.0 if k is None else 0.0) + val2(sub))
            memo2[state] = v
            return v
        return val2((1 << S) - 1)
    return val((1 << S) - 1)

if __name__ == "__main__":
    import time
    Slist = [7, 8, 9, 10, 11]
    trials = 25
    rng = np.random.default_rng(2024)
    policies = [("greedy", 1.0), ("info", 0.0), ("blend", 0.5), ("blend", 1.0),
                ("blend", 2.0), ("blend", 4.0), ("lookahead", 0.0)]
    for S in Slist:
        res = {p[0] + str(p[1]): [] for p in policies}
        t0 = time.time()
        for t in range(trials):
            idx = rng.choice(E.CNT, S, replace=False)
            masks = build_masks(idx); keys = keys_table(masks)
            for pol, lam in policies:
                res[pol + str(lam)].append(evaluate(keys, pol, lam))
        print(f"S={S}")
        for pol, lam in policies:
            v = np.mean(res[pol + str(lam)])
            print(f"    {pol:10s} lam={lam:<4} {v:.4f}")
        print(f"    time {time.time()-t0:.1f}s", flush=True)
