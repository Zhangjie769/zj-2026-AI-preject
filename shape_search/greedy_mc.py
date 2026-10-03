import numpy as np, time, collections
from policy_compare import mc, n
t0=time.time()
es = mc("greedy", 1.0, 1000, 42)
print("greedy N=1000 mean empties", round(float(es.mean()),4), "std", round(float(es.std()),4),
      "SE", round(float(es.std())/np.sqrt(len(es)),4), "min", int(es.min()), "max", int(es.max()),
      "mean total", round(16+float(es.mean()),4), "time", round(time.time()-t0,1))
print("percentiles 5/25/50/75/95:", np.percentile(es,[5,25,50,75,95]))
print("histogram:", sorted(collections.Counter(es.tolist()).items()))
