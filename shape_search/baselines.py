"""Baselines: random order and best fixed order (non-adaptive)."""
import numpy as np

configs = np.load(r"D:\my_AI_practice\shape_search\configs.npy")
n = len(configs)
N = 7

# occupancy marginal
freq = np.zeros(49, dtype=np.int64)
for c in range(49):
    freq[c] = np.count_nonzero(configs & np.uint64(1 << c))

# expected empties for a fixed order: for each config, position of last occupied - 16
def fixed_order_cost(order):
    order = np.asarray(order)
    # position (1..49) of each cell in the order
    pos = np.empty(49, dtype=np.int64)
    pos[order] = np.arange(1, 50)
    total = 0
    # compute max position among occupied per config
    # vectorize over cells: get bit matrices
    maxpos = np.zeros(n, dtype=np.int64)
    # process configs in chunks
    step = 200000
    for s in range(0, n, step):
        sub = configs[s:s+step]
        mp = np.zeros(len(sub), dtype=np.int64)
        for c in range(49):
            has = ((sub >> np.uint64(c)) & np.uint64(1)).astype(bool)
            mp[has] = np.maximum(mp[has], pos[c])
        maxpos[s:s+step] = mp
    return float(np.mean(maxpos - 16))

# best fixed order: sort by marginal descending
order_marg = np.argsort(-freq)
print("marginal order (row,col):", [divmod(int(c),7) for c in order_marg])
print("fixed-order (marginal-desc) expected empties:", fixed_order_cost(order_marg))

# random order expectation via formula / simulation
rng = np.random.default_rng(0)
vals = []
for _ in range(200):
    o = rng.permutation(49)
    # cheap: only compute on a sample of configs
    sam = configs[rng.choice(n, size=20000, replace=False)]
    pos = np.empty(49, dtype=np.int64); pos[o] = np.arange(1, 50)
    mp = np.zeros(len(sam), dtype=np.int64)
    for c in range(49):
        has = ((sam >> np.uint64(c)) & np.uint64(1)).astype(bool)
        mp[has] = np.maximum(mp[has], pos[c])
    vals.append(np.mean(mp - 16))
print("random fixed order expected empties (approx):", float(np.mean(vals)))
