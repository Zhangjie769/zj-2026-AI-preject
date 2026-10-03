import numpy as np, time, random, math, collections, sys, json

configs = np.load(r"D:\my_AI_practice\shape_search\configs.npy")
n = len(configs)
W = (n + 63) // 64

def build_B():
    B = np.zeros((49, W), dtype=np.uint64)
    for c in range(49):
        has = ((configs >> np.uint64(c)) & np.uint64(1)).astype(np.uint64)
        pw = np.zeros(W, dtype=np.uint64)
        pad = np.zeros(W*64 - n, dtype=np.uint64)
        hh = np.concatenate([has, pad])
        for j in range(64):
            pw |= (hh[j::64] << np.uint64(j))
        B[c] = pw
    return B

B = build_B()
ALL = np.full(W, np.uint64(0xFFFFFFFFFFFFFFFF))
rem = n % 64
if rem:
    ALL[-1] = np.uint64((1 << rem) - 1)

def ptotal(bits):
    return int(np.bitwise_count(bits).sum(dtype=np.int64))

def counts(bits):
    return np.bitwise_count(B & bits).sum(axis=1, dtype=np.int64)

def entropy_gain(cs, total):
    # returns info gain (nats) for each cell
    t = float(total)
    H0 = math.log(t) if t > 0 else 0.0
    cy = cs.astype(np.float64)
    cn = t - cy
    # -[p log cy + q log cn]
    term = np.zeros_like(cy)
    m1 = (cy > 0) & (cy < t)
    out = np.zeros_like(cy)
    p = cy[m1] / t
    q = cn[m1] / t
    # gain = ln t - (p ln cy + q ln cn)   [nats]
    out[m1] = H0 - (p * np.log(cy[m1]) + q * np.log(cn[m1]))
    return out

def choose(cs, total, policy, lam=1.0):
    determined = (cs == 0) | (cs == total)
    amb = ~determined
    if not amb.any():
        return -1
    p = cs.astype(np.float64)/total
    if policy == "greedy":
        score = p.copy()
    elif policy == "info":
        score = entropy_gain(cs, total)
    elif policy == "blend":
        score = entropy_gain(cs, total) + lam*p
    elif policy == "infominus":
        score = entropy_gain(cs, total) - lam*(1-p)
    score[~amb] = -1e18
    return int(np.argmax(score))

def play(t_index, policy="greedy", lam=1.0):
    T = configs[t_index]
    bits = ALL.copy()
    empties = 0
    while True:
        total = ptotal(bits)
        cs = counts(bits)
        c = choose(cs, total, policy, lam)
        if c < 0:
            break
        occ = bool((T >> np.uint64(c)) & np.uint64(1))
        if occ:
            bits = bits & B[c]
        else:
            empties += 1
            bits = bits & ~B[c]
    return empties

def mc(policy, lam, N, seed):
    random.seed(seed)
    es = np.empty(N, dtype=np.int64)
    for i in range(N):
        es[i] = play(random.randrange(n), policy, lam)
    return es

if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    configs_to_test = [
        ("greedy", 1.0),
        ("info", 0.0),
        ("blend", 0.25),
        ("blend", 0.5),
        ("blend", 1.0),
        ("blend", 2.0),
        ("blend", 4.0),
    ]
    results = {}
    for pol, lam in configs_to_test:
        t0=time.time()
        es = mc(pol, lam, N, 999)
        key = f"{pol}_{lam}"
        results[key] = (float(es.mean()), float(es.std()), int(es.min()), int(es.max()), round(time.time()-t0,1))
        print(key, "mean", round(es.mean(),3), "std", round(es.std(),3), "min", es.min(), "max", es.max(), "time", round(time.time()-t0,1), flush=True)
    with open(r"D:\my_AI_practice\shape_search\policy_results.json","w") as f:
        json.dump(results, f, indent=2)
