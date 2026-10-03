"""On a small random sample of layouts, compare greedy with the EXACT optimal
policy (expectimax over hypothesis subsets).  Gives a sense of the optimality gap."""
import numpy as np, sys, math, time
from functools import lru_cache

configs = np.load(r"D:\my_AI_practice\shape_search\configs.npy")
n = len(configs)

def popcount(x):
    return bin(x).count("1")

def run_trial(S, seed):
    rng = np.random.default_rng(seed)
    idx = rng.choice(n, size=S, replace=False)
    masks = configs[idx]
    # Bc[c] = bitmask over hypotheses where cell c occupied
    Bc = []
    for c in range(49):
        m = 0
        for j in range(S):
            if (int(masks[j]) >> c) & 1:
                m |= (1 << j)
        Bc.append(m)
    full = (1 << S) - 1
    memo = {}

    def is_resolved(state):
        tot = popcount(state)
        for B in Bc:
            k = popcount(state & B)
            if k != 0 and k != tot:
                return False
        return True

    def greedy_value(state):
        if is_resolved(state):
            return 0.0
        if state in memo:
            return memo[state]
        tot = popcount(state)
        best_c = -1
        best_cnt = -1
        counts = []
        for B in Bc:
            k = popcount(state & B)
            counts.append(k)
            if 0 < k < tot and k > best_cnt:
                best_cnt = k
                best_c = B
        # greedy chooses max count (tie -> first)
        c_best = None
        bc = -1
        for i, k in enumerate(counts):
            if 0 < k < tot and k > bc:
                bc = k
                c_best = i
        B = Bc[c_best]
        yes = state & B
        no = state & ~B
        py = bc / tot
        val = (1 - py) * (1 + greedy_value(no)) + py * greedy_value(yes)
        memo[state] = val
        return val

    def optimal_value(state):
        if is_resolved(state):
            return 0.0
        if state in memo2:
            return memo2[state]
        tot = popcount(state)
        best = float("inf")
        seen = set()
        for i, B in enumerate(Bc):
            k = popcount(state & B)
            if k == 0 or k == tot:
                continue
            yes = state & B
            no = state & ~B
            py = k / tot
            v = (1 - py) * (1 + optimal_value(no)) + py * optimal_value(yes)
            if v < best:
                best = v
        memo2[state] = best
        return best

    memo2 = {}
    g = greedy_value(full)
    o = optimal_value(full)
    return g, o

if __name__ == "__main__":
    maxS = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    for S in range(4, maxS + 1):
        gs, os_ = [], []
        t0 = time.time()
        for t in range(trials):
            g, o = run_trial(S, 1000 + t)
            gs.append(g); os_.append(o)
        gs = np.array(gs); os_ = np.array(os_)
        print(f"S={S}: greedy {gs.mean():.4f}  optimal {os_.mean():.4f}  gap {100*(gs.mean()-os_.mean())/max(os_.mean(),1e-9):.2f}%  time {time.time()-t0:.1f}")
