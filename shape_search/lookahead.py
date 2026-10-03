"""Compare the greedy policy with a one-step-lookahead policy on a sample."""
import numpy as np, time, random, sys
sys.setrecursionlimit(100000)

configs = np.load(r"D:\my_AI_practice\shape_search\configs.npy")
n = len(configs)

def make_sample(S, seed):
    rng = np.random.default_rng(seed)
    idx = rng.choice(n, size=S, replace=False)
    masks = configs[idx]
    H = np.zeros((S, 49), dtype=np.uint8)
    for c in range(49):
        H[:, c] = ((masks >> np.uint64(c)) & np.uint64(1)).astype(np.uint8)
    return H

def greedy_value(H, idx, memo, depth=0):
    """Expected empty clicks for greedy play on the hypotheses H[idx]."""
    m = len(idx)
    if m <= 1:
        return 0.0
    key = idx.tobytes()
    if key in memo:
        return memo[key]
    Hs = H[idx]
    counts = Hs.sum(axis=0).astype(np.int64)
    determined = (counts == 0) | (counts == m)
    if determined.all():
        memo[key] = 0.0
        return 0.0
    masked = np.where(determined, -1, counts)
    c = int(np.argmax(masked))
    yes = idx[Hs[:, c] == 1]
    no = idx[Hs[:, c] == 0]
    py = len(yes) / m
    val = (1 - py) * (1.0 + greedy_value(H, no, memo, depth + 1)) + py * greedy_value(H, yes, memo, depth + 1)
    memo[key] = val
    return val

def greedy_choice(H, idx):
    Hs = H[idx]
    counts = Hs.sum(axis=0).astype(np.int64)
    determined = (counts == 0) | (counts == len(idx))
    masked = np.where(determined, -1, counts)
    return int(np.argmax(masked))

def lookahead_root(H):
    S = len(H)
    allidx = np.arange(S)
    memo = {}
    base = greedy_value(H, allidx, memo)
    # value of each first probe then greedy
    Q = np.full(49, np.inf)
    for c in range(49):
        yes = np.nonzero(H[:, c] == 1)[0]
        no = np.nonzero(H[:, c] == 0)[0]
        py = len(yes) / S
        q = (1 - py) * (1.0 + greedy_value(H, no, memo, 1)) + py * greedy_value(H, yes, memo, 1)
        Q[c] = q
    bc = int(np.argmin(Q))
    gc = greedy_choice(H, allidx)
    return base, Q, bc, gc

if __name__ == "__main__":
    S = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    seeds = [1, 2, 3]
    for sd in seeds:
        H = make_sample(S, sd)
        t0 = time.time()
        base, Q, bc, gc = lookahead_root(H)
        order = np.argsort(Q)
        print(f"seed {sd} S={S}: greedy first move {divmod(gc,7)}, value {base:.4f}")
        print(f"   best first probe {divmod(bc,7)} value {Q[bc]:.4f} (improvement {base-Q[bc]:.4f})")
        print("   top6 probes:", [(divmod(int(c),7), round(float(Q[c]),4)) for c in order[:6]])
        print("   time", round(time.time()-t0,1))
