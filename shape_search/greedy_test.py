import numpy as np, time, random

configs = np.load(r"D:\my_AI_practice\shape_search\configs.npy")
n = len(configs)
print("n", n)

def counts(sub):
    nsub = len(sub)
    cs = np.empty(49, dtype=np.int64)
    for i in range(49):
        cs[i] = np.count_nonzero(sub & np.uint64(1 << i))
    return cs

def play(t_index, verbose=False):
    T = configs[t_index]
    sub = configs
    empties = 0
    clicks = 0
    steps = 0
    while True:
        nsub = len(sub)
        cs = counts(sub)
        determined = (cs == 0) | (cs == nsub)
        if determined.all():
            break
        # ambiguous
        masked = np.where(determined, -1, cs)
        c = int(np.argmax(masked))
        clicks += 1
        occ = bool((T >> np.uint64(c)) & np.uint64(1))
        if occ:
            sub = sub[(sub >> np.uint64(c)) & np.uint64(1) == 1]
        else:
            empties += 1
            sub = sub[(sub >> np.uint64(c)) & np.uint64(1) == 0]
        steps += 1
        if verbose:
            print("probe", divmod(c,7), "occ" if occ else "EMPTY", "|sub|", len(sub))
    return empties, steps

t0=time.time()
random.seed(1)
e,s = play(random.randrange(n), verbose=True)
print("one game empties", e, "steps", s, "time", round(time.time()-t0,2))
