import numpy as np, time, random

configs = np.load(r"D:\my_AI_practice\shape_search\configs.npy")
n = len(configs)
W = (n + 63) // 64

t0 = time.time()
# per-cell bitset as uint64 words
B = np.zeros((49, W), dtype=np.uint64)
for c in range(49):
    has = ((configs >> np.uint64(c)) & np.uint64(1)).astype(np.uint64)
    pw = np.zeros(W, dtype=np.uint64)
    # pack 64 booleans per word: word k = sum has[k*64+j] << j
    pad = np.zeros(W*64 - n, dtype=np.uint64)
    hh = np.concatenate([has, pad])
    for j in range(64):
        pw |= (hh[j::64] << np.uint64(j))
    B[c] = pw
ALL = np.full(W, np.uint64(0xFFFFFFFFFFFFFFFF))
rem = n % 64
if rem:
    ALL[-1] = np.uint64((1 << rem) - 1)
print("B built", B.shape, "time", round(time.time()-t0, 2))

def ptotal(bits):
    return int(np.bitwise_count(bits).sum(dtype=np.int64))

def counts(bits):
    return np.bitwise_count(B & bits).sum(axis=1, dtype=np.int64)

def play(t_index, verbose=False, policy="greedy"):
    T = configs[t_index]
    bits = ALL.copy()
    empties = 0
    steps = 0
    trace = []
    while True:
        total = ptotal(bits)
        cs = counts(bits)
        determined = (cs == 0) | (cs == total)
        if determined.all():
            break
        masked = np.where(determined, -1, cs).astype(np.int64)
        c = int(np.argmax(masked))
        steps += 1
        occ = bool((T >> np.uint64(c)) & np.uint64(1))
        if occ:
            bits = bits & B[c]
        else:
            empties += 1
            bits = bits & ~B[c]
        if verbose:
            trace.append((divmod(c,7), occ, ptotal(bits)))
    if verbose:
        return empties, steps, trace
    return empties, steps

if __name__ == "__main__":
    random.seed(2)
    t0=time.time()
    e,s,tr = play(random.randrange(n), verbose=True)
    print("one game empties",e,"steps",s,"time",round(time.time()-t0,3))
    for row in tr: print(row)

    # Monte Carlo
    t0=time.time()
    N=200
    random.seed(12345)
    es=[]
    for _ in range(N):
        e,s=play(random.randrange(n))
        es.append(e)
    es=np.array(es)
    print("greedy MC N=",N,"mean empties",es.mean(),"std",es.std(),"min",es.min(),"max",es.max(),"time",round(time.time()-t0,1))
    import collections
    print(sorted(collections.Counter(es.tolist()).items()))
