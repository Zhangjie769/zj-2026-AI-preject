import numpy as np, time, random

configs = np.load(r"D:\my_AI_practice\shape_search\configs.npy")
n = len(configs)

t0 = time.time()
# Build per-cell bitsets: B[c] is a bitset over configs, bit j set if config j covers cell c
B = np.empty((49, (n + 7) // 8), dtype=np.uint8)
for c in range(49):
    has = ((configs >> np.uint64(c)) & np.uint64(1)).astype(np.uint8)
    B[c] = np.packbits(has)
ALL = np.full((n + 7) // 8, 0xFF, dtype=np.uint8)
# clear padding bits beyond n
rem = n % 8
if rem:
    ALL[-1] = (1 << rem) - 1
print("B built", B.shape, "time", round(time.time()-t0, 2))

def popcount_total(bits):
    return int(np.bitwise_count(bits).sum(dtype=np.int64))

def counts(bits):
    return np.bitwise_count(B & bits).sum(axis=1, dtype=np.int64)

def play(t_index, policy="greedy", verbose=False):
    T = configs[t_index]
    bits = ALL.copy()
    empties = 0
    steps = 0
    trace = []
    while True:
        total = popcount_total(bits)
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
            trace.append((divmod(c,7), occ, popcount_total(bits)))
    if verbose:
        return empties, steps, trace
    return empties, steps

if __name__ == "__main__":
    random.seed(2)
    t0=time.time()
    e,s,tr = play(random.randrange(n), verbose=True)
    print("one game empties",e,"steps",s,"time",round(time.time()-t0,3))
    for row in tr:
        print(row)
